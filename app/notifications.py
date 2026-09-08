from aiogram import Bot

from app.models import Employee


async def notify(bot: Bot, employee: Employee | None, text: str) -> None:
    if employee and employee.telegram_id and employee.notifications_enabled:
        try:
            await bot.send_message(employee.telegram_id, text)
        except Exception:
            # A blocked/deleted Telegram chat must not break the workflow.
            pass
