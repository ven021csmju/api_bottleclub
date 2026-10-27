from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.db.models import Base  # noqa: F401  — single source of truth


def _set_store_timezone(dbapi_connection, _record) -> None:
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT set_config('timezone', %s, false)", (settings.STORE_TIMEZONE,))
    dbapi_connection.commit()


def use_store_timezone(engine: Engine) -> Engine:
    """Every new connection's session time zone is the store's: timestamps
    come back as +07:00 and anything that still reads the session's date or
    hour gets the shop's, whatever the server's ``timezone`` or the client's
    ``PGTZ`` is (a SET after connecting; ``PGTZ`` overrides libpq options)."""
    event.listen(engine, "connect", _set_store_timezone)
    return engine


engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
)
use_store_timezone(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
