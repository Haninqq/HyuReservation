"""관리자 API: config, 예약 현황, 통계, user 역할, 공지사항 관리."""
from datetime import datetime, date, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_admin, get_current_super_admin
from app.models import Reservation, ReservationStatus, Room, SystemConfig, User, UserRole, Notice, Department, DepartmentLevel, UNDERGRAD_DEPARTMENTS

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Schemas ---
class ConfigItem(BaseModel):
    key: str
    value: str


class ConfigUpdate(BaseModel):
    config: dict[str, str]


class ReservationAdminOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    user_email: str
    user_dept: str
    room_id: int
    room_name: str
    start_time: str
    end_time: str
    status: str
    cancel_reason: str | None = None
    cancelled_by_admin: bool = False

    class Config:
        from_attributes = True


class ReservationCancelRequest(BaseModel):
    reason: str = "관리자에 의해 취소되었습니다."


class UserAdminOut(BaseModel):
    id: int
    email: str
    name: str
    dept: str
    role: str
    is_graduate: bool
    created_at: str


class UserRoleUpdate(BaseModel):
    role: str


class GraduateUpdate(BaseModel):
    is_graduate: bool


class DeptUpdate(BaseModel):
    dept: str


class DepartmentCreate(BaseModel):
    name: str
    level: str


class DepartmentAdminOut(BaseModel):
    id: int
    name: str
    level: str
    sort_order: int
    is_active: bool

    class Config:
        from_attributes = True


class NoticeCreate(BaseModel):
    title: str
    content: str


class NoticeUpdate(BaseModel):
    title: str
    content: str


class NoticeAdminOut(BaseModel):
    id: int
    title: str
    content: str
    created_at: str
    is_active: bool

    class Config:
        from_attributes = True


# --- Routes ---
@router.get("/config", response_model=list[ConfigItem])
async def get_config(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    return [ConfigItem(key=c.key, value=c.value) for c in result.scalars().all()]


@router.put("/config")
async def update_config(
    body: ConfigUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    for key, value in body.config.items():
        result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(SystemConfig(key=key, value=str(value)))
    await db.commit()
    return {"ok": True}


@router.get("/reservations", response_model=list[ReservationAdminOut])
async def list_reservations(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    date_from: str | None = Query(None, alias="date"),
    room_id: int | None = None,
):
    q = (
        select(Reservation, User, Room)
        .join(User, Reservation.user_id == User.id)
        .join(Room, Reservation.room_id == Room.id)
    )
    if date_from:
        try:
            d = datetime.strptime(date_from, "%Y-%m-%d").date()
            day_start = datetime.combine(d, time(0, 0, 0))
            day_end = datetime.combine(d, time(23, 59, 59))
            q = q.where(
                Reservation.start_time >= day_start,
                Reservation.end_time <= day_end,
            )
        except ValueError:
            pass
    if room_id is not None:
        q = q.where(Reservation.room_id == room_id)
    q = q.order_by(Reservation.start_time.desc())
    result = await db.execute(q)
    rows = result.all()
    return [
        ReservationAdminOut(
            id=r.id,
            user_id=r.user_id,
            user_name=u.name,
            user_email=u.email,
            user_dept=u.dept or "-",
            room_id=r.room_id,
            room_name=room.name,
            start_time=r.start_time.isoformat(),
            end_time=r.end_time.isoformat(),
            status=r.status.value,
            cancel_reason=r.cancel_reason,
            cancelled_by_admin=r.cancelled_by_admin,
        )
        for r, u, room in rows
    ]


@router.delete("/reservations/{reservation_id}", status_code=204)
async def admin_cancel_reservation(
    reservation_id: int,
    body: ReservationCancelRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    r.status = ReservationStatus.cancelled
    r.cancelled_by_admin = True
    r.user_notified = False
    r.cancel_reason = body.reason
    await db.commit()


@router.get("/stats")
async def get_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    # 오늘 예약 수
    today = date.today()
    day_start = datetime.combine(today, time(0, 0, 0))
    day_end = datetime.combine(today, time(23, 59, 59)) + timedelta(seconds=1)
    today_result = await db.execute(
        select(func.count(Reservation.id)).where(
            Reservation.status == ReservationStatus.confirmed,
            Reservation.start_time >= day_start,
            Reservation.end_time <= day_end,
        )
    )
    today_count = today_result.scalar() or 0

    # 방별 예약 횟수
    room_result = await db.execute(select(Room))
    rooms = room_result.scalars().all()
    by_room = []
    for room in rooms:
        cnt_result = await db.execute(
            select(func.count(Reservation.id)).where(
                room.id == Reservation.room_id,
                Reservation.status == ReservationStatus.confirmed,
            )
        )
        by_room.append({"room": room.name, "count": cnt_result.scalar() or 0})

    # 전체 예약 수
    total_result = await db.execute(
        select(func.count(Reservation.id)).where(Reservation.status == ReservationStatus.confirmed)
    )
    total_count = total_result.scalar() or 0

    return {
        "today_count": today_count,
        "total_count": total_count,
        "by_room": by_room,
    }


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            name=u.name,
            dept=u.dept or "-",
            role=u.role.value,
            is_graduate=bool(u.is_graduate),
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in users
    ]


@router.patch("/users/{user_id}/graduate")
async def update_user_graduate(
    user_id: int,
    body: GraduateUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_graduate = body.is_graduate
    await db.commit()
    return {"ok": True, "is_graduate": body.is_graduate}


@router.patch("/users/{user_id}/dept")
async def update_user_dept(
    user_id: int,
    body: DeptUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """학과가 비어있거나 잘못 들어간 사용자를 관리자가 직접 고쳐줄 수 있는 엔드포인트."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.dept = body.dept
    await db.commit()
    return {"ok": True, "dept": body.dept}


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: UserRoleUpdate,
    admin: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = UserRole(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = role
    await db.commit()
    return {"ok": True, "role": role.value}


# --- Notice Management Routes ---
@router.get("/notices", response_model=list[NoticeAdminOut])
async def list_admin_notices(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notice).order_by(Notice.created_at.desc()))
    rows = result.scalars().all()
    return [
        NoticeAdminOut(
            id=n.id,
            title=n.title,
            content=n.content,
            created_at=n.created_at.isoformat(),
            is_active=n.is_active,
        )
        for n in rows
    ]


@router.post("/notices", response_model=NoticeAdminOut)
async def create_notice(
    body: NoticeCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    n = Notice(title=body.title, content=body.content)
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return NoticeAdminOut(
        id=n.id,
        title=n.title,
        content=n.content,
        created_at=n.created_at.isoformat(),
        is_active=n.is_active,
    )


@router.put("/notices/{notice_id}", response_model=NoticeAdminOut)
async def update_notice(
    notice_id: int,
    body: NoticeUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notice).where(Notice.id == notice_id))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    n.title = body.title
    n.content = body.content
    await db.commit()
    await db.refresh(n)
    return NoticeAdminOut(
        id=n.id,
        title=n.title,
        content=n.content,
        created_at=n.created_at.isoformat(),
        is_active=n.is_active,
    )


@router.delete("/notices/{notice_id}", status_code=204)
async def delete_notice(
    notice_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notice).where(Notice.id == notice_id))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    # Soft delete by setting is_active = False
    n.is_active = False
    await db.commit()


# --- Department Management Routes ---
@router.get("/departments", response_model=list[DepartmentAdminOut])
async def list_admin_departments(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Department).order_by(Department.level, Department.sort_order))
    return [
        DepartmentAdminOut(
            id=d.id, name=d.name, level=d.level.value, sort_order=d.sort_order, is_active=d.is_active,
        )
        for d in result.scalars().all()
    ]


@router.post("/departments", response_model=DepartmentAdminOut)
async def create_department(
    body: DepartmentCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        level = DepartmentLevel(body.level)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid level")
    max_order_result = await db.execute(
        select(func.max(Department.sort_order)).where(Department.level == level)
    )
    next_order = (max_order_result.scalar() or 0) + 1
    d = Department(name=body.name, level=level, sort_order=next_order, is_active=True)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return DepartmentAdminOut(id=d.id, name=d.name, level=d.level.value, sort_order=d.sort_order, is_active=d.is_active)


@router.delete("/departments/{department_id}", status_code=204)
async def delete_department(
    department_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Department).where(Department.id == department_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="학과를 찾을 수 없습니다.")
    # Soft delete by setting is_active = False (이미 가입한 학생 데이터는 영향 없음)
    d.is_active = False
    await db.commit()


@router.get("/user-dept-options")
async def get_user_dept_options(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """사용자 관리 탭에서 학과를 고쳐줄 때 보여줄 전체 학과 옵션 (학부 고정목록 + 대학원 DB목록)."""
    result = await db.execute(
        select(Department).where(Department.is_active == True).order_by(Department.level, Department.sort_order)
    )
    all_depts = result.scalars().all()
    grad_general = [d.name for d in all_depts if d.level == DepartmentLevel.grad_general]
    grad_education = [d.name for d in all_depts if d.level == DepartmentLevel.grad_education]
    return {
        "undergraduate": UNDERGRAD_DEPARTMENTS,
        "grad_general": grad_general,
        "grad_education": grad_education,
    }
