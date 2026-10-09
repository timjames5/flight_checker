import datetime as dt

from tracker.http import ApiError
from tracker.ignav import search_combo
from tracker.selection import cheapest, parse_itinerary, pick_booking_url

D1, D2 = dt.date(2027, 8, 16), dt.date(2027, 8, 31)


def seg(code, num, dep, arr, dep_t="2027-08-16T10:00", arr_t="2027-08-16T15:00"):
    return {"marketing_carrier_code": code, "flight_number": num, "operating_carrier_name": None,
            "departure_airport": dep, "arrival_airport": arr,
            "departure_time_local": dep_t, "arrival_time_local": arr_t, "duration_minutes": 1}


def itin(price, out_segs, in_segs, iid, currency="GBP", carrier="Delta"):
    return {"price": {"amount": price, "currency": currency, "status": "verified"},
            "outbound": {"carrier": carrier, "segments": out_segs},
            "inbound": {"carrier": carrier, "segments": in_segs} if in_segs is not None else None,
            "ignav_id": iid}


NONSTOP = itin(4200, [seg("DL", "31", "LHR", "ATL")], [seg("DL", "30", "ATL", "LHR")], "ns")
ONE_STOP_OUT = itin(3900, [seg("AA", "101", "LHR", "JFK"), seg("AA", "2245", "JFK", "ATL")],
                    [seg("DL", "30", "ATL", "LHR")], "1s")


def test_parse_nonstop():
    o = parse_itinerary(NONSTOP)
    assert o.is_nonstop and o.price == 4200
    assert (o.out_flights, o.in_flights) == ("DL31", "DL30")
    assert o.out_depart == "2027-08-16T10:00"


def test_parse_counts_stops_per_leg_from_segments():
    o = parse_itinerary(ONE_STOP_OUT)
    assert (o.out_stops, o.in_stops) == (1, 0)
    assert not o.is_nonstop
    assert o.out_flights == "AA101, AA2245"
    assert o.out_arrive == "2027-08-16T15:00"


def test_flight_number_already_prefixed():
    o = parse_itinerary(itin(1, [seg("BA", "BA 227", "LHR", "ATL")], [seg("BA", "226", "ATL", "LHR")], "x"))
    assert o.out_flights == "BA227"


def test_one_way_only_itinerary_is_rejected():
    assert parse_itinerary(itin(1, [seg("DL", "31", "LHR", "ATL")], None, "x")) is None


def test_cheapest_nonstop_vs_overall():
    opts = [parse_itinerary(NONSTOP), parse_itinerary(ONE_STOP_OUT)]
    assert cheapest(opts, nonstop_only=True).ignav_id == "ns"
    assert cheapest(opts).ignav_id == "1s"
    assert cheapest([parse_itinerary(ONE_STOP_OUT)], nonstop_only=True) is None


def test_pick_booking_url_prefers_single_booking_airline_exact():
    resp = {"booking_options": [
        {"legs": ["outbound"], "links": [{"provider_name": "A", "provider_type": "airline",
                                          "specificity": "exact_flight", "url": "u1"}]},
        {"legs": ["outbound", "inbound"], "links": [
            {"provider_name": "OTA", "provider_type": "third_party", "specificity": "exact_flight", "url": "u2"},
            {"provider_name": "Delta", "provider_type": "airline", "specificity": "search_results", "url": "u3"},
            {"provider_name": "Delta", "provider_type": "airline", "specificity": "exact_flight", "url": "u4"},
        ]},
    ]}
    assert pick_booking_url(resp) == ("u4", "Delta")
    assert pick_booking_url({"booking_options": []}) == (None, None)


class FakeClient:
    def __init__(self, nonstop_resp, any_resp, fail_links=False):
        self.responses = {0: nonstop_resp, None: any_resp}
        self.fail_links = fail_links
        self.link_calls = []

    def round_trip(self, depart, ret, max_stops):
        resp = self.responses[max_stops]
        if isinstance(resp, Exception):
            raise resp
        return resp

    def booking_links(self, ignav_id):
        self.link_calls.append(ignav_id)
        if self.fail_links:
            raise ApiError("HTTP 503")
        return {"booking_options": [{"legs": ["outbound", "inbound"],
                                     "links": [{"provider_name": "P", "url": f"https://b/{ignav_id}"}]}]}


def test_search_combo_records_nonstop_and_overall(cfg):
    client = FakeClient({"itineraries": [NONSTOP]}, {"itineraries": [ONE_STOP_OUT]})
    r = search_combo(client, cfg, D1, D2)
    assert r.nonstop.ignav_id == "ns" and r.nonstop.booking_url == "https://b/ns"
    assert r.overall.ignav_id == "1s" and r.overall.booking_url == "https://b/1s"
    assert r.errors == []


def test_search_combo_filters_stops_even_if_api_ignores_max_stops(cfg):
    client = FakeClient({"itineraries": [ONE_STOP_OUT]}, {"itineraries": [ONE_STOP_OUT]})
    r = search_combo(client, cfg, D1, D2)
    assert r.nonstop is None
    assert r.overall.ignav_id == "1s"


def test_search_combo_ignores_wrong_currency(cfg):
    usd = itin(100, [seg("DL", "31", "LHR", "ATL")], [seg("DL", "30", "ATL", "LHR")], "usd", currency="USD")
    r = search_combo(FakeClient({"itineraries": [usd, NONSTOP]}, {"itineraries": []}), cfg, D1, D2)
    assert r.nonstop.ignav_id == "ns"


def test_search_combo_one_booking_call_when_same_option(cfg):
    client = FakeClient({"itineraries": [NONSTOP]}, {"itineraries": [NONSTOP]})
    r = search_combo(client, cfg, D1, D2)
    assert r.nonstop is r.overall or r.nonstop.ignav_id == r.overall.ignav_id
    assert client.link_calls == ["ns"]


def test_search_combo_survives_partial_failures(cfg):
    client = FakeClient(ApiError("HTTP 503"), {"itineraries": [NONSTOP]}, fail_links=True)
    r = search_combo(client, cfg, D1, D2)
    assert r.nonstop.ignav_id == "ns"
    assert r.nonstop.booking_url is None
    assert len(r.errors) == 2
