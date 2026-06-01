# Import every model module here so Alembic autogenerate sees the full metadata.
# Model modules are added per build phase.
from app.db import Base  # noqa: F401
from app.models.bike import Bike  # noqa: F401
from app.models.ride import Ride, RidePoint, RideWeather  # noqa: F401
from app.models.user import OAuthAccount, User  # noqa: F401
