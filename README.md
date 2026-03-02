# 스터디룸 예약 시스템 (RSV)

한양대학교 사범대학 스터디룸 & DCELL 예약 시스템입니다.

## 기술 스택

- **Backend**: FastAPI, SQLite (aiosqlite)
- **Frontend**: Jinja2, Bootstrap 5
- **Auth**: Google OAuth2 (hanyang.ac.kr 도메인)

## 설치 및 실행

```bash
# 가상환경 생성 및 활성화
python -m venv venv
# Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# .env 설정 (Google OAuth 등)
cp .env.example .env
# .env 파일 편집 (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 등)

# DB 시드 (선택)
python -m app.seed

# 개발 서버 실행
uvicorn app.main:app --reload --workers 1
```

## 배포 (AWS 등)

1. **환경 변수**: `.env.example` 참고하여 서버에 `.env` 설정
2. **GOOGLE_REDIRECT_URI**: 배포 URL로 변경 (예: `https://your-domain.com/auth/callback`)
3. **Google Cloud Console**: Redirect URI에 배포 URL 등록
4. **타임존**: 서울 배포 시 `TZ=Asia/Seoul` 설정 권장 (과거 슬롯 필터용)
5. **프로덕션**: `uvicorn app.main:app --host 0.0.0.0 --workers 1`

## 페이지

- `/login` - Google OAuth2 로그인
- `/main` - 날짜·시간 선택 및 예약
