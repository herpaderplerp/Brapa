import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.user import User


@pytest.fixture
async def db():
    # Dedicated NullPool engine per test so connections never outlive the
    # function-scoped event loop. Rolled back at the end, leaving the DB clean.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture
async def user(db) -> User:
    u = User(email=f"{uuid.uuid4().hex}@test.dev", display_name="Tester")
    db.add(u)
    await db.flush()
    return u
