"""예약 가능 슬롯 계산 서비스."""
from datetime import datetime, date, time, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reservation, ReservationStatus
from app.services.config_service import (
    get_operating_hours,
    get_exclude_weekends,
    get_exclude_holidays,
    get_slot_duration,
    get_max_hours_per_day,
    get_holidays,
    get_is_exam_period,
)


def _parse_time(s: str) -> time:
    """'09:00' -> time(9,0), '24:00' -> time(23,59) for end."""
    parts = s.split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if h == 24:
        h, m = 23, 59
    return time(h, m)


def split_reservation_hours(start: datetime, end: datetime) -> tuple[float, float]:
    """예약 시간 [start, end]를 새벽(00:00~09:00)과 주간(09:00~24:00)으로 분할하여 각각의 시간(hour)을 반환."""
    pivot = datetime.combine(start.date(), time(9, 0))
    
    dawn_seconds = 0.0
    day_seconds = 0.0
    
    # 새벽 시간대 계산 (start ~ pivot 사이의 겹치는 부분)
    if start < pivot:
        dawn_end = min(end, pivot)
        if start < dawn_end:
            dawn_seconds = (dawn_end - start).total_seconds()
        
    # 주간 시간대 계산 (pivot ~ end 사이의 겹치는 부분)
    if end > pivot:
        day_start = max(start, pivot)
        if day_start < end:
            day_seconds = (end - day_start).total_seconds()
        
    return dawn_seconds / 3600.0, day_seconds / 3600.0


async def get_available_slots(
    db: AsyncSession, target_date: date, room_id: int, user_id: int
) -> list[dict]:
    """
    해당 날짜·방의 슬롯 목록. 각 슬롯: {start, end, available: bool}
    """
    open_s, close_s = await get_operating_hours(db)
    slot_mins = await get_slot_duration(db)
    exclude_wknd = await get_exclude_weekends(db)
    exclude_hol = await get_exclude_holidays(db)
    holidays = await get_holidays(db)
    max_hours = await get_max_hours_per_day(db)
    is_exam = await get_is_exam_period(db)

    # 주말(일요일) 제외
    if exclude_wknd and target_date.weekday() == 6:
        return []


    # 공휴일 제외
    date_str = target_date.isoformat()
    if exclude_hol and date_str in holidays:
        return []

    open_t = _parse_time(open_s)
    close_t = _parse_time(close_s)
    open_dt = datetime.combine(target_date, open_t)
    close_dt = datetime.combine(target_date, close_t)
    if close_t == time(23, 59):
        close_dt += timedelta(minutes=1)

    # 슬롯 생성
    slots = []
    current = open_dt
    while current + timedelta(minutes=slot_mins) <= close_dt:
        end_dt = current + timedelta(minutes=slot_mins)
        slots.append({"start": current, "end": end_dt})
        current = end_dt

    if not slots:
        return []

    # 해당 방·날짜의 confirmed 예약 조회
    day_start = datetime.combine(target_date, time(0, 0))
    day_end = datetime.combine(target_date, time(23, 59, 59))
    result = await db.execute(
        select(Reservation.start_time, Reservation.end_time)
        .where(
            and_(
                Reservation.room_id == room_id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end + timedelta(seconds=1),
            )
        )
    )
    occupied_ranges = [(r.start_time, r.end_time) for r in result.all()]

    # user의 해당 날짜·해당 방 예약 (나의 예약)
    user_room_result = await db.execute(
        select(Reservation.start_time, Reservation.end_time).where(
            and_(
                Reservation.user_id == user_id,
                Reservation.room_id == room_id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end + timedelta(seconds=1),
            )
        )
    )
    mine_ranges = [(r.start_time, r.end_time) for r in user_room_result.all()]

    # user의 해당 날짜·다른 방 예약 (동시간 예약 불가이므로 슬롯 비가능 처리)
    user_other_room_result = await db.execute(
        select(Reservation.start_time, Reservation.end_time).where(
            and_(
                Reservation.user_id == user_id,
                Reservation.room_id != room_id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end + timedelta(seconds=1),
            )
        )
    )
    user_other_room_ranges = [(r.start_time, r.end_time) for r in user_other_room_result.all()]

    # user의 해당 날짜 전체 예약 시간 합계 (한도 계산용, 중도 퇴실 시 billed_end_time 사용)
    user_result = await db.execute(
        select(Reservation.start_time, Reservation.end_time, Reservation.billed_end_time).where(
            and_(
                Reservation.user_id == user_id,
                Reservation.status == ReservationStatus.confirmed,
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end + timedelta(seconds=1),
            )
        )
    )
    
    used_dawn = 0.0
    used_day = 0.0
    for r in user_result.all():
        eff_end = r.billed_end_time or r.end_time
        dawn, day = split_reservation_hours(r.start_time, eff_end)
        used_dawn += dawn
        used_day += day

    # 각 슬롯에 available, mine, occupied_by_others 부여
    # 현재 시간 이전 슬롯 제외 (오늘 날짜인 경우만, 서버 로컬 시각 기준)
    now = datetime.now()
    out = []
    
    for slot in slots:
        if target_date == now.date() and slot["end"] <= now:
            continue
        occupied = any(
            slot["start"] < r_end and slot["end"] > r_start
            for r_start, r_end in occupied_ranges
        )
        mine = any(
            slot["start"] < r_end and slot["end"] > r_start
            for r_start, r_end in mine_ranges
        )
        conflict_other_room = any(
            slot["start"] < r_end and slot["end"] > r_start
            for r_start, r_end in user_other_room_ranges
        )
        
        # 슬롯 단독의 시간 영역 분할
        slot_dawn, slot_day = split_reservation_hours(slot["start"], slot["end"])
        
        if is_exam:
            # 시험 기간 모드: 새벽 2시간, 주간 3시간, 합계 5시간
            can_book_more = (
                (used_dawn + slot_dawn <= 2.0) and
                (used_day + slot_day <= 3.0) and
                ((used_dawn + used_day) + (slot_dawn + slot_day) <= 5.0)
            )
        else:
            # 평상시 모드: 전체 총량 검사
            can_book_more = ((used_dawn + used_day) + (slot_dawn + slot_day) <= max_hours)

        occupied_by_others = occupied and not mine
        available = not occupied and can_book_more and not conflict_other_room
        out.append({
            "start": slot["start"].isoformat(),
            "end": slot["end"].isoformat(),
            "available": available,
            "occupied": occupied,
            "mine": mine,
            "occupied_by_others": occupied_by_others,
        })

    return out


async def get_user_remaining_hours(
    db: AsyncSession, user_id: int, target_date: date
) -> float:
    """하위 호환성용: 총 남은 시간 반환."""
    res = await get_user_remaining_hours_split(db, user_id, target_date)
    return res["remaining_hours"]


async def get_user_remaining_hours_split(
    db: AsyncSession, user_id: int, target_date: date
) -> dict:
    """해당 날짜에 user가 추가로 예약 가능한 시간(주간, 새벽, 전체 잔여량)."""
    is_exam = await get_is_exam_period(db)
    max_hours = 5.0 if is_exam else float(await get_max_hours_per_day(db))
    
    day_start = datetime.combine(target_date, time(0, 0))
    day_end = datetime.combine(target_date, time(23, 59, 59))
    result = await db.execute(
        select(Reservation.start_time, Reservation.end_time, Reservation.billed_end_time).where(
            and_(
                Reservation.user_id == user_id,
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
        remaining_dawn = max(0.0, 2.0 - used_dawn)
        remaining_day = max(0.0, 3.0 - used_day)
        remaining_total = max(0.0, 5.0 - (used_dawn + used_day))
    else:
        remaining_dawn = 0.0
        remaining_day = max(0.0, max_hours - used_day)
        remaining_total = max(0.0, max_hours - (used_dawn + used_day))
        
    return {
        "remaining_hours": remaining_total,
        "remaining_day_hours": remaining_day,
        "remaining_dawn_hours": remaining_dawn,
        "is_exam_period": is_exam
    }

