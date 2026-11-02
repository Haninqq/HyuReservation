"""SystemConfig 조회 서비스."""
import json
from datetime import date

import holidays as kr_holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemConfig

DEFAULTS = {
    "slot_duration": 30,
    "max_hours_per_day": 3,
    "operating_hours": {"open": "09:00", "close": "24:00"},
    "max_advance_days": 7,
    "is_exam_period": False,
    "holidays_json": "[]",
}


async def get_config(db: AsyncSession, key: str) -> str:
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    row = result.scalar_one_or_none()
    if row:
        return row.value
    default = DEFAULTS.get(key)
    if default is not None:
        if isinstance(default, bool):
            return "true" if default else "false"
        if isinstance(default, dict):
            return json.dumps(default)
        return str(default)
    return ""


async def get_slot_duration(db: AsyncSession) -> int:
    v = await get_config(db, "slot_duration")
    try:
        return int(v) if v else 30
    except ValueError:
        return 30


async def get_max_hours_per_day(db: AsyncSession) -> int:
    v = await get_config(db, "max_hours_per_day")
    try:
        return int(v) if v else 3
    except ValueError:
        return 3


async def get_max_advance_days(db: AsyncSession) -> int:
    v = await get_config(db, "max_advance_days")
    try:
        return int(v) if v else 7
    except ValueError:
        return 7


async def get_operating_hours(db: AsyncSession) -> tuple[str, str]:
    v = await get_config(db, "operating_hours")
    try:
        d = json.loads(v) if v else {}
        return (
            d.get("open", "09:00"),
            d.get("close", "24:00"),
        )
    except (json.JSONDecodeError, TypeError):
        return "09:00", "24:00"


async def get_auto_holidays(years: list[int] | None = None) -> set[str]:
    """holidays 라이브러리로 계산한 대한민국 법정 공휴일(대체공휴일 포함)."""
    if years is None:
        this_year = date.today().year
        years = [this_year, this_year + 1]
    return {d.isoformat() for d in kr_holidays.country_holidays("KR", years=years)}


async def get_extra_holidays(db: AsyncSession) -> set[str]:
    """관리자가 수동으로 추가한 휴무일 (학교 자체 휴일 등)."""
    v = await get_config(db, "holidays_json")
    try:
        arr = json.loads(v) if v else []
        return set(arr) if isinstance(arr, list) else set()
    except (json.JSONDecodeError, TypeError):
        return set()


async def get_holidays(db: AsyncSession) -> set[str]:
    """자동 계산된 법정 공휴일 + 관리자가 추가한 휴무일."""
    auto = await get_auto_holidays()
    extra = await get_extra_holidays(db)
    return auto | extra


async def get_is_exam_period(db: AsyncSession) -> bool:
    v = await get_config(db, "is_exam_period")
    return v.lower() in ("true", "1", "yes") if v else False

