from typing import Union

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, UserRole, user_dept_missing


async def get_logged_in_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Union[User, RedirectResponse]:
    """세션만 확인. 학과 미입력이어도 통과 (complete_dept 등)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    return user


async def get_current_user_api(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """API용: 미인증 시 401, 학과 미입력 시 403."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    if user_dept_missing(user):
        raise HTTPException(
            status_code=403,
            detail="학과를 입력해 주세요. 안내 페이지에서 학과를 등록한 뒤 이용할 수 있습니다.",
        )
    return user


async def get_current_user(
    request: Request,
    user_or_redirect: Union[User, RedirectResponse] = Depends(get_logged_in_user),
) -> Union[User, RedirectResponse]:
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    if user_dept_missing(user_or_redirect):
        return RedirectResponse(url="/complete_dept", status_code=302)
    return user_or_redirect


async def get_current_admin(
    user: User = Depends(get_current_user_api),
) -> User:
    """admin 또는 super_admin만 허용."""
    if user.role not in (UserRole.admin, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    return user


async def get_current_super_admin(
    user: User = Depends(get_current_user_api),
) -> User:
    """super_admin만 허용 (역할 변경 등)."""
    if user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    return user
