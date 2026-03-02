from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables and seed default data."""
    import app.models  # noqa: F401 - register models with Base.metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # billed_end_time 컬럼 추가 (기존 DB 마이그레이션)
        await conn.run_sync(_add_billed_end_time_if_missing)

    from app.seed import seed_db
    await seed_db()


def _add_billed_end_time_if_missing(conn):
    """reservations 테이블에 billed_end_time 컬럼이 없으면 추가."""
    from sqlalchemy import text
    try:
        r = conn.execute(text("PRAGMA table_info(reservations)"))
        cols = [row[1] for row in r.fetchall()]
        if "billed_end_time" not in cols:
            conn.execute(text("ALTER TABLE reservations ADD COLUMN billed_end_time DATETIME"))
    except Exception:
        pass  # 테이블 없으면 스킵
