from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


VENUE_CHAT_IDS = {
    "Петроградская": settings.petrogradskaya_chat_id,
    "Маяковская": settings.mayakovskaya_chat_id,
}


def chat_id_for_venue(venue_name: str) -> int | None:
    return VENUE_CHAT_IDS.get(venue_name)


async def send_shift_offer(
    bot: Bot,
    chat_id: int,
    shift_id: int,
    venue_name: str,
    employee_name: str,
    label: str,
) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Забрать смену", callback_data=f"claim:{shift_id}")]
        ]
    )
    text = (
        "🔄 <b>Смена доступна</b>\n\n"
        f"📍 {venue_name}\n"
        f"👤 {employee_name}\n"
        f"🕐 {label.split(' · ', 1)[1] if ' · ' in label else label}\n\n"
        "Кто готов забрать смену — нажмите кнопку ниже."
    )
    await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
