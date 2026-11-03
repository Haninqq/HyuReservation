"""DB 시드: SystemConfig 기본값, Room 8개, 대학원 학과 목록."""
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Room, SystemConfig, Department, DepartmentLevel

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

GRAD_GENERAL_DEPARTMENTS = [
    "교육공학과", "러닝사이언스학과", "응용미술학과", "한국어교육학과",
    "박물관교육학과", "다문화교육학과", "평생학습학과",
]

GRAD_EDUCATION_DEPARTMENTS = [
    "상담심리", "유아교육", "교육공학", "국어교육", "영어교육",
    "수학교육", "일반사회교육", "음악교육", "미술교육", "체육교육",
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

        # Department (대학원 17개, 최초 1회만 시드)
        result = await db.execute(select(Department))
        if len(result.scalars().all()) == 0:
            order = 0
            for name in GRAD_GENERAL_DEPARTMENTS:
                db.add(Department(name=name, level=DepartmentLevel.grad_general, sort_order=order, is_active=True))
                order += 1
            for name in GRAD_EDUCATION_DEPARTMENTS:
                db.add(Department(name=name, level=DepartmentLevel.grad_education, sort_order=order, is_active=True))
                order += 1

        await db.commit()
