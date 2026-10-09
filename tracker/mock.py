"""Offline stand-in for IgnavClient, used by --mock.

Returns responses shaped like the real API with prices that drift
deterministically with the run time, so repeated mock runs build a
plausible price history for testing the email and alert logic.
"""

from __future__ import annotations

import datetime as dt
import hashlib

NONSTOPS = [
    # (carrier name, code, outbound flight, out dep, out arr, inbound flight, in dep, in arr)
    ("Delta", "DL", "31", "10:25", "15:20", "30", "22:05", "11:15+1"),
    ("Virgin Atlantic", "VS", "103", "13:45", "18:35", "104", "19:30", "08:50+1"),
    ("British Airways", "BA", "227", "15:05", "19:55", "226", "21:40", "10:55+1"),
]


def _noise(*parts) -> float:
    """Deterministic value in [0, 1) from the given parts."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def _local(date: dt.date, hhmm: str) -> str:
    plus_day = hhmm.endswith("+1")
    hhmm = hhmm.removesuffix("+1")
    day = date + dt.timedelta(days=1 if plus_day else 0)
    return f"{day.isoformat()}T{hhmm}"


def _segment(code, name, number, dep_ap, arr_ap, date, dep, arr, minutes):
    return {
        "marketing_carrier_code": code,
        "flight_number": number,
        "operating_carrier_name": name,
        "departure_airport": dep_ap,
        "departure_time_local": _local(date, dep),
        "departure_timezone": None,
        "departure_time_utc": None,
        "arrival_airport": arr_ap,
        "arrival_time_local": _local(date, arr),
        "arrival_timezone": None,
        "arrival_time_utc": None,
        "duration_minutes": minutes,
        "aircraft": None,
    }


class MockIgnavClient:
    def __init__(self, now: dt.datetime):
        self.now = now
        # Changes twice a day so morning and evening runs differ.
        self.tick = f"{now.date()}-{'am' if now.hour < 12 else 'pm'}"
        self.days_elapsed = (now.date() - dt.date(2026, 10, 1)).days

    def _price(self, base: float, *key) -> float:
        drift = -4.0 * self.days_elapsed  # fares slowly ease over time
        wobble = (_noise(self.tick, *key) - 0.5) * 70
        return round(base + drift + wobble, 2)

    def round_trip(self, depart: dt.date, ret: dt.date, max_stops: int | None) -> dict:
        combo_bias = (depart.day - 16) * 55 + (0 if ret.month == 8 else 40)
        itineraries = []
        for name, code, out_no, od, oa, in_no, idp, ia in NONSTOPS:
            price = self._price(4150 + combo_bias + len(name) * 9, depart, ret, code)
            itineraries.append({
                "price": {"amount": price, "currency": "GBP", "status": "verified"},
                "outbound": {"carrier": name, "duration_minutes": 595, "segments": [
                    _segment(code, name, out_no, "LHR", "ATL", depart, od, oa, 595)]},
                "inbound": {"carrier": name, "duration_minutes": 520, "segments": [
                    _segment(code, name, in_no, "ATL", "LHR", ret, idp, ia, 520)]},
                "cabin_class": "economy",
                "requires_self_transfer": False,
                "ignav_id": hashlib.md5(f"{depart}{ret}{code}".encode()).hexdigest(),
            })
        if max_stops != 0:
            # A one-stop via New York; much cheaper on the 18 Aug / 31 Aug pair.
            saving = 420 if (depart.day, ret.day) == (18, 31) else 40
            price = self._price(4150 + combo_bias - saving, depart, ret, "AA")
            itineraries.append({
                "price": {"amount": price, "currency": "GBP", "status": "verified"},
                "outbound": {"carrier": "American Airlines", "duration_minutes": 760, "segments": [
                    _segment("AA", "American Airlines", "101", "LHR", "JFK", depart, "08:20", "11:15", 475),
                    _segment("AA", "American Airlines", "2245", "JFK", "ATL", depart, "13:05", "15:40", 155)]},
                "inbound": {"carrier": "American Airlines", "duration_minutes": 745, "segments": [
                    _segment("AA", "American Airlines", "1880", "ATL", "JFK", ret, "14:10", "16:35", 145),
                    _segment("AA", "American Airlines", "100", "JFK", "LHR", ret, "18:30", "06:40+1", 430)]},
                "cabin_class": "economy",
                "requires_self_transfer": False,
                "ignav_id": hashlib.md5(f"{depart}{ret}AA".encode()).hexdigest(),
            })
        return {
            "origin": "LHR",
            "destination": "ATL",
            "departure_date": depart.isoformat(),
            "return_date": ret.isoformat(),
            "itineraries": itineraries,
            "observed_at": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cache_hit": False,
        }

    def booking_links(self, ignav_id: str) -> dict:
        return {
            "itinerary": {},
            "booking_options": [{
                "legs": ["outbound", "inbound"],
                "links": [{
                    "provider_name": "Example Airline",
                    "provider_type": "airline",
                    "specificity": "exact_flight",
                    "url": f"https://example.com/book/{ignav_id}",
                }],
            }],
        }
