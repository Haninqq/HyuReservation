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
)


def _parse_time(s: str) -> time:
    """'09:00' -> time(9,0), '24:00' -> time(23,59) for end."""
    parts = s.split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if h == 24:
        h, m = 23, 59
    return time(h, m)


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

    # 주말 제외
    if exclude_wknd and target_date.weekday() >= 5:
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
    user_hours = sum(
        ((r.billed_end_time or r.end_time) - r.start_time).total_seconds() / 3600
        for r in user_result.all()
    )

    # 각 슬롯에 available, mine, occupied_by_others 부여
    # 현재 시간 이전 슬롯 제외 (오늘 날짜인 경우만, 서버 로컬 시각 기준)
    now = datetime.now()
    out = []
    can_book_more = user_hours < max_hours
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
        occupied_by_others = occupied and not mine
        available = not occupied and can_book_more
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
    """해당 날짜에 user가 추가로 예약 가능한 시간(시간 단위). 중도 퇴실 시 billed_end_time 사용."""
    max_hours = await get_max_hours_per_day(db)
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
    used = sum(
        ((r.billed_end_time or r.end_time) - r.start_time).total_seconds() / 3600
        for r in result.all()
    )
    return max(0, max_hours - used)
