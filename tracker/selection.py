"""Turn raw Ignav itineraries into FlightOptions and pick the cheapest ones."""

from __future__ import annotations

import logging
from typing import Iterable

from tracker.models import FlightOption

log = logging.getLogger(__name__)


def _flight_code(seg: dict) -> str:
    code = (seg.get("marketing_carrier_code") or "").strip()
    num = str(seg.get("flight_number") or "").replace(" ", "")
    if code and num.upper().startswith(code.upper()):
        return num
    return f"{code}{num}" or "?"


def _carrier_names(leg: dict) -> list[str]:
    # Prefer the leg-level summary; fall back to the segments' carriers.
    if leg.get("carrier"):
        return [leg["carrier"]]
    names = []
    for seg in leg.get("segments") or []:
        name = seg.get("operating_carrier_name") or seg.get("marketing_carrier_code")
        if name and name not in names:
            names.append(name)
    return names


def parse_itinerary(itin: dict) -> FlightOption | None:
    """Return a FlightOption, or None if the itinerary isn't a usable round trip."""
    out = itin.get("outbound") or {}
    inb = itin.get("inbound") or {}
    out_segs = out.get("segments") or []
    in_segs = inb.get("segments") or []
    price = itin.get("price") or {}
    if not out_segs or not in_segs or price.get("amount") is None:
        return None

    carriers = _carrier_names(out)
    for name in _carrier_names(inb):
        if name not in carriers:
            carriers.append(name)
    airline = " / ".join(carriers[:3]) or "Unknown airline"

    return FlightOption(
        price=float(price["amount"]),
        currency=price.get("currency") or "",
        price_status=price.get("status") or "",
        ignav_id=itin.get("ignav_id") or "",
        out_stops=len(out_segs) - 1,
        in_stops=len(in_segs) - 1,
        airline=airline,
        out_flights=", ".join(_flight_code(s) for s in out_segs),
        in_flights=", ".join(_flight_code(s) for s in in_segs),
        out_depart=out_segs[0].get("departure_time_local") or "",
        out_arrive=out_segs[-1].get("arrival_time_local") or "",
        in_depart=in_segs[0].get("departure_time_local") or "",
        in_arrive=in_segs[-1].get("arrival_time_local") or "",
        self_transfer=bool(itin.get("requires_self_transfer")),
    )


def parse_itineraries(itineraries: Iterable[dict], currency: str) -> list[FlightOption]:
    options = []
    for itin in itineraries:
        opt = parse_itinerary(itin)
        if opt is None:
            continue
        if currency and opt.currency and opt.currency.upper() != currency.upper():
            log.warning("skipping itinerary priced in %s (expected %s)", opt.currency, currency)
            continue
        options.append(opt)
    return options


def cheapest(options: Iterable[FlightOption], *, nonstop_only: bool = False) -> FlightOption | None:
    """Cheapest option, preferring fewer total stops on equal price."""
    pool = [o for o in options if o.is_nonstop or not nonstop_only]
    if not pool:
        return None
    return min(pool, key=lambda o: (o.price, o.out_stops + o.in_stops))


def pick_booking_url(response: dict) -> tuple[str | None, str | None]:
    """Choose the best URL from a booking-links response.

    Prefers an option that covers both legs in one booking, then airline
    sellers, then links that preselect the exact flights.
    """
    best = None
    best_rank = None
    for option in response.get("booking_options") or []:
        legs = set(option.get("legs") or [])
        covers_both = {"outbound", "inbound"} <= legs
        for link in option.get("links") or []:
            if not link.get("url"):
                continue
            rank = (
                0 if covers_both else 1,
                0 if link.get("provider_type") == "airline" else 1,
                0 if link.get("specificity") == "exact_flight" else 1,
            )
            if best_rank is None or rank < best_rank:
                best, best_rank = link, rank
    if best is None:
        return None, None
    return best["url"], best.get("provider_name")
