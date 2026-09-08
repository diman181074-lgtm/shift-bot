from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Employee, RequestStatus, Shift, ShiftStatus, SubstitutionRequest


async def employee_by_telegram(
    session: AsyncSession, telegram_id: int, username: str | None = None
) -> Employee | None:
    conditions = [Employee.telegram_id == telegram_id]
    if username:
        conditions.append(Employee.telegram_username == username.lstrip("@"))
    result = await session.execute(select(Employee).where(or_(*conditions), Employee.is_active.is_(True)))
    employee = result.scalar_one_or_none()
    if employee and employee.telegram_id is None:
        employee.telegram_id = telegram_id
        await session.commit()
    return employee


async def audit(session: AsyncSession, actor: Employee | None, action: str, entity_type: str, entity_id: int, details: str = "") -> None:
    session.add(AuditLog(actor_employee_id=actor.id if actor else None, action=action, entity_type=entity_type, entity_id=entity_id, details=details))


async def give_shift(session: AsyncSession, employee: Employee, shift: Shift) -> None:
    if shift.employee_id != employee.id or shift.status != ShiftStatus.SCHEDULED:
        raise ValueError("shift_unavailable")
    shift.status = ShiftStatus.OFFERED
    await audit(session, employee, "SHIFT_OFFERED", "shift", shift.id)
    await session.commit()


async def claim_shift(session: AsyncSession, employee: Employee, shift: Shift) -> SubstitutionRequest:
    result = await session.execute(select(Shift).where(Shift.id == shift.id).with_for_update())
    locked_shift = result.scalar_one_or_none()
    if locked_shift is None or locked_shift.status != ShiftStatus.OFFERED:
        raise ValueError("shift_unavailable")
    if locked_shift.employee_id == employee.id:
        raise ValueError("self_claim")
    request = SubstitutionRequest(
        shift_id=locked_shift.id,
        old_employee_id=locked_shift.employee_id,
        new_employee_id=employee.id,
        status=RequestStatus.PENDING,
    )
    locked_shift.status = ShiftStatus.CLAIMED
    session.add(request)
    await audit(session, employee, "SHIFT_CLAIMED", "shift", locked_shift.id)
    await session.commit()
    await session.refresh(request)
    return request


async def decide_request(session: AsyncSession, manager: Employee, request: SubstitutionRequest, approve: bool, comment: str | None = None) -> None:
    if request.status != RequestStatus.PENDING:
        raise ValueError("request_processed")
    shift = await session.get(Shift, request.shift_id)
    if shift is None:
        raise ValueError("shift_missing")
    request.manager_comment = comment
    if approve:
        request.status = RequestStatus.APPROVED
        shift.employee_id = request.new_employee_id
        shift.status = ShiftStatus.APPROVED
        await audit(session, manager, "SUBSTITUTION_APPROVED", "request", request.id)
    else:
        request.status = RequestStatus.REJECTED
        shift.status = ShiftStatus.OFFERED
        await audit(session, manager, "SUBSTITUTION_REJECTED", "request", request.id, comment or "")
    await session.commit()


async def create_shift(session: AsyncSession, manager: Employee, employee_id: int, venue_id: int, date: datetime, start_time: str, end_time: str, position: str, comment: str | None = None) -> Shift:
    shift = Shift(venue_id=venue_id, employee_id=employee_id, date=date, start_time=start_time, end_time=end_time, position=position, status=ShiftStatus.SCHEDULED, comment=comment)
    session.add(shift)
    await session.flush()
    await audit(session, manager, "SHIFT_CREATED", "shift", shift.id)
    await session.commit()
    await session.refresh(shift)
    return shift


def shift_label(shift: Shift) -> str:
    date = shift.date.astimezone(timezone.utc).strftime("%d.%m.%Y") if shift.date.tzinfo else shift.date.strftime("%d.%m.%Y")
    return f"{date} · {shift.start_time}–{shift.end_time} · {shift.position}"
