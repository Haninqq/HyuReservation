from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User, UserRole, parse_google_name
from app.templating import templates
from app.oauth import oauth

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
    )


@router.get("/auth/google")
async def auth_google(request: Request):
    redirect_uri = get_settings().google_redirect_uri
    # prompt=select_account: 매번 계정 선택 화면 표시 → 학교 메일로 로그인 선택 가능
    return await oauth.google.authorize_redirect(request, redirect_uri, prompt="select_account")


@router.get("/auth/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url="/login?error=token", status_code=302)

    userinfo = token.get("userinfo")
    if not userinfo:
        return RedirectResponse(url="/login?error=token", status_code=302)

    hd = userinfo.get("hd") or ""
    if hd != settings.allowed_domain:
        return RedirectResponse(url="/login?error=domain", status_code=302)

    email = userinfo.get("email", "")
    google_sub = userinfo.get("sub", "")
    raw_name = userinfo.get("name", "")
    name, dept = parse_google_name(raw_name or "")

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if user:
        user.name = name
        user.dept = dept
        user.email = email
        await db.commit()
        await db.refresh(user)
        request.session["user_id"] = user.id
        return RedirectResponse(url="/initial_setup", status_code=302)

    # 신규 사용자: 가입 정보를 세션에 저장 후 initial_setup으로 리다이렉트
    request.session["pending_signup"] = {
        "email": email,
        "name": name,
        "dept": dept,
        "google_sub": google_sub,
    }
    return RedirectResponse(url="/initial_setup", status_code=302)


@router.get("/initial_setup", response_class=HTMLResponse)
async def initial_setup_page(request: Request):
    if "user_id" in request.session:
        return RedirectResponse(url="/main", status_code=302)
    if "pending_signup" not in request.session:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "initial_setup.html",
        {"request": request},
    )


@router.post("/auth/complete_setup")
async def complete_setup(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    pending = request.session.pop("pending_signup", None)
    if not pending:
        return RedirectResponse(url="/login", status_code=302)

    is_graduate = (
        (await request.form()).get("is_graduate") in ("1", "on", "true")
    )

    role = UserRole.super_admin
    count_result = await db.execute(select(User))
    if count_result.scalars().all():
        role = UserRole.user

    user = User(
        email=pending["email"],
        name=pending["name"],
        dept=pending["dept"],
        google_sub=pending["google_sub"],
        role=role,
        is_graduate=is_graduate,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url="/main", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
