"""SystemConfig 조회 서비스."""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemConfig

DEFAULTS = {
    "slot_duration": 30,
    "max_hours_per_day": 3,
    "operating_hours": {"open": "09:00", "close": "24:00"},
    "exclude_weekends": True,
    "exclude_holidays": True,
    "max_advance_days": 7,
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
        return int(v) if v else 14
    except ValueError:
        return 14


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


async def get_exclude_weekends(db: AsyncSession) -> bool:
    v = await get_config(db, "exclude_weekends")
    return v.lower() in ("true", "1", "yes") if v else True


async def get_exclude_holidays(db: AsyncSession) -> bool:
    v = await get_config(db, "exclude_holidays")
    return v.lower() in ("true", "1", "yes") if v else True


async def get_holidays(db: AsyncSession) -> set[str]:
    v = await get_config(db, "holidays_json")
    try:
        arr = json.loads(v) if v else []
        return set(arr) if isinstance(arr, list) else set()
    except (json.JSONDecodeError, TypeError):
        return set()
