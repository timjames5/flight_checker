"""Ignav API client and the per-date-combo search."""

from __future__ import annotations

import datetime as dt
import logging

import requests

from tracker.config import Config
from tracker.http import ApiError, request_with_retry
from tracker.models import ComboResult, FlightOption
from tracker.selection import cheapest, parse_itineraries, pick_booking_url

log = logging.getLogger(__name__)


class IgnavClient:
    def __init__(self, api_key: str, cfg: Config, session: requests.Session | None = None):
        if not api_key:
            raise ApiError("IGNAV_API_KEY is not set")
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    def _post(self, path: str, body: dict) -> dict:
        resp = request_with_retry(
            self.session,
            "POST",
            f"{self.cfg.api_base_url}{path}",
            json=body,
            max_attempts=self.cfg.api_max_attempts,
            backoff_base=self.cfg.api_backoff_base,
            timeout=self.cfg.api_timeout,
        )
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError(f"invalid JSON from {path}: {exc}") from exc

    def round_trip(self, depart: dt.date, ret: dt.date, max_stops: int | None) -> dict:
        body = {
            "origin": self.cfg.origin,
            "destination": self.cfg.destination,
            "departure_date": depart.isoformat(),
            "return_date": ret.isoformat(),
            "adults": self.cfg.adults,
            "children": self.cfg.children,
            "cabin_class": self.cfg.cabin_class,
            "market": self.cfg.market,
        }
        if max_stops is not None:
            body["max_stops"] = max_stops
        return self._post("/fares/round-trip", body)

    def booking_links(self, ignav_id: str) -> dict:
        return self._post("/fares/booking-links", {"ignav_id": ignav_id})


def search_combo(client, cfg: Config, depart: dt.date, ret: dt.date) -> ComboResult:
    """Search one date pair and record the cheapest nonstop and overall options.

    Two searches run: one with max_stops=0, one without a stops filter. Ignav
    doesn't return every combination, so the unfiltered search can miss
    nonstop fares; pooling both and filtering on segment counts ourselves
    gives the most reliable answer to both questions.
    """
    result = ComboResult(depart=depart, ret=ret)
    options: list[FlightOption] = []

    for label, max_stops in (("nonstop search", 0), ("any-stops search", None)):
        try:
            data = client.round_trip(depart, ret, max_stops)
        except ApiError as exc:
            result.errors.append(f"{label}: {exc}")
            continue
        options.extend(parse_itineraries(data.get("itineraries") or [], cfg.currency))
        result.observed_at = result.observed_at or data.get("observed_at")
        if data.get("cache_hit") is not None:
            result.cache_hit = bool(data["cache_hit"])

    result.nonstop = cheapest(options, nonstop_only=True)
    result.overall = cheapest(options)

    links: dict[str, tuple[str | None, str | None]] = {}
    for opt in (result.nonstop, result.overall):
        if opt is None or not opt.ignav_id:
            continue
        if opt.ignav_id not in links:
            try:
                links[opt.ignav_id] = pick_booking_url(client.booking_links(opt.ignav_id))
            except ApiError as exc:
                result.errors.append(f"booking links for {opt.out_flights}: {exc}")
                links[opt.ignav_id] = (None, None)
        opt.booking_url, opt.booking_provider = links[opt.ignav_id]

    return result


def search_all(client, cfg: Config) -> list[ComboResult]:
    results = []
    for depart, ret in cfg.combos:
        log.info("searching %s -> %s", depart, ret)
        results.append(search_combo(client, cfg, depart, ret))
    return results
