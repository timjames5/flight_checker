"""Price comparisons and alert decisions. Pure functions, no I/O."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from tracker.models import ComboResult, FlightOption

History = dict[tuple[str, str], list[tuple[str, float]]]


@dataclass
class ComboStatus:
    result: ComboResult
    current: float | None
    previous: float | None  # nonstop price from the most recent earlier run
    first: float | None  # first nonstop price ever recorded
    previous_low: float | None  # lowest before this run

    @property
    def change_since_last(self) -> float | None:
        if self.current is None or self.previous is None:
            return None
        return round(self.current - self.previous, 2)

    @property
    def change_since_start(self) -> float | None:
        if self.current is None or self.first is None:
            return None
        return round(self.current - self.first, 2)

    @property
    def all_time_low(self) -> float | None:
        prices = [p for p in (self.current, self.previous_low) if p is not None]
        return min(prices) if prices else None

    @property
    def is_new_low(self) -> bool:
        """Strictly below every earlier price. A first-ever price doesn't count."""
        return (
            self.current is not None
            and self.previous_low is not None
            and self.current < self.previous_low
        )

    def dropped_by(self, threshold: float) -> bool:
        change = self.change_since_last
        return change is not None and -change >= threshold


def build_statuses(results: list[ComboResult], history: History) -> list[ComboStatus]:
    """Compare this run against history recorded before it."""
    statuses = []
    for r in results:
        past = [price for _, price in history.get(r.key, [])]
        statuses.append(ComboStatus(
            result=r,
            current=r.nonstop.price if r.nonstop else None,
            previous=past[-1] if past else None,
            first=past[0] if past else None,
            previous_low=min(past) if past else None,
        ))
    return statuses


def best_nonstop(statuses: list[ComboStatus]) -> ComboStatus | None:
    priced = [s for s in statuses if s.current is not None]
    return min(priced, key=lambda s: s.current) if priced else None


def alert_reasons(statuses: list[ComboStatus], drop_threshold: float) -> list[str]:
    """Reasons that justify a PRICE DROP email. Empty list means no alert."""
    reasons = []
    for s in statuses:
        label = combo_label(s.result.depart, s.result.ret)
        if s.dropped_by(drop_threshold):
            reasons.append(f"{label}: down £{-s.change_since_last:,.0f} since last check")
        if s.is_new_low:
            reasons.append(f"{label}: new all-time low £{s.current:,.0f}")
    return reasons


def connecting_worth_listing(nonstop: FlightOption | None, overall: FlightOption | None,
                             min_saving: float) -> bool:
    """A connecting option is shown only if it beats the nonstop by min_saving."""
    if nonstop is None or overall is None or overall.is_nonstop:
        return False
    return nonstop.price - overall.price >= min_saving


def is_problem(results: list[ComboResult]) -> bool:
    """True when no combo produced a nonstop price (API down, bad key, etc.)."""
    return all(r.nonstop is None for r in results)


def should_send(slot: str, problem: bool, reasons: list[str], force: bool) -> bool:
    if problem or force or slot == "morning":
        return True
    return bool(reasons)


def chart_series(history: History, tz: str) -> list[tuple[dt.datetime, float]]:
    """Cheapest nonstop price across all combos at each run, oldest first."""
    by_run: dict[str, float] = {}
    for points in history.values():
        for ts, price in points:
            by_run[ts] = min(price, by_run.get(ts, price))
    zone = ZoneInfo(tz)
    return [
        (dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).astimezone(zone), price)
        for ts, price in sorted(by_run.items())
    ]


def distinct_days(series: list[tuple[dt.datetime, float]]) -> int:
    return len({when.date() for when, _ in series})


def combo_label(depart: dt.date, ret: dt.date) -> str:
    return f"{depart:%a} {depart.day} {depart:%b} → {ret:%a} {ret.day} {ret:%b}"
