from sqlalchemy import ForeignKey, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import enum

from app.database import Base


class ReservationStatus(str, enum.Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # 중도 퇴실 시 room 공실은 end_time(실제 퇴실 시각), 한도 차감은 billed_end_time(올림) 사용
    billed_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus), nullable=False, default=ReservationStatus.confirmed
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="reservations")
    room: Mapped["Room"] = relationship("Room", back_populates="reservations")
