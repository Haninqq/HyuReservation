import traceback
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import init_db
from app.dependencies import get_current_user
from app.models import User
from app.routers import admin, auth, reservations
from app.templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="스터디룸 예약 시스템", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """500 에러 시 traceback 로깅. HTTPException은 FastAPI 기본 처리 유지."""
    if isinstance(exc, HTTPException):
        raise exc
    tb = traceback.format_exc()
    print(f"[500] {request.method} {request.url.path}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "서버 오류가 발생했습니다."},
    )
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

app.include_router(auth.router)
app.include_router(admin.router)  # /api/admin/* 먼저 등록 (더 구체적 경로)
app.include_router(reservations.router)


@app.get("/")
async def root(user_or_redirect=Depends(get_current_user)):
    """로그인 시 /main, 미로그인 시 /login으로 리다이렉트."""
    if isinstance(user_or_redirect, RedirectResponse):
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/main", status_code=302)


@app.get("/main", response_class=HTMLResponse)
async def main_page(request: Request, user_or_redirect=Depends(get_current_user)):
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    return templates.TemplateResponse("main.html", {"request": request, "user": user_or_redirect})
