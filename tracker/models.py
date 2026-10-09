"""Data types shared across the tracker."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class FlightOption:
    """One round-trip itinerary, reduced to the fields we track."""

    price: float
    currency: str
    price_status: str
    ignav_id: str
    out_stops: int
    in_stops: int
    airline: str
    out_flights: str  # e.g. "DL31" or "BA227, AA1234"
    in_flights: str
    out_depart: str  # local times as returned by Ignav, e.g. "2027-08-16T10:25"
    out_arrive: str
    in_depart: str
    in_arrive: str
    self_transfer: bool = False
    booking_url: str | None = None
    booking_provider: str | None = None

    @property
    def is_nonstop(self) -> bool:
        return self.out_stops == 0 and self.in_stops == 0

    @property
    def stops_label(self) -> str:
        def one(n: int) -> str:
            return "nonstop" if n == 0 else f"{n} stop{'s' if n > 1 else ''}"

        if self.out_stops == self.in_stops:
            return f"{one(self.out_stops)} each way"
        return f"out {one(self.out_stops)}, back {one(self.in_stops)}"


@dataclass
class ComboResult:
    """Search outcome for one outbound/return date pair in one cabin."""

    depart: dt.date
    ret: dt.date
    cabin: str = "economy"
    nonstop: FlightOption | None = None  # (a) cheapest with both legs nonstop
    overall: FlightOption | None = None  # (b) cheapest regardless of stops
    errors: list[str] = field(default_factory=list)
    observed_at: str | None = None
    cache_hit: bool | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.cabin, self.depart.isoformat(), self.ret.isoformat())
