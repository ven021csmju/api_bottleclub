from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.db.models import Base  # noqa: F401  — single source of truth


def connect_args() -> dict:
    """Every connection's session time zone is the store's: timestamps come
    back as +07:00 and anything that still reads the session's date or hour
    gets the shop's, whatever the server's PostgreSQL ``timezone`` is."""
    return {"options": f"-c timezone={settings.STORE_TIMEZONE}"}


engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args(),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
