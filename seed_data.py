"""Initial database setup for the two restaurant venues.

Run inside the bot environment after the database is available.
Edit the DATA section before the first run. Telegram IDs are intentionally
not hard-coded here; they are entered through environment variables or the
admin setup flow later.
"""

import asyncio
import os

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Employee, Role, Venue

# Replace these names with the exact names of the two venues.
VENUES = [
    "Точка 1",
    "Точка 2",
]

# Initial employees. Keep telegram_id empty until real Telegram IDs are known.
# Format: full_name, position, venue_index, role, telegram_id
EMPLOYEES = [
    # {"full_name": "Иван Иванов", "position": "бармен", "venue": 0, "role": Role.EMPLOYEE, "telegram_id": 123456789},
]

# Manager Telegram IDs can also be supplied without putting them in Git:
# MANAGER_TELEGRAM_IDS="123456789,987654321"
MANAGER_TELEGRAM_IDS = {
    int(value.strip())
    for value in os.getenv("MANAGER_TELEGRAM_IDS", "").split(",")
    if value.strip().isdigit()
}


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
            result = await session.execute(
                select(Employee).where(Employee.telegram_id == data["telegram_id"])
            )
            employee = result.scalar_one_or_none()
            if employee is None:
                employee = Employee(
                    telegram_id=data["telegram_id"],
                    full_name=data["full_name"],
                    position=data["position"],
                    role=data.get("role", Role.EMPLOYEE),
                    venue_id=venues[data["venue"]].id,
                    is_active=True,
                    notifications_enabled=True,
                )
                session.add(employee)
            else:
                employee.full_name = data["full_name"]
                employee.position = data["position"]
                employee.venue_id = venues[data["venue"]].id
                employee.role = data.get("role", employee.role)
                employee.is_active = True

        if MANAGER_TELEGRAM_IDS:
            result = await session.execute(
                select(Employee).where(Employee.telegram_id.in_(MANAGER_TELEGRAM_IDS))
            )
            for employee in result.scalars():
                employee.role = Role.MANAGER
                employee.is_active = True

        await session.commit()

        print("База первоначально настроена.")
        print("Точки:", ", ".join(VENUES))
        print("Сотрудников в seed-файле:", len(EMPLOYEES))
        print("Менеджеров из MANAGER_TELEGRAM_IDS:", len(MANAGER_TELEGRAM_IDS))


if __name__ == "__main__":
    asyncio.run(seed())
