import pytest

from app.models.ride import STATUS_DONE, Ride
from app.services import garage as garage_svc
from app.services import stats as stats_svc


async def _published_ride(db, user_id, bike_id, dist, elev, moving):
    r = Ride(
        user_id=user_id,
        bike_id=bike_id,
        published=True,
        processing_status=STATUS_DONE,
        distance_m=dist,
        elev_gain=elev,
        moving_time_s=moving,
        title="t",
    )
    db.add(r)
    await db.flush()
    return r


@pytest.mark.asyncio
async def test_lifetime_and_per_bike(db, user):
    b1 = await garage_svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    b2 = await garage_svc.add_bike(
        db, user.id, make="Honda", model="CB500", year=2020, nickname=None, photo_url=None
    )
    await _published_ride(db, user.id, b1.id, 10000, 100, 1800)
    await _published_ride(db, user.id, b1.id, 20000, 200, 3600)
    await _published_ride(db, user.id, b2.id, 5000, 50, 900)
    # A draft ride must NOT count.
    draft = Ride(user_id=user.id, bike_id=b1.id, published=False,
                 processing_status=STATUS_DONE, distance_m=99999)
    db.add(draft)
    await db.flush()

    life = await stats_svc.lifetime_stats(db, user.id)
    assert life.rides == 3
    assert life.distance_m == pytest.approx(35000)
    assert life.elev_gain == pytest.approx(350)

    per = await stats_svc.per_bike_stats(db, user.id)
    by_label = {bs.bike.label: bs for bs in per}
    assert by_label["2022 Yamaha MT-07"].rides == 2
    assert by_label["2022 Yamaha MT-07"].distance_m == pytest.approx(30000)
    assert by_label["2020 Honda CB500"].rides == 1
    # Ordered by distance desc.
    assert per[0].bike.id == b1.id


@pytest.mark.asyncio
async def test_recent_rides_pagination(db, user):
    b = await garage_svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    for _ in range(12):
        await _published_ride(db, user.id, b.id, 1000, 10, 60)

    page1, has_next1 = await stats_svc.recent_rides(db, user.id, page=1, per_page=10)
    assert len(page1) == 10
    assert has_next1 is True

    page2, has_next2 = await stats_svc.recent_rides(db, user.id, page=2, per_page=10)
    assert len(page2) == 2
    assert has_next2 is False
