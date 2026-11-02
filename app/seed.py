"""DB 시드: SystemConfig 기본값, Room 8개."""
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Room, SystemConfig

DEFAULT_CONFIG = {
    "slot_duration": "30",
    "max_hours_per_day": "3",
    "operating_hours": '{"open": "09:00", "close": "24:00"}',
    "max_advance_days": "7",
    "is_exam_period": "false",
    # 공휴일은 holidays 라이브러리로 자동 계산된다 (app/services/config_service.get_holidays).
    # 여기에는 학교 자체 휴무일처럼 추가로 쉬는 날만 넣는다.
    "holidays_json": "[]",
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
