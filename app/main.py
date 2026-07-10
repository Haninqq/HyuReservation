from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import init_db
from app.dependencies import get_current_user
from app.models import User, UserRole
from app.routers import admin, auth, reservations
from app.templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="스터디룸 예약 시스템", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse("app/static/favicon.ico")


app.include_router(auth.router)
app.include_router(admin.router)  # /api/admin/* 먼저 등록 (더 구체적 경로)
app.include_router(reservations.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/login", status_code=302)


@app.get("/main", response_class=HTMLResponse)
async def main_page(request: Request, user_or_redirect=Depends(get_current_user)):
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    return templates.TemplateResponse(request=request, name="main.html", context={"user": user_or_redirect})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user_or_redirect=Depends(get_current_user)):
    if isinstance(user_or_redirect, RedirectResponse):
        return user_or_redirect
    if user_or_redirect.role not in [UserRole.admin, UserRole.super_admin]:
        return RedirectResponse(url="/main", status_code=302)
    return templates.TemplateResponse(request=request, name="admin.html", context={"user": user_or_redirect})

