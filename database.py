from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

# SQLite synchronous engine for development
sqlite_url = "sqlite:///./data.db"
engine = create_engine(
    sqlite_url,
    echo=False,  # Set to True for SQL logging
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Dependency to get database session for FastAPI routes."""
    with Session(engine) as session:
        yield session
