import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.dependencies import get_current_user
from app.models import User
from app.routers import admin, auth, reservations
from app.templating import templates


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _format_http_detail(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail[:8]:
            if isinstance(item, dict):
                parts.append(str(item.get("msg", item)))
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "요청을 처리할 수 없습니다."
    return str(detail)


def _error_mascot_src(status_code: int) -> str:
    """404일 때만 404.jpg, 그 외는 기본 히나리 이미지."""
    if status_code == 404:
        return "/static/404.jpg"
    return "/static/error_hinari.png"


def _error_title(status_code: int) -> str:
    return {
        400: "이건 뭔가 잘못됐어요",
        401: "로그인이 필요해요",
        403: "들어갈 수 없어요",
        404: "여기엔 아무것도 없어요",
        405: "그 방법은 안 돼요",
        422: "입력을 다시 확인해 주세요",
        429: "잠깐만요, 너무 빨라요",
        500: "서버가 삐끗했어요",
    }.get(status_code, "앗, 문제가 생겼어요")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="스터디룸 예약 시스템", lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """브라우저는 HTML 에러 페이지, /api/* 는 JSON 유지."""
    if _is_api_request(request):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    msg = _format_http_detail(exc.detail)
    title = _error_title(exc.status_code)
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": exc.status_code,
            "title": title,
            "message": msg,
            "mascot_src": _error_mascot_src(exc.status_code),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """미처리 예외: 500. HTTPException은 상위 핸들러로."""
    if isinstance(exc, StarletteHTTPException):
        raise exc
    tb = traceback.format_exc()
    print(f"[500] {request.method} {request.url.path}\n{tb}")
    if _is_api_request(request):
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc) or "서버 오류가 발생했습니다."},
        )
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": 500,
            "title": _error_title(500),
            "message": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            "mascot_src": _error_mascot_src(500),
        },
        status_code=500,
    )
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

app.include_router(auth.router)
app.include_router(admin.router)  # /api/admin/* 먼저 등록 (더 구체적 경로)
app.include_router(reservations.router)

# 정적 파일 (favicon 등)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


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
