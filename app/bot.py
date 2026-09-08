from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
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


@router.message(F.text == "Мои смены")
async def my_shifts(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        now = datetime.now(timezone.utc)
        result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.date >= now).order_by(Shift.date))
        shifts = result.scalars().all()
    if not shifts:
        await message.answer("На ближайшее время смен нет.")
        return
    await message.answer("Твои смены:\n\n" + "\n".join(f"#{s.id} — {shift_label(s)} [{s.status.value}]" for s in shifts))


@router.message(F.text == "Отдать смену")
async def give_shift(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(Shift).where(Shift.employee_id == employee.id, Shift.status == ShiftStatus.SCHEDULED, Shift.date >= datetime.now(timezone.utc)).order_by(Shift.date))
        shifts = result.scalars().all()
    if not shifts:
        await message.answer("Нет смен, которые можно передать.")
        return
    await message.answer("Чтобы передать смену, напиши: /give ID\n\n" + "\n".join(f"#{s.id} — {shift_label(s)}" for s in shifts))


@router.message(F.text.startswith("/give "))
async def give_command(message: Message) -> None:
    try:
        shift_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /give ID")
        return
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        shift = await session.get(Shift, shift_id)
        if not employee or not shift:
            await message.answer("Смена не найдена.")
            return
        try:
            await give_shift_service(session, employee, shift)
        except ValueError:
            await message.answer("Эту смену сейчас нельзя передать.")
            return
        label = shift_label(shift)
    await message.answer(f"Смена опубликована: {label}\nДругой сотрудник может подать заявку на получение.")


@router.message(F.text == "Доступные смены")
async def available_shifts(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(Shift).where(Shift.status == ShiftStatus.OFFERED, Shift.date >= datetime.now(timezone.utc)).order_by(Shift.date))
        shifts = result.scalars().all()
    if not shifts:
        await message.answer("Сейчас доступных смен нет.")
        return
    await message.answer("Доступные смены:\n\n" + "\n".join(f"#{s.id} — {shift_label(s)}\nЧтобы забрать: /claim {s.id}" for s in shifts))


@router.message(F.text.startswith("/claim "))
async def claim_command(message: Message) -> None:
    try:
        shift_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /claim ID")
        return
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        shift = await session.get(Shift, shift_id)
        if not employee or not shift:
            await message.answer("Смена не найдена.")
            return
        try:
            request = await claim_shift_service(session, employee, shift)
        except ValueError:
            await message.answer("Эта смена уже недоступна.")
            return
    await message.answer(f"Заявка #{request.id} отправлена менеджеру на подтверждение.")


@router.message(F.text == "Мои заявки")
async def my_requests(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(SubstitutionRequest).where(SubstitutionRequest.new_employee_id == employee.id).order_by(SubstitutionRequest.created_at.desc()).limit(20))
        requests = result.scalars().all()
    if not requests:
        await message.answer("Заявок нет.")
        return
    await message.answer("Мои заявки:\n\n" + "\n".join(f"#{r.id} — смена #{r.shift_id} — {r.status.value}" for r in requests))


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
        await message.answer("Новых заявок нет.")
        return
    await message.answer("Заявки:\n\n" + "\n".join(f"#{r.id} — смена #{r.shift_id}\n/approve {r.id} — одобрить\n/reject {r.id} — отклонить" for r in requests))


async def manager_decision(message: Message, approve: bool) -> None:
    try:
        request_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Укажи ID заявки.")
        return
    async with SessionLocal() as session:
        manager = await employee_by_telegram(session, message.from_user.id)
        request = await session.get(SubstitutionRequest, request_id)
        if not manager or manager.role not in (Role.MANAGER, Role.ADMIN) or not request:
            await message.answer("Заявка не найдена или нет доступа.")
            return
        try:
            await decide_request(session, manager, request, approve)
        except ValueError:
            await message.answer("Заявку уже обработали или смена недоступна.")
            return
    await message.answer("Заявка одобрена." if approve else "Заявка отклонена.")


@router.message(F.text.startswith("/approve "))
async def approve(message: Message) -> None:
    await manager_decision(message, True)


@router.message(F.text.startswith("/reject "))
async def reject(message: Message) -> None:
    await manager_decision(message, False)


@router.message(F.text == "История")
async def history(message: Message) -> None:
    from app.models import AuditLog
    async with SessionLocal() as session:
        employee = await employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer("Ты не зарегистрирован.")
            return
        result = await session.execute(select(AuditLog).where((AuditLog.actor_employee_id == employee.id) | (AuditLog.actor_employee_id.is_(None))).order_by(AuditLog.created_at.desc()).limit(20))
        logs = result.scalars().all()
    if not logs:
        await message.answer("История пока пустая.")
        return
    await message.answer("Последние действия:\n\n" + "\n".join(f"{x.created_at:%d.%m %H:%M} — {x.action} #{x.entity_id}" for x in logs))


@router.message(F.text == "Уведомления")
async def notifications(message: Message) -> None:
    await message.answer("Уведомления включены. Системные уведомления будут приходить сюда.")


@router.message(F.text == "Профиль")
async def profile(message: Message) -> None:
    employee = await get_employee(message)
    if not employee:
        await message.answer("Ты не зарегистрирован.")
        return
    await message.answer(f"Профиль:\n{employee.full_name}\nДолжность: {employee.position}\nРоль: {employee.role.value}")
