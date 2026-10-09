"""Load and validate config.yaml."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Config:
    origin: str
    destination: str
    outbound_dates: list[dt.date]
    return_dates: list[dt.date]
    adults: int
    children: int
    cabin_class: str
    market: str
    currency: str
    evening_drop_threshold: float
    connecting_min_saving: float
    chart_min_days: int
    timezone: str
    morning_hour: int
    evening_hour: int
    email_from: str
    database: str
    api_base_url: str
    api_timeout: float
    api_max_attempts: int
    api_backoff_base: float

    @property
    def combos(self) -> list[tuple[dt.date, dt.date]]:
        """Every (outbound, return) pair, ordered by outbound then return."""
        return [
            (out, ret)
            for out in sorted(self.outbound_dates)
            for ret in sorted(self.return_dates)
            if ret >= out
        ]

    @property
    def passenger_summary(self) -> str:
        parts = [f"{self.adults} adult{'s' if self.adults != 1 else ''}"]
        if self.children:
            parts.append(f"{self.children} child{'ren' if self.children != 1 else ''}")
        return " + ".join(parts)


def _date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    trip = raw["trip"]
    alerts = raw.get("alerts", {})
    schedule = raw.get("schedule", {})
    email = raw.get("email", {})
    storage = raw.get("storage", {})
    api = raw.get("api", {})

    cfg = Config(
        origin=trip["origin"].upper(),
        destination=trip["destination"].upper(),
        outbound_dates=[_date(d) for d in trip["outbound_dates"]],
        return_dates=[_date(d) for d in trip["return_dates"]],
        adults=int(trip.get("adults", 1)),
        children=int(trip.get("children", 0)),
        cabin_class=trip.get("cabin_class", "economy"),
        market=trip.get("market", "GB"),
        currency=trip.get("currency", "GBP"),
        evening_drop_threshold=float(alerts.get("evening_drop_threshold", 25)),
        connecting_min_saving=float(alerts.get("connecting_min_saving", 150)),
        chart_min_days=int(alerts.get("chart_min_days", 3)),
        timezone=schedule.get("timezone", "Europe/London"),
        morning_hour=int(schedule.get("morning_hour", 7)),
        evening_hour=int(schedule.get("evening_hour", 19)),
        email_from=email.get("from", "Flight Tracker <onboarding@resend.dev>"),
        database=storage.get("database", "data/prices.db"),
        api_base_url=api.get("base_url", "https://ignav.com/api").rstrip("/"),
        api_timeout=float(api.get("timeout_seconds", 60)),
        api_max_attempts=int(api.get("max_attempts", 4)),
        api_backoff_base=float(api.get("backoff_base_seconds", 2)),
    )
    if not cfg.combos:
        raise ValueError("config.yaml: no valid outbound/return date combinations")
    if cfg.adults + cfg.children > 9:
        raise ValueError("config.yaml: Ignav allows at most 9 passengers")
    return cfg
