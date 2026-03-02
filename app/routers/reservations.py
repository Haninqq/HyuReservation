"""예약 API."""
from datetime import datetime, timedelta
import math
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_api
from app.models import Reservation, ReservationStatus, Room, User
from app.services.config_service import (
    get_max_advance_days,
    get_max_hours_per_day,
    get_operating_hours,
    get_exclude_weekends,
    get_exclude_holidays,
    get_holidays,
    get_slot_duration,
)
from app.services.slot_service import get_available_slots, get_user_remaining_hours

router = APIRouter(prefix="/api", tags=["reservations"])


# --- Schemas ---
class RoomOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class SlotOut(BaseModel):
    start: str
    end: str
    available: bool
    occupied: bool = False
    mine: bool = False
    occupied_by_others: bool = False


class ReservationCreate(BaseModel):
    room_id: int
    start_time: str  # ISO format
    end_time: str


class ReservationOut(BaseModel):
    id: int
    room_id: int
    room_name: str
    start_time: str
    end_time: str
    status: str
    cancelable: bool = True
    can_early_checkout: bool = False

    class Config:
        from_attributes = True


# --- Routes ---
@router.get("/config")
async def get_public_config(db: AsyncSession = Depends(get_db)):
    """main 페이지용 설정 (인증 불필요)."""
    max_adv = await get_max_advance_days(db)
    exclude_wknd = await get_exclude_weekends(db)
    exclude_hol = await get_exclude_holidays(db)
    holidays = await get_holidays(db)
    max_hours = await get_max_hours_per_day(db)
    slot_duration = await get_slot_duration(db)
    open_t, close_t = await get_operating_hours(db)
    return {
        "max_advance_days": max_adv,
        "exclude_weekends": exclude_wknd,
        "exclude_holidays": exclude_hol,
        "holidays": list(holidays),
        "max_hours_per_day": max_hours,
        "slot_duration": slot_duration,
        "operating_hours": {"open": open_t, "close": close_t},
    }


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Room).where(Room.is_active == True).order_by(Room.id))
    return [RoomOut(id=r.id, name=r.name) for r in result.scalars().all()]


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(
    date: str,
    room_id: int,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")

    return await get_available_slots(db, target_date, room_id, user.id)


@router.get("/slots/remaining")
async def get_remaining_hours(
    date: str,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")
    remaining = await get_user_remaining_hours(db, user.id, target_date)
    return {"remaining_hours": round(remaining, 2)}


@router.post("/reservations", response_model=ReservationOut, status_code=201)
async def create_reservation(
    body: ReservationCreate,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    try:
        start_dt = datetime.fromisoformat(body.start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(body.end_time.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    # timezone-naive 로 저장 (로컬 기준)
    if start_dt.tzinfo:
        start_dt = start_dt.replace(tzinfo=None)
    if end_dt.tzinfo:
        end_dt = end_dt.replace(tzinfo=None)

    # room 존재 확인
    room_result = await db.execute(select(Room).where(Room.id == body.room_id, Room.is_active == True))
    room = room_result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # max_advance_days 확인
    max_adv = await get_max_advance_days(db)
    from datetime import date, timedelta
    today = date.today()
    if start_dt.date() > today + timedelta(days=max_adv):
        raise HTTPException(status_code=400, detail=f"예약은 {max_adv}일 이내만 가능합니다.")

    # 인당 일일 제한
    remaining = await get_user_remaining_hours(db, user.id, start_dt.date())
    slot_hours = (end_dt - start_dt).total_seconds() / 3600
    if slot_hours > remaining:
        raise HTTPException(status_code=400, detail="일일 예약 가능 시간을 초과했습니다.")

    # 슬롯이 예약 가능한지 확인 (범위 전체가 available이어야 함)
    slots = await get_available_slots(db, start_dt.date(), body.room_id, user.id)
    overlapping = [
        s for s in slots
        if datetime.fromisoformat(s["start"]) < end_dt and datetime.fromisoformat(s["end"]) > start_dt
    ]
    slot_available = overlapping and all(s["available"] for s in overlapping)
    if not slot_available:
        raise HTTPException(status_code=400, detail="해당 시간은 예약할 수 없습니다.")

    # 중복 예약 체크 (같은 user, 같은 시간대)
    from sqlalchemy import and_
    overlap = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.user_id == user.id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time < end_dt,
                Reservation.end_time > start_dt,
            )
        )
    )
    if overlap.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="해당 시간에 이미 예약이 있습니다.")

    r = Reservation(
        user_id=user.id,
        room_id=body.room_id,
        start_time=start_dt,
        end_time=end_dt,
        status=ReservationStatus.confirmed,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return ReservationOut(
        id=r.id,
        room_id=r.room_id,
        room_name=room.name,
        start_time=r.start_time.isoformat(),
        end_time=r.end_time.isoformat(),
        status=r.status.value,
    )


def _compute_cancel_flags(r: Reservation, now: datetime, slot_mins: int) -> tuple[bool, bool]:
    """첫 슬롯 end 기준: 취소 가능 여부, 중도 퇴실 가능 여부."""
    first_slot_end = r.start_time + timedelta(minutes=slot_mins)
    cancelable = now < first_slot_end
    # 중도 퇴실: 첫 슬롯 지났고, 예약 종료 전인 진행 중 예약
    can_early_checkout = (now >= first_slot_end) and (r.start_time <= now < r.end_time)
    return cancelable, can_early_checkout


@router.get("/reservations/mine", response_model=list[ReservationOut])
async def list_my_reservations(
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now()
    slot_mins = await get_slot_duration(db)
    # end_time > now: 진행 중·예정 예약만 (시작했어도 아직 끝나지 않았으면 표시)
    result = await db.execute(
        select(Reservation, Room)
        .join(Room, Reservation.room_id == Room.id)
        .where(
            Reservation.user_id == user.id,
            Reservation.status == ReservationStatus.confirmed,
            Reservation.end_time > now,
        )
        .order_by(Reservation.start_time)
    )
    rows = result.all()
    return [
        ReservationOut(
            id=r.id,
            room_id=r.room_id,
            room_name=room.name,
            start_time=r.start_time.isoformat(),
            end_time=r.end_time.isoformat(),
            status=r.status.value,
            cancelable=cancelable,
            can_early_checkout=can_early_checkout,
        )
        for r, room in rows
        for cancelable, can_early_checkout in [_compute_cancel_flags(r, now, slot_mins)]
    ]


@router.delete("/reservations/{reservation_id}", status_code=204)
async def cancel_reservation(
    reservation_id: int,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now()
    slot_mins = await get_slot_duration(db)
    result = await db.execute(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.user_id == user.id,
        )
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    if r.status != ReservationStatus.confirmed:
        raise HTTPException(status_code=400, detail="이미 처리된 예약입니다.")
    first_slot_end = r.start_time + timedelta(minutes=slot_mins)
    if now >= first_slot_end:
        raise HTTPException(status_code=400, detail="취소할 수 없습니다.")
    r.status = ReservationStatus.cancelled
    await db.commit()


@router.post("/reservations/{reservation_id}/early-checkout", response_model=ReservationOut)
async def early_checkout(
    reservation_id: int,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    """중도 퇴실: 사용 중인 슬롯을 올림 처리해 end_time을 단축하고 잔여 슬롯을 공실 처리."""
    now = datetime.now()
    slot_mins = await get_slot_duration(db)
    result = await db.execute(
        select(Reservation, Room)
        .join(Room, Reservation.room_id == Room.id)
        .where(
            Reservation.id == reservation_id,
            Reservation.user_id == user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    r, room = row
    if r.status != ReservationStatus.confirmed:
        raise HTTPException(status_code=400, detail="이미 처리된 예약입니다.")
    first_slot_end = r.start_time + timedelta(minutes=slot_mins)
    if now < first_slot_end:
        raise HTTPException(
            status_code=400,
            detail="첫 번째 슬롯이 지나야 중도 퇴실할 수 있습니다.",
        )
    if now >= r.end_time:
        raise HTTPException(status_code=400, detail="이미 종료된 예약입니다.")
    # 사용 시간(한도): 올림 처리. 공실(room): 실제 퇴실 시각으로 즉시 해제
    diff_seconds = (now - r.start_time).total_seconds()
    slot_seconds = slot_mins * 60
    num_slots_used = math.ceil(diff_seconds / slot_seconds)
    billed_end = r.start_time + timedelta(minutes=slot_mins * num_slots_used)
    r.end_time = now  # 20:05 퇴실이면 20:05~ 공실
    r.billed_end_time = billed_end  # 한도는 20:30까지로 차감
    await db.commit()
    await db.refresh(r)
    cancelable, can_early_checkout = _compute_cancel_flags(r, datetime.now(), slot_mins)
    return ReservationOut(
        id=r.id,
        room_id=r.room_id,
        room_name=room.name,
        start_time=r.start_time.isoformat(),
        end_time=r.end_time.isoformat(),
        status=r.status.value,
        cancelable=cancelable,
        can_early_checkout=can_early_checkout,
    )
