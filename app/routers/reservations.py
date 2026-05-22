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
    get_is_exam_period,
)
from app.services.slot_service import (
    get_available_slots,
    get_user_remaining_hours,
    get_user_remaining_hours_split,
    split_reservation_hours,
)

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
async def list_rooms(
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    q = select(Room).where(Room.is_active == True)
    if user.is_graduate:
        q = q.where(Room.name.contains("DCELL"))
    q = q.order_by(Room.id)
    result = await db.execute(q)
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
    res = await get_user_remaining_hours_split(db, user.id, target_date)
    return {
        "remaining_hours": round(res["remaining_hours"], 2),
        "remaining_day_hours": round(res["remaining_day_hours"], 2),
        "remaining_dawn_hours": round(res["remaining_dawn_hours"], 2),
        "is_exam_period": res["is_exam_period"]
    }


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
    if user.is_graduate and "DCELL" not in room.name:
        raise HTTPException(status_code=403, detail="대학원생은 DCELL만 예약 가능합니다.")

    # max_advance_days 확인
    max_adv = await get_max_advance_days(db)
    from datetime import date, timedelta
    today = date.today()
    if start_dt.date() > today + timedelta(days=max_adv):
        raise HTTPException(status_code=400, detail=f"예약은 {max_adv}일 이내만 가능합니다.")

    # 인당 일일 제한 (시험 기간 분할 검증 적용)
    is_exam = await get_is_exam_period(db)
    max_hours = 5.0 if is_exam else float(await get_max_hours_per_day(db))
    
    req_dawn, req_day = split_reservation_hours(start_dt, end_dt)
    req_total = (end_dt - start_dt).total_seconds() / 3600.0
    
    from sqlalchemy import and_
    day_start = datetime.combine(start_dt.date(), datetime.min.time())
    day_end = datetime.combine(start_dt.date(), datetime.max.time())
    result = await db.execute(
        select(Reservation.start_time, Reservation.end_time, Reservation.billed_end_time).where(
            and_(
                Reservation.user_id == user.id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end + timedelta(seconds=1),
            )
        )
    )
    
    used_dawn = 0.0
    used_day = 0.0
    for r in result.all():
        eff_end = r.billed_end_time or r.end_time
        dawn, day = split_reservation_hours(r.start_time, eff_end)
        used_dawn += dawn
        used_day += day
        
    if is_exam:
        if used_day + req_day > 3.0:
            raise HTTPException(status_code=400, detail="시험기간 중 주간(09:00~24:00) 예약 한도는 최대 3시간입니다.")
        if used_dawn + req_dawn > 2.0:
            raise HTTPException(status_code=400, detail="시험기간 중 새벽(00:00~09:00) 예약 한도는 최대 2시간입니다.")
        if (used_dawn + used_day) + req_total > 5.0:
            raise HTTPException(status_code=400, detail="시험기간 중 일일 총 예약 한도는 5시간입니다.")
    else:
        if (used_dawn + used_day) + req_total > max_hours:
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

    # 중복 예약 체크 (같은 user, 같은 시간대 - 다른 방이어도 1인 1예약)
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
        raise HTTPException(status_code=400, detail="해당 시간에 이미 다른 예약이 있습니다.")

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


def _compute_cancel_flags(r: Reservation, now: datetime) -> tuple[bool, bool]:
    """취소: 예약 시작 전만. 퇴실: 예약 시작 후 진행 중일 때."""
    cancelable = now < r.start_time
    can_early_checkout = r.start_time <= now < r.end_time
    return cancelable, can_early_checkout


@router.get("/reservations/mine", response_model=list[ReservationOut])
async def list_my_reservations(
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now()
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
        for cancelable, can_early_checkout in [_compute_cancel_flags(r, now)]
    ]


@router.delete("/reservations/{reservation_id}", status_code=204)
async def cancel_reservation(
    reservation_id: int,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now()
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
    if now >= r.start_time:
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
    if now < r.start_time:
        raise HTTPException(status_code=400, detail="예약 시작 전에는 퇴실할 수 없습니다.")
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
    cancelable, can_early_checkout = _compute_cancel_flags(r, datetime.now())
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


# --- Notice Schema ---
class NoticeOut(BaseModel):
    id: int
    title: str
    content: str
    created_at: str


# --- Notice Route ---
@router.get("/notices", response_model=list[NoticeOut])
async def list_notices(db: AsyncSession = Depends(get_db)):
    from app.models.notice import Notice
    result = await db.execute(
        select(Notice).where(Notice.is_active == True).order_by(Notice.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        NoticeOut(
            id=n.id,
            title=n.title,
            content=n.content,
            created_at=n.created_at.isoformat()
        )
        for n in rows
    ]


# --- Notification Routes ---
@router.get("/notifications")
async def get_notifications(
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Reservation, Room)
        .join(Room, Reservation.room_id == Room.id)
        .where(
            Reservation.user_id == user.id,
            Reservation.cancelled_by_admin == True,
            Reservation.user_notified == False,
        )
    )
    rows = result.all()
    out = []
    for r, room in rows:
        out.append({
            "id": r.id,
            "room_name": room.name,
            "start_time": r.start_time.isoformat(),
            "end_time": r.end_time.isoformat(),
            "cancel_reason": r.cancel_reason or "사유가 입력되지 않았습니다."
        })
    return out


@router.post("/notifications/{reservation_id}/read")
async def read_notification(
    reservation_id: int,
    user: User = Depends(get_current_user_api),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.user_id == user.id
        )
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Notification not found")
    r.user_notified = True
    await db.commit()
    return {"ok": True}

