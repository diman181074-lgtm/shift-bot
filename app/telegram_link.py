from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee


class TelegramLinkMiddleware(BaseMiddleware):
    """Attach Telegram ID to a pre-seeded employee by username on first use."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and user.username:
            username = user.username.lstrip("@")
            async with SessionLocal() as session:
                result = await session.execute(
                    select(Employee).where(
                        Employee.telegram_username == username,
                        Employee.is_active.is_(True),
                    )
                )
                employee = result.scalar_one_or_none()
                if employee and employee.telegram_id != user.id:
                    employee.telegram_id = user.id
                    await session.commit()
        return await handler(event, data)
