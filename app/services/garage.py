import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bike import Bike


async def list_bikes(db: AsyncSession, user_id: uuid.UUID, *, active_only: bool = False):
    stmt = select(Bike).where(Bike.user_id == user_id)
    if active_only:
        stmt = stmt.where(Bike.is_active.is_(True))
    stmt = stmt.order_by(Bike.is_default.desc(), Bike.created_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def has_active_bike(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Gating check for uploads (spec US-03: >=1 active bike required)."""
    stmt = select(Bike.id).where(Bike.user_id == user_id, Bike.is_active.is_(True)).limit(1)
    return (await db.execute(stmt)).first() is not None


async def get_bike(db: AsyncSession, user_id: uuid.UUID, bike_id: uuid.UUID) -> Bike | None:
    stmt = select(Bike).where(Bike.id == bike_id, Bike.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _clear_defaults(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Bike).where(Bike.user_id == user_id).values(is_default=False)
    )


async def add_bike(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    make: str,
    model: str,
    year: int | None,
    nickname: str | None,
    photo_url: str | None,
) -> Bike:
    # First bike for a user becomes the default automatically.
    first = not await list_bikes(db, user_id)
    bike = Bike(
        user_id=user_id,
        make=make,
        model=model,
        year=year,
        nickname=nickname,
        photo_url=photo_url,
        is_default=first,
        is_active=True,
    )
    db.add(bike)
    await db.flush()
    return bike


async def set_default(db: AsyncSession, user_id: uuid.UUID, bike: Bike) -> None:
    await _clear_defaults(db, user_id)
    bike.is_default = True
    bike.is_active = True  # a default must be active
    db.add(bike)


async def set_active(db: AsyncSession, user_id: uuid.UUID, bike: Bike, active: bool) -> None:
    bike.is_active = active
    if not active and bike.is_default:
        # Reassign default to another active bike if one exists.
        bike.is_default = False
        db.add(bike)
        replacement = (
            await db.execute(
                select(Bike)
                .where(
                    Bike.user_id == user_id,
                    Bike.is_active.is_(True),
                    Bike.id != bike.id,
                )
                .order_by(Bike.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if replacement:
            replacement.is_default = True
            db.add(replacement)
    else:
        db.add(bike)
