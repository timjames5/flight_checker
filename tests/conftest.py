import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.config import load_config  # noqa: E402
from tracker.models import ComboResult, FlightOption  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.yaml")


def option(price: float, out_stops: int = 0, in_stops: int = 0, **kw) -> FlightOption:
    defaults = dict(
        currency="GBP", price_status="verified", ignav_id=f"id-{price}-{out_stops}{in_stops}",
        airline="Delta", out_flights="DL31", in_flights="DL30",
        out_depart="2027-08-16T10:25", out_arrive="2027-08-16T15:20",
        in_depart="2027-08-31T22:05", in_arrive="2027-09-01T11:15",
    )
    defaults.update(kw)
    return FlightOption(price=price, out_stops=out_stops, in_stops=in_stops, **defaults)


def combo(depart: str, ret: str, nonstop: float | None, overall: FlightOption | None = None,
          errors=None) -> ComboResult:
    ns = option(nonstop) if nonstop is not None else None
    return ComboResult(
        depart=dt.date.fromisoformat(depart), ret=dt.date.fromisoformat(ret),
        nonstop=ns, overall=overall or ns, errors=errors or [],
    )
