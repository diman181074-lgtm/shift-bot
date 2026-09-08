from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(str, Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"


class ShiftStatus(str, Enum):
    SCHEDULED = "scheduled"
    OFFERED = "offered"
    CLAIMED = "claimed"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    employees: Mapped[list["Employee"]] = relationship(back_populates="venue")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="venue")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(160))
    position: Mapped[str] = mapped_column(String(80), default="официант")
    role: Mapped[Role] = mapped_column(default=Role.EMPLOYEE)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    notifications_enabled: Mapped[bool] = mapped_column(default=True)

    venue: Mapped[Venue | None] = relationship(back_populates="employees")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="employee", foreign_keys="Shift.employee_id")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    position: Mapped[str] = mapped_column(String(80))
    status: Mapped[ShiftStatus] = mapped_column(default=ShiftStatus.SCHEDULED)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    venue: Mapped[Venue] = relationship(back_populates="shifts")
    employee: Mapped[Employee] = relationship(back_populates="shifts", foreign_keys=[employee_id])


class SubstitutionRequest(Base):
    __tablename__ = "substitution_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"))
    old_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    new_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[RequestStatus] = mapped_column(default=RequestStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column()
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
