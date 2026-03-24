import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dept_choices import DEPTS_GRADUATE, DEPTS_UNDERGRAD, allowed_depts, is_valid_dept
from app.dependencies import get_logged_in_user
from app.models import User, UserRole, parse_google_name, user_dept_missing
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
        user.email = email
        # Google에서 학과를 파싱한 경우에만 갱신 — 허용 목록에 맞을 때만 (이상한 문자열 덮어쓰기 방지)
        if (dept or "").strip():
            d = dept.strip()
            if is_valid_dept(d, user.is_graduate):
                user.dept = d
        await db.commit()
        await db.refresh(user)
        request.session["user_id"] = user.id
        return RedirectResponse(url="/main", status_code=302)

    # 신규 사용자: 가입 정보를 세션에 저장 후 initial_setup으로 리다이렉트
    request.session["pending_signup"] = {
        "email": email,
        "name": name,
        "dept": dept,
        "google_sub": google_sub,
    }
    return RedirectResponse(url="/initial_setup", status_code=302)


@router.get("/complete_dept", response_class=HTMLResponse)
async def complete_dept_page(
    request: Request,
    user_or_redirect=Depends(get_logged_in_user),
):
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect
    if not user_dept_missing(user):
        return RedirectResponse(url="/main", status_code=302)
    error = request.query_params.get("error")
    dept_options = allowed_depts(user.is_graduate)
    return templates.TemplateResponse(
        "complete_dept.html",
        {
            "request": request,
            "error": error,
            "dept_options": dept_options,
            "is_graduate": user.is_graduate,
        },
    )


@router.post("/complete_dept")
async def complete_dept_submit(
    request: Request,
    user_or_redirect=Depends(get_logged_in_user),
    db: AsyncSession = Depends(get_db),
):
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    user = user_or_redirect
    if not user_dept_missing(user):
        return RedirectResponse(url="/main", status_code=302)
    form = await request.form()
    dept = (form.get("dept") or "").strip()
    if not is_valid_dept(dept, user.is_graduate):
        return RedirectResponse(url="/complete_dept?error=invalid", status_code=302)
    user.dept = dept
    await db.commit()
    await db.refresh(user)
    return RedirectResponse(url="/main", status_code=302)


@router.get("/initial_setup", response_class=HTMLResponse)
async def initial_setup_page(request: Request):
    if "pending_signup" not in request.session:
        return RedirectResponse(url="/login", status_code=302)
    error = request.query_params.get("error")
    pending = request.session["pending_signup"]
    prefill_dept = (pending.get("dept") or "").strip()
    setup_data_json = json.dumps(
        {
            "undergrad": DEPTS_UNDERGRAD,
            "graduate": DEPTS_GRADUATE,
            "prefill": prefill_dept,
        },
        ensure_ascii=False,
    )
    return templates.TemplateResponse(
        "initial_setup.html",
        {
            "request": request,
            "error": error,
            "setup_data_json": setup_data_json,
        },
    )


@router.post("/auth/complete_setup")
async def complete_setup(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    pending = request.session.get("pending_signup")
    if not pending:
        return RedirectResponse(url="/login", status_code=302)

    form_data = await request.form()
    is_graduate = form_data.get("is_graduate") in ("1", "true")
    dept = (form_data.get("dept") or "").strip() or (pending.get("dept") or "").strip()
    if not is_valid_dept(dept, is_graduate):
        return RedirectResponse(url="/initial_setup?error=dept", status_code=302)

    request.session.pop("pending_signup", None)

    role = UserRole.super_admin
    count_result = await db.execute(select(User))
    if count_result.scalars().all():
        role = UserRole.user
    user = User(
        email=pending["email"],
        name=pending["name"],
        dept=dept,
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
