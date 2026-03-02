from sqlalchemy import String, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"
    super_admin = "super_admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    dept: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.user
    )
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    reservations: Mapped[list["Reservation"]] = relationship("Reservation", back_populates="user")


def parse_google_name(raw_name: str) -> tuple[str, str]:
    """Google name '한인규 | 교육공학과 | 한양대(서울)' → (name, dept)"""
    parts = [p.strip() for p in raw_name.split("|")]
    name = parts[0] if len(parts) > 0 else ""
    dept = parts[1] if len(parts) > 1 else ""
    return name, dept
