import enum

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DepartmentLevel(str, enum.Enum):
    grad_general = "grad_general"       # 일반대학원
    grad_education = "grad_education"   # 교육전문대학원


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[DepartmentLevel] = mapped_column(Enum(DepartmentLevel), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# 학부 학과는 사범대학 특성상 거의 안 바뀌어서 DB화하지 않고 고정 목록으로 관리한다.
UNDERGRAD_DEPARTMENTS = [
    "교육학과", "교육공학과", "국어교육과", "영어교육과", "수학교육과", "응용미술교육학과",
]
