import io

import httpx
import pytest
from PIL import Image

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.photo import Photo
from app.models.ride import STATUS_DONE, Ride
from app.services import exif


def _plain_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def _jpeg_with_gps(lat_dms, lat_ref, lon_dms, lon_ref) -> bytes:
    img = Image.new("RGB", (16, 16), (10, 20, 30))
    ex = img.getexif()
    gps = {1: lat_ref, 2: lat_dms, 3: lon_ref, 4: lon_dms}
    ex[0x8825] = gps  # GPSInfo IFD
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=ex.tobytes())
    return buf.getvalue()


def test_exif_plain_has_no_gps():
    lat, lon, taken = exif.extract(_plain_jpeg())
    assert lat is None and lon is None


def test_exif_extracts_gps():
    data = _jpeg_with_gps((37.0, 48.0, 0.0), "N", (122.0, 24.0, 0.0), "W")
    lat, lon, _ = exif.extract(data)
    assert lat == pytest.approx(37.8, abs=0.01)
    assert lon == pytest.approx(-122.4, abs=0.01)


@pytest.mark.asyncio
async def test_upload_and_list_photos(db, user):
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE, published=True)
    db.add(ride)
    await db.flush()
    await db.commit()
    ride_id = ride.id

    app.dependency_overrides[require_login] = lambda: user
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
            # one geotagged, one plain
            geo = _jpeg_with_gps((45.0, 0.0, 0.0), "N", (75.0, 0.0, 0.0), "W")
            files = [
                ("files", ("geo.jpg", geo, "image/jpeg")),
                ("files", ("plain.jpg", _plain_jpeg(), "image/jpeg")),
            ]
            up = await c.post(f"/rides/{ride_id}/photos", files=files, follow_redirects=False)
            assert up.status_code == 303

            pj = await c.get(f"/rides/{ride_id}/photos.json")
            body = pj.json()
            assert len(body["photos"]) == 1  # only the geotagged one has coords
            file_url = body["photos"][0]["url"]
            served = await c.get(file_url)
            assert served.status_code == 200
            assert served.headers["content-type"].startswith("image/")
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Photo).where(Photo.ride_id == ride_id))
        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        await global_engine.dispose()
