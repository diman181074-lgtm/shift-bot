from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy import select

from app.db import SessionLocal
from app.group_notifications import chat_id_for_venue, send_shift_offer
from app.models import AuditLog, Employee, RequestStatus, Role, Shift, ShiftStatus, SubstitutionRequest, Venue
from app.notifications import notify
from app.services import claim_shift as claim_shift_service
from app.services import create_shift, decide_request, employee_by_telegram, give_shift as give_shift_service, shift_label

router = Router()


class CreateShiftState(StatesGroup):
    employee = State()
    date = State()
    start = State()
    end = State()
    confirm = State()


def main_menu(role: Role = Role.EMPLOYEE) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="Мои смены"), KeyboardButton(text="Отдать смену")],
        [KeyboardButton(text="Доступные смены"), KeyboardButton(text="Мои заявки")],
        [KeyboardButton(text="История"), KeyboardButton(text="Уведомления")],
        [KeyboardButton(text="Профиль")],
    ]
    if role in (Role.MANAGER, Role.ADMIN):
        rows.append([KeyboardButton(text="Создать смену"), KeyboardButton(text="Заявки менеджера")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]])


def shift_buttons(prefix: str, shifts: list[Shift]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"#{s.id} · {s.date:%d.%m} {s.start_time}–{s.end_time}", callback_data=f"{prefix}:{s.id}")]
            for s in shifts
        ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]]
    )


def employees_keyboard(employees: list[Employee]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{e.full_name} · {e.position}", callback_data=f"create_employee:{e.id}")]
            for e in employees
        ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="create_cancel")]]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="create_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="create_cancel")],
    ])


async def get_employee(message: Message) -> Employee | None:
    async with SessionLocal() as session:
        return await employee_by_telegram(session, message.from_user.id)


async def notify_managers(bot, text: str) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Employee).where(Employee.role.in_([Role.MANAGER, Role.ADMIN]), Employee.is_active.is_(True)))
        managers = result.scalars().all()
    for manager in managers:
        await notify(bot, manager, text)


@router.message(Command("chatid"))
async def chat_id_command(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Эту команду нужно отправить внутри рабочей Telegram-беседы.")
        return
    await message.answer(f"ID этой беседы: <code>{message.chat.id}</code>", parse_mode="HTML")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    employee = await get_employee(message)
    if employee is None:
        await message.answer("Ты ещё не зарегистрирован в системе. Обратись к менеджеру.")
        return
    await message.answer(f"Привет, {employee.full_name}!\nВыбери действие:", reply_markup=main_menu(employee.role))


@router.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    employee = await get_employee(callback.message)
    if employee:
        await callback.message.edit_text("Главное меню")
        await callback.message.answer("Выбери действие:", reply_markup=main_menu(employee.role))
    await callback.answer()


@router.message(F.text == "Мои смены")
async def my_shifts(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.date >= datetime.now(timezone.utc)).order_by(Shift.date))
        shifts = result.scalars().all()
    await message.answer("Твои смены:\n\n" + ("\n".join(f"#{s.id} — {shift_label(s)}" for s in shifts) if shifts else "Смен нет."), reply_markup=back_keyboard())


@router.message(F.text == "Отдать смену")
async def give_shift(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.status == ShiftStatus.SCHEDULED, Shift.date >= datetime.now(timezone.utc)).order_by(Shift.date))
        shifts = result.scalars().all()
    await message.answer("Выбери смену, которую хочешь передать:", reply_markup=shift_buttons("give", shifts) if shifts else back_keyboard())


@router.callback_query(F.data.startswith("give:"))
async def give_callback(callback: CallbackQuery) -> None:
    shift_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, callback.from_user.id)
        shift = await session.get(Shift, shift_id)
        if not employee or not shift:
            await callback.answer("Смена не найдена", show_alert=True)
            return
        try:
            await give_shift_service(session, employee, shift)
        except ValueError:
            await callback.answer("Смену уже нельзя передать", show_alert=True)
            return
        venue = await session.get(Venue, shift.venue_id)
        label = shift_label(shift)
    if not venue:
        await callback.answer("У смены не указана точка", show_alert=True)
        return
    chat_id = chat_id_for_venue(venue.name)
    if not chat_id:
        await callback.answer("Для этой точки ещё не настроена Telegram-беседа", show_alert=True)
        return
    try:
        await send_shift_offer(callback.bot, chat_id, shift.id, venue.name, employee.full_name, label)
    except Exception:
        await callback.answer("Не удалось отправить смену в беседу. Проверьте, что бот добавлен в неё.", show_alert=True)
        return
    await callback.message.edit_text(f"✅ Смена опубликована в беседе «{venue.name}».\n{label}")
    await callback.answer()


@router.message(F.text == "Доступные смены")
async def available_shifts(message: Message) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(Shift).where(Shift.status == ShiftStatus.OFFERED, Shift.date >= datetime.now(timezone.utc)).order_by(Shift.date))
        shifts = result.scalars().all()
    await message.answer("Выбери смену, которую хочешь забрать:", reply_markup=shift_buttons("claim", shifts) if shifts else back_keyboard())


@router.callback_query(F.data.startswith("claim:"))
async def claim_callback(callback: CallbackQuery) -> None:
    shift_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, callback.from_user.id)
        shift = await session.get(Shift, shift_id)
        if not employee or not shift:
            await callback.answer("Смена не найдена", show_alert=True)
            return
        old_employee = await session.get(Employee, shift.employee_id)
        try:
            request = await claim_shift_service(session, employee, shift)
        except ValueError:
            await callback.answer("Смена уже недоступна", show_alert=True)
            return
        label = shift_label(shift)
    await notify(callback.bot, old_employee, f"📨 {employee.full_name} подал заявку забрать твою смену.\n{label}\nОжидается решение менеджера.")
    await notify_managers(callback.bot, f"📨 Новая заявка #{request.id}\n{employee.full_name} хочет забрать смену.\n{label}")
    await callback.message.edit_text(f"📨 Заявка #{request.id} отправлена менеджеру на подтверждение.\n\n{label}")
    await callback.answer("Заявка отправлена")


@router.message(F.text == "Мои заявки")
async def my_requests(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(SubstitutionRequest).where(SubstitutionRequest.new_employee_id == employee.id).order_by(SubstitutionRequest.created_at.desc()).limit(20))
        requests = result.scalars().all()
    await message.answer("Мои заявки:\n\n" + ("\n".join(f"#{r.id} — смена #{r.shift_id} — {r.status.value}" for r in requests) if requests else "Заявок нет."), reply_markup=back_keyboard())


@router.message(F.text == "Заявки менеджера")
async def manager_requests(message: Message) -> None:
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, message.from_user.id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN):
            await message.answer("Доступ только для менеджера.")
            return
        result = await session.execute(select(SubstitutionRequest).where(SubstitutionRequest.status == RequestStatus.PENDING).order_by(SubstitutionRequest.created_at))
        requests = result.scalars().all()
    if not requests:
        await message.answer("Новых заявок нет.", reply_markup=back_keyboard())
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Заявка #{r.id} · смена #{r.shift_id}", callback_data=f"request:{r.id}")] for r in requests] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]])
    await message.answer("Выбери заявку:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("request:"))
async def request_callback(callback: CallbackQuery) -> None:
    request_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, callback.from_user.id)
        request = await session.get(SubstitutionRequest, request_id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN) or not request:
            await callback.answer("Нет доступа", show_alert=True)
            return
        shift = await session.get(Shift, request.shift_id)
        new_employee = await session.get(Employee, request.new_employee_id)
        old_employee = await session.get(Employee, request.old_employee_id)
        if request.status != RequestStatus.PENDING:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        text = f"📋 Заявка #{request.id}\n\nСмена: {shift_label(shift) if shift else '—'}\nОтдаёт: {old_employee.full_name if old_employee else '—'}\nЗабирает: {new_employee.full_name if new_employee else '—'}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"decision:approve:{request_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decision:reject:{request_id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_requests")]])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "manager_requests")
async def manager_requests_callback(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Откройте раздел «Заявки менеджера» в главном меню.")
    await callback.answer()


@router.callback_query(F.data.startswith("decision:"))
async def decision_callback(callback: CallbackQuery) -> None:
    _, decision, request_id_text = callback.data.split(":")
    request_id = int(request_id_text)
    approve = decision == "approve"
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, callback.from_user.id)
        request = await session.get(SubstitutionRequest, request_id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN) or not request:
            await callback.answer("Нет доступа", show_alert=True)
            return
        old_employee = await session.get(Employee, request.old_employee_id)
        new_employee = await session.get(Employee, request.new_employee_id)
        shift = await session.get(Shift, request.shift_id)
        try:
            await decide_request(session, manager, request, approve)
        except ValueError:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        label = shift_label(shift) if shift else f"Смена #{request.shift_id}"
    if approve:
        await notify(callback.bot, new_employee, f"✅ Менеджер одобрил заявку #{request_id}.\nТеперь твоя смена:\n{label}")
        await notify(callback.bot, old_employee, f"✅ Менеджер подтвердил передачу смены #{request.shift_id}.\nНовый сотрудник: {new_employee.full_name if new_employee else '—'}\n{label}")
    else:
        await notify(callback.bot, new_employee, f"❌ Менеджер отклонил заявку #{request_id}.\nСмена снова доступна для получения.\n{label}")
        await notify(callback.bot, old_employee, f"ℹ️ Заявка на получение твоей смены #{request.shift_id} отклонена менеджером.\n{label}")
    result = "одобрена" if approve else "отклонена"
    await callback.message.edit_text(f"Заявка #{request_id} {result}.\n\n{label}")
    await callback.answer()


@router.message(F.text == "Создать смену")
async def create_shift_start(message: Message, state: FSMContext) -> None:
    employee = await get_employee(message)
    if not employee or employee.role not in (Role.MANAGER, Role.ADMIN):
        await message.answer("Доступ только для менеджера.")
        return
    async with SessionLocal() as session:
        result = await session.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name))
        employees = result.scalars().all()
    if not employees:
        await message.answer("Нет активных сотрудников. Сначала добавьте сотрудников.")
        return
    await state.clear()
    await state.set_state(CreateShiftState.employee)
    await message.answer("👤 Выбери сотрудника, для которого создаём смену:", reply_markup=employees_keyboard(employees))


@router.callback_query(CreateShiftState.employee, F.data.startswith("create_employee:"))
async def create_employee_callback(callback: CallbackQuery, state: FSMContext) -> None:
    employee_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, callback.from_user.id)
        employee = await session.get(Employee, employee_id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN) or not employee or not employee.is_active:
            await callback.answer("Сотрудник не найден", show_alert=True)
            return
        if employee.venue_id is None:
            await callback.answer("У сотрудника не указана точка", show_alert=True)
            return
        await state.update_data(employee_id=employee.id, employee_name=employee.full_name, position=employee.position, venue_id=employee.venue_id)
    await state.set_state(CreateShiftState.date)
    await callback.message.edit_text(f"Сотрудник: {employee.full_name}\nДолжность: {employee.position}\n\n📅 Введи дату смены в формате ДД.ММ.ГГГГ")
    await callback.answer()


@router.callback_query(F.data == "create_cancel")
async def create_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    employee = await get_employee(callback.message)
    await callback.message.edit_text("Создание смены отменено.")
    if employee:
        await callback.message.answer("Выбери действие:", reply_markup=main_menu(employee.role))
    await callback.answer()


@router.message(CreateShiftState.date)
async def create_date(message: Message, state: FSMContext) -> None:
    try:
        date_value = datetime.strptime(message.text.strip(), "%d.%m.%Y").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        await message.answer("Неверная дата. Пример: 11.09.2026")
        return
    if date_value.date() < datetime.now(timezone.utc).date():
        await message.answer("Дата уже прошла. Введи сегодняшнюю или будущую дату.")
        return
    await state.update_data(date=date_value.isoformat())
    await state.set_state(CreateShiftState.start)
    await message.answer("🕐 Введи время начала в формате ЧЧ:ММ\nНапример: 11:00")


@router.message(CreateShiftState.start)
async def create_start(message: Message, state: FSMContext) -> None:
    value = message.text.strip() if message.text else ""
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        await message.answer("Неверное время. Пример: 11:00")
        return
    await state.update_data(start_time=value)
    await state.set_state(CreateShiftState.end)
    await message.answer("🕐 Введи время окончания в формате ЧЧ:ММ\nНапример: 23:00")


@router.message(CreateShiftState.end)
async def create_end(message: Message, state: FSMContext) -> None:
    value = message.text.strip() if message.text else ""
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        await message.answer("Неверное время. Пример: 23:00")
        return
    data = await state.get_data()
    await state.update_data(end_time=value)
    await state.set_state(CreateShiftState.confirm)
    await message.answer("Проверь смену:\n\n" + f"👤 {data['employee_name']}\n" + f"💼 {data['position']}\n" + f"📅 {datetime.fromisoformat(data['date']):%d.%m.%Y}\n" + f"🕐 {data['start_time']}–{value}\n\nСоздать эту смену?", reply_markup=confirm_keyboard())


@router.callback_query(CreateShiftState.confirm, F.data == "create_confirm")
async def create_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, callback.from_user.id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN):
            await callback.answer("Нет доступа", show_alert=True)
            return
        employee = await session.get(Employee, int(data["employee_id"]))
        if not employee or not employee.is_active:
            await callback.answer("Сотрудник больше недоступен", show_alert=True)
            await state.clear()
            return
        date_value = datetime.fromisoformat(data["date"])
        shift = await create_shift(session, manager, employee_id=employee.id, venue_id=int(data["venue_id"]), date=date_value, start_time=data["start_time"], end_time=data["end_time"], position=data["position"])
        label = shift_label(shift)
    await state.clear()
    await notify(callback.bot, employee, f"📅 Менеджер создал для тебя смену.\n{label}")
    await callback.message.edit_text(f"✅ Смена #{shift.id} создана.\n\n{label}")
    await callback.message.answer("Выбери действие:", reply_markup=main_menu(manager.role))
    await callback.answer()


@router.message(F.text == "История")
async def history(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(30))
        logs = result.scalars().all()
    await message.answer("Последние действия:\n\n" + ("\n".join(f"{x.created_at:%d.%m %H:%M} — {x.action} #{x.entity_id}" for x in logs) if logs else "История пока пустая."), reply_markup=back_keyboard())


@router.message(F.text == "Уведомления")
async def notifications(message: Message) -> None:
    await message.answer("🔔 Уведомления включены.")


@router.message(F.text == "Профиль")
async def profile(message: Message) -> None:
    employee = await get_employee(message)
    if not employee:
        await message.answer("Ты не зарегистрирован.")
        return
    await message.answer(f"Профиль:\n{employee.full_name}\nДолжность: {employee.position}\nРоль: {employee.role.value}", reply_markup=back_keyboard())
