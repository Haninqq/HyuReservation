# 스터디룸 예약 시스템 (RSV)

한양대학교 학생 전용 스터디룸 예약 웹 시스템입니다.

## 기술 스택

- **Backend**: FastAPI, SQLite
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
# .env 파일 편집

# 개발 서버 실행
uvicorn app.main:app --reload --workers 1
```

## 페이지

- `/login` - Google OAuth2 로그인
- `/main` - 날짜·시간 선택 및 예약
