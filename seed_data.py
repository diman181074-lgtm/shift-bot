"""Initial roster for the shift handover bot.

All listed employees are waiters for now. Telegram IDs are filled automatically
when a person starts the bot if their Telegram username is listed below.
"""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee, Role, Venue

VENUES = ["Петроградская", "Маяковская"]

EMPLOYEES = [
    {"full_name": "Рома Три полоски", "venue": 0}, {"full_name": "Жанна", "venue": 0},
    {"full_name": "Соня", "venue": 0}, {"full_name": "Милана", "venue": 0},
    {"full_name": "Димаус", "venue": 0}, {"full_name": "Артур КБ", "venue": 0},
    {"full_name": "Катя высокая", "venue": 0}, {"full_name": "Жэка", "venue": 0},
    {"full_name": "Полина", "venue": 1}, {"full_name": "Олеся", "venue": 1},
    {"full_name": "Максим слей", "venue": 1}, {"full_name": "Аня", "venue": 1},
    {"full_name": "Инна", "venue": 1}, {"full_name": "Марк", "venue": 1},
    {"full_name": "Софа", "venue": 1}, {"full_name": "Крис", "venue": 1},
    {"full_name": "Динара", "venue": 1}, {"full_name": "Кама", "venue": 1},
    {"full_name": "Шая", "venue": 1}, {"full_name": "Глеб", "venue": 1},
    {"full_name": "Игнат", "venue": 1}, {"full_name": "Рома", "venue": 1},
    {"full_name": "Панайот", "venue": 1}, {"full_name": "Саша", "venue": 1},
    {"full_name": "Маша", "venue": 1},
    {"full_name": "Маша", "venue": 0, "telegram_username": "marichelou", "role": Role.MANAGER},
    {"full_name": "Соня", "venue": 0, "telegram_username": "yourrddrug", "role": Role.MANAGER},
    {"full_name": "Анжелика", "venue": 0, "telegram_username": "angel_K_S7", "role": Role.MANAGER},
    {"full_name": "Юля мацала", "venue": 1, "telegram_username": "Yuliamatsola", "role": Role.MANAGER},
    {"full_name": "Лиза Минта", "venue": 1, "telegram_username": "shavkan", "role": Role.MANAGER},
    {"full_name": "Леха колядки", "venue": 1, "telegram_username": "L4ckey", "role": Role.MANAGER},
    {"full_name": "Кристина отдых", "venue": 1, "telegram_username": "kriskis_mk", "role": Role.MANAGER},
    {"full_name": "Дмитрий", "venue": 0, "telegram_username": "Guffons", "role": Role.ADMIN},
]


async def seed() -> None:
    async with SessionLocal() as session:
        venues: list[Venue] = []
        for name in VENUES:
            result = await session.execute(select(Venue).where(Venue.name == name))
            venue = result.scalar_one_or_none()
            if venue is None:
                venue = Venue(name=name, is_active=True)
                session.add(venue)
                await session.flush()
            venues.append(venue)

        for data in EMPLOYEES:
            username = data.get("telegram_username")
            employee = None
            if username:
                result = await session.execute(select(Employee).where(Employee.telegram_username == username))
                employee = result.scalar_one_or_none()
            else:
                result = await session.execute(
                    select(Employee).where(Employee.full_name == data["full_name"], Employee.venue_id == venues[data["venue"]].id, Employee.telegram_username.is_(None))
                )
                employee = result.scalar_one_or_none()

            if employee is None:
                employee = Employee(
                    telegram_id=None,
                    telegram_username=username,
                    full_name=data["full_name"],
                    position="официант",
                    role=data.get("role", Role.EMPLOYEE),
                    venue_id=venues[data["venue"]].id,
                    is_active=True,
                    notifications_enabled=True,
                )
                session.add(employee)
            else:
                employee.full_name = data["full_name"]
                employee.position = "официант"
                employee.role = data.get("role", employee.role)
                employee.venue_id = venues[data["venue"]].id
                employee.is_active = True

        await session.commit()
        print("База первоначально настроена.")
        print("Точки:", ", ".join(VENUES))
        print("Записей в первоначальном составе:", len(EMPLOYEES))
        print("Все должности: официант")


if __name__ == "__main__":
    asyncio.run(seed())
