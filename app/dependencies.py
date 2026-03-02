from typing import Union

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, UserRole


async def get_current_user_api(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """API용: 미인증 시 401 반환."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Union[User, RedirectResponse]:
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    return user


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
