from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee, RequestStatus, Role, Shift, ShiftStatus, SubstitutionRequest
from app.services import claim_shift as claim_shift_service
from app.services import decide_request, employee_by_telegram, give_shift as give_shift_service, shift_label

router = Router()


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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{s.id} · {s.date:%d.%m} {s.start_time}–{s.end_time}", callback_data=f"{prefix}:{s.id}")]
        for s in shifts
    ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]])


async def get_employee(message: Message) -> Employee | None:
    async with SessionLocal() as session:
        return await employee_by_telegram(session, message.from_user.id)


@router.message(CommandStart())
async def start(message: Message) -> None:
    employee = await get_employee(message)
    if employee is None:
        await message.answer("Ты ещё не зарегистрирован в системе. Обратись к менеджеру.")
        return
    await message.answer(f"Привет, {employee.full_name}!\nВыбери действие:", reply_markup=main_menu(employee.role))


@router.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery) -> None:
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
            await callback.answer("Смена не найдена", show_alert=True); return
        try:
            await give_shift_service(session, employee, shift)
        except ValueError:
            await callback.answer("Смену уже нельзя передать", show_alert=True); return
        label = shift_label(shift)
    await callback.message.edit_text(f"✅ Смена опубликована\n{label}")
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
            await callback.answer("Смена не найдена", show_alert=True); return
        try:
            request = await claim_shift_service(session, employee, shift)
        except ValueError:
            await callback.answer("Смена уже недоступна", show_alert=True); return
    await callback.message.edit_text(f"📨 Заявка #{request.id} отправлена менеджеру на подтверждение.")
    await callback.answer("Заявка отправлена")


@router.message(F.text == "Мои заявки")
async def my_requests(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован."); return
        result = await session.execute(select(SubstitutionRequest).where(SubstitutionRequest.new_employee_id == employee.id).order_by(SubstitutionRequest.created_at.desc()).limit(20))
        requests = result.scalars().all()
    await message.answer("Мои заявки:\n\n" + ("\n".join(f"#{r.id} — смена #{r.shift_id} — {r.status.value}" for r in requests) if requests else "Заявок нет."), reply_markup=back_keyboard())


@router.message(F.text == "Заявки менеджера")
async def manager_requests(message: Message) -> None:
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, message.from_user.id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN):
            await message.answer("Доступ только для менеджера."); return
        result = await session.execute(select(SubstitutionRequest).where(SubstitutionRequest.status == RequestStatus.PENDING).order_by(SubstitutionRequest.created_at))
        requests = result.scalars().all()
    if not requests:
        await message.answer("Новых заявок нет.", reply_markup=back_keyboard()); return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Заявка #{r.id} · смена #{r.shift_id}", callback_data=f"request:{r.id}")] for r in requests
    ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]])
    await message.answer("Выбери заявку:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("request:"))
async def request_callback(callback: CallbackQuery) -> None:
    request_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, callback.from_user.id)
        request = await session.get(SubstitutionRequest, request_id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN) or not request:
            await callback.answer("Нет доступа", show_alert=True); return
        shift = await session.get(Shift, request.shift_id)
        new_employee = await session.get(Employee, request.new_employee_id)
        old_employee = await session.get(Employee, request.old_employee_id)
        if request.status != RequestStatus.PENDING:
            await callback.answer("Заявка уже обработана", show_alert=True); return
        text = (f"📋 Заявка #{request.id}\n\nСмена: {shift_label(shift) if shift else '—'}\n"
                f"Отдаёт: {old_employee.full_name if old_employee else '—'}\n"
                f"Забирает: {new_employee.full_name if new_employee else '—'}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"decision:approve:{request_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decision:reject:{request_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_requests")],
    ])
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
            await callback.answer("Нет доступа", show_alert=True); return
        try:
            await decide_request(session, manager, request, approve)
        except ValueError:
            await callback.answer("Заявка уже обработана", show_alert=True); return
        new_employee = await session.get(Employee, request.new_employee_id)
        old_employee = await session.get(Employee, request.old_employee_id)
    result = "одобрена" if approve else "отклонена"
    await callback.message.edit_text(f"Заявка #{request_id} {result}.")
    # The notification helper is wired separately once the bot instance is injected into handlers.
    await callback.answer()


@router.message(F.text == "Создать смену")
async def create_shift_start(message: Message) -> None:
    employee = await get_employee(message)
    if not employee or employee.role not in (Role.MANAGER, Role.ADMIN):
        await message.answer("Доступ только для менеджера."); return
    await message.answer("Создание смены подключим через пошаговую форму: сотрудник → дата → время → должность.")


@router.message(F.text == "История")
async def history(message: Message) -> None:
    from app.models import AuditLog
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован."); return
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
        await message.answer("Ты не зарегистрирован."); return
    await message.answer(f"Профиль:\n{employee.full_name}\nДолжность: {employee.position}\nРоль: {employee.role.value}", reply_markup=back_keyboard())
