"""Database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.database_url, echo=settings.debug, connect_args=connect_args
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def get_db():
    """Dependency: yield a database session."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables (for SQLite dev usage)."""
    async with engine.begin() as conn:
        from . import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
