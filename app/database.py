"""
Database configuration for Lampeland Bakeri Ordresystem.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool, StaticPool
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _load_database_url() -> str:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    app_env = (os.getenv("APP_ENV") or "development").strip().lower()

    if database_url:
        return database_url

    if app_env in {"production", "prod", "staging"}:
        raise RuntimeError(
            "DATABASE_URL environment variable is required in production-like environments. "
            "Refusing to fall back to a local SQLite database."
        )

    return "sqlite:///./lampeland_bakeri.db"


DATABASE_URL = _load_database_url()

# Configure engine based on database type
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


def get_db():
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
