"""관리자 API: config, 예약 현황, 통계, user 역할."""
from datetime import datetime, date, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_admin, get_current_super_admin
from app.models import Reservation, ReservationStatus, Room, SystemConfig, User, UserRole

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Schemas ---
class ConfigItem(BaseModel):
    key: str
    value: str


class ConfigUpdate(BaseModel):
    config: dict[str, str]


class ReservationAdminOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_email: str
    room_id: int
    room_name: str
    start_time: str
    end_time: str
    status: str


class UserAdminOut(BaseModel):
    id: int
    email: str
    name: str
    dept: str
    role: str
    is_graduate: bool
    created_at: str


class UserRoleUpdate(BaseModel):
    role: str


class GraduateUpdate(BaseModel):
    is_graduate: bool


# --- Routes ---
@router.get("/config", response_model=list[ConfigItem])
async def get_config(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    return [ConfigItem(key=c.key, value=c.value) for c in result.scalars().all()]


@router.put("/config")
async def update_config(
    body: ConfigUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    for key, value in body.config.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(SystemConfig(key=key, value=str(value)))
    await db.commit()
    return {"ok": True}


@router.get("/reservations", response_model=list[ReservationAdminOut])
async def list_reservations(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="date"),
    room_id: int | None = None,
):
    q = (
        select(Reservation, User, Room)
        .join(User, Reservation.user_id == User.id)
        .join(Room, Reservation.room_id == Room.id)
        .where(Reservation.status == ReservationStatus.confirmed)
    )
    if date_from:
        try:
            d = datetime.strptime(date_from, "%Y-%m-%d").date()
            day_start = datetime.combine(d, time(0, 0, 0))
            day_end = datetime.combine(d, time(23, 59, 59))
            q = q.where(
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end,
            )
        except ValueError:
            pass
    if room_id is not None:
        q = q.where(Reservation.room_id == room_id)
    q = q.order_by(Reservation.start_time.desc())
    result = await db.execute(q)
    rows = result.all()
    return [
        ReservationAdminOut(
            id=r.id,
            user_id=r.user_id,
            user_name=u.name,
            user_email=u.email,
            room_id=r.room_id,
            room_name=room.name,
            start_time=r.start_time.isoformat(),
            end_time=r.end_time.isoformat(),
            status=r.status.value,
        )
        for r, u, room in rows
    ]


@router.delete("/reservations/{reservation_id}", status_code=204)
async def admin_cancel_reservation(
    reservation_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    r.status = ReservationStatus.cancelled
    await db.commit()


@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # 오늘 예약 수
    today = date.today()
    day_start = datetime.combine(today, time(0, 0, 0))
    day_end = datetime.combine(today, time(23, 59, 59)) + timedelta(seconds=1)
    today_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.status == ReservationStatus.confirmed,
            Reservation.start_time >= day_start,
            Reservation.end_time <= day_end,
        )
    )
    today_count = today_result.scalar() or 0

    # 방별 예약 횟수
    room_result = await db.execute(select(Room))
    rooms = room_result.scalars().all()
    by_room = []
    for room in rooms:
        cnt_result = await db.execute(
            select(func.count(Reservation.id)).where(
                Reservation.room_id == room.id,
                Reservation.status == ReservationStatus.confirmed,
            )
        )
        by_room.append({"room": room.name, "count": cnt_result.scalar() or 0})

    # 전체 예약 수
    total_result = await db.execute(
        select(func.count(Reservation.id)).where(Reservation.status == ReservationStatus.confirmed)
    )
    total_count = total_result.scalar() or 0

    return {
        "today_count": today_count,
        "total_count": total_count,
        "by_room": by_room,
    }


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            name=u.name,
            dept=u.dept,
            role=u.role.value,
            is_graduate=bool(u.is_graduate),
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]


@router.patch("/users/{user_id}/graduate")
async def update_user_graduate(
    user_id: int,
    body: GraduateUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_graduate = body.is_graduate
    await db.commit()
    return {"ok": True, "is_graduate": body.is_graduate}


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: UserRoleUpdate,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    await db.commit()
    return {"ok": True, "role": role.value}
