"""DB 시드: SystemConfig 기본값, Room 8개."""
import json
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Room, SystemConfig

DEFAULT_CONFIG = {
    "slot_duration": "30",
    "max_hours_per_day": "3",
    "operating_hours": json.dumps({"open": "09:00", "close": "24:00"}),
    "exclude_weekends": "true",
    "exclude_holidays": "true",
    "exam_period": "false",
    "exam_max_hours_per_day": "3",
    "max_advance_days": "7",
    "holidays_json": json.dumps([
        "2025-01-01",
        "2025-02-16", "2025-02-17", "2025-02-18",
        "2025-03-01", "2025-03-02",
        "2025-05-05", "2025-05-24", "2025-05-25",
        "2025-06-03", "2025-06-06",
        "2025-08-15", "2025-08-17",
        "2025-09-24", "2025-09-25", "2025-09-26",
        "2025-10-03", "2025-10-05", "2025-10-09",
        "2025-12-25",
    ]),
}

ROOM_NAMES = [
    "Studyroom A", "Studyroom B", "Studyroom C", "Studyroom D",
    "Studyroom E", "Studyroom F", "DCELL 1", "DCELL 2",
]


async def seed_db():
    async with AsyncSessionLocal() as db:
        # SystemConfig
        for key, value in DEFAULT_CONFIG.items():
            result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
            if result.scalar_one_or_none() is None:
                db.add(SystemConfig(key=key, value=value))

        # Room (8개)
        result = await db.execute(select(Room))
        if len(result.scalars().all()) == 0:
            for name in ROOM_NAMES:
                db.add(Room(name=name, is_active=True))

        await db.commit()
