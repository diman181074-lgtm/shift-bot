from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee

router = Router()


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мои смены"), KeyboardButton(text="Отдать смену")],
            [KeyboardButton(text="Доступные смены"), KeyboardButton(text="Найти подмену")],
            [KeyboardButton(text="Обмен сменами"), KeyboardButton(text="Уведомления")],
            [KeyboardButton(text="Профиль")],
        ],
        resize_keyboard=True,
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == message.from_user.id)
        )
        employee = result.scalar_one_or_none()

    if employee is None:
        await message.answer(
            "Ты ещё не зарегистрирован в системе. Обратись к менеджеру, чтобы тебя добавили."
        )
        return

    await message.answer(
        f"Привет, {employee.full_name}!\nВыбери нужное действие:",
        reply_markup=main_menu(),
    )


@router.message(F.text == "Мои смены")
async def my_shifts(message: Message) -> None:
    await message.answer("Раздел «Мои смены» подключим следующим этапом.")


@router.message(F.text == "Отдать смену")
async def give_shift(message: Message) -> None:
    await message.answer("Здесь появится список твоих смен для передачи.")


@router.message(F.text == "Доступные смены")
async def available_shifts(message: Message) -> None:
    await message.answer("Здесь будут опубликованные смены, которые можно забрать.")


@router.message(F.text == "Найти подмену")
async def find_substitute(message: Message) -> None:
    await message.answer("Раздел поиска подмены подключим после основного сценария передачи.")
