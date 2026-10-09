import datetime as dt

from conftest import combo, option

from tracker import analysis

K1 = ("2027-08-16", "2027-08-31")
K2 = ("2027-08-17", "2027-08-31")


def E(dates, cabin="economy"):
    """History key for a date pair in a cabin."""
    return (cabin, *dates)


def hist(*pairs):
    return [(f"2026-10-0{i + 1}T06:00:00Z", p) for i, p in enumerate(pairs)]


# ---------------------------------------------------------------- comparisons

def test_changes_against_previous_and_first_run():
    history = {E(K1): hist(4200, 4100, 4150)}
    [s] = analysis.build_statuses([combo(*K1, nonstop=4000)], history)
    assert s.previous == 4150
    assert s.first == 4200
    assert s.change_since_last == -150
    assert s.change_since_start == -200
    assert s.all_time_low == 4000
    assert s.is_new_low


def test_first_ever_run_has_no_changes_and_no_new_low():
    [s] = analysis.build_statuses([combo(*K1, nonstop=4000)], {})
    assert s.change_since_last is None
    assert s.change_since_start is None
    assert s.all_time_low == 4000
    assert not s.is_new_low


def test_equal_to_previous_low_is_not_a_new_low():
    [s] = analysis.build_statuses([combo(*K1, nonstop=4100)], {E(K1): hist(4100, 4300)})
    assert not s.is_new_low
    assert s.all_time_low == 4100


def test_all_time_low_keeps_history_when_price_rises():
    [s] = analysis.build_statuses([combo(*K1, nonstop=4500)], {E(K1): hist(4000, 4300)})
    assert s.all_time_low == 4000
    assert s.change_since_last == 200


def test_missing_current_price():
    [s] = analysis.build_statuses([combo(*K1, nonstop=None)], {E(K1): hist(4000)})
    assert s.current is None
    assert s.change_since_last is None
    assert s.all_time_low == 4000
    assert not s.is_new_low
    assert not s.dropped_by(25)


def test_best_nonstop_picks_cheapest_priced_combo():
    statuses = analysis.build_statuses(
        [combo(*K1, nonstop=4300), combo(*K2, nonstop=4100),
         combo("2027-08-18", "2027-08-31", nonstop=None)], {})
    assert analysis.best_nonstop(statuses).result.key == E(K2)


def test_best_nonstop_none_when_nothing_priced():
    statuses = analysis.build_statuses([combo(*K1, nonstop=None)], {})
    assert analysis.best_nonstop(statuses) is None


# ---------------------------------------------------------------- alert rules

def test_drop_exactly_at_threshold_alerts():
    statuses = analysis.build_statuses([combo(*K1, nonstop=4075)], {E(K1): hist(4000, 4100)})
    reasons = analysis.alert_reasons(statuses, 25)
    assert len(reasons) == 1 and "down £25" in reasons[0]


def test_drop_below_threshold_does_not_alert():
    statuses = analysis.build_statuses([combo(*K1, nonstop=4076)], {E(K1): hist(4000, 4100)})
    assert analysis.alert_reasons(statuses, 25) == []


def test_small_drop_to_new_low_alerts():
    statuses = analysis.build_statuses([combo(*K1, nonstop=3995)], {E(K1): hist(4000, 4005)})
    reasons = analysis.alert_reasons(statuses, 25)
    assert reasons == ["Economy · Mon 16 Aug → Tue 31 Aug: new all-time low £3,995"]


def test_big_drop_to_new_low_gives_both_reasons():
    statuses = analysis.build_statuses([combo(*K1, nonstop=3900)], {E(K1): hist(4000, 4100)})
    assert len(analysis.alert_reasons(statuses, 25)) == 2


def test_price_rise_does_not_alert():
    statuses = analysis.build_statuses([combo(*K1, nonstop=4200)], {E(K1): hist(4000, 4100)})
    assert analysis.alert_reasons(statuses, 25) == []


def test_any_combo_can_trigger():
    statuses = analysis.build_statuses(
        [combo(*K1, nonstop=4100), combo(*K2, nonstop=4000)],
        {E(K1): hist(4100), E(K2): hist(4050, 4100)})
    reasons = analysis.alert_reasons(statuses, 25)
    assert reasons and all("17 Aug" in r for r in reasons)


def test_should_send_rules():
    assert analysis.should_send("morning", problem=False, reasons=[], force=False)
    assert not analysis.should_send("evening", problem=False, reasons=[], force=False)
    assert analysis.should_send("evening", problem=False, reasons=["x"], force=False)
    assert analysis.should_send("evening", problem=True, reasons=[], force=False)
    assert analysis.should_send("evening", problem=False, reasons=[], force=True)


def test_problem_only_when_every_combo_lacks_nonstop():
    assert analysis.is_problem([combo(*K1, nonstop=None), combo(*K2, nonstop=None, errors=["HTTP 401"])])
    assert not analysis.is_problem([combo(*K1, nonstop=None), combo(*K2, nonstop=4000)])


# ---------------------------------------------------------------- connecting options

def test_connecting_listed_when_saving_meets_minimum():
    assert analysis.connecting_worth_listing(option(4000), option(3850, 1, 1), 150)


def test_connecting_hidden_when_saving_too_small():
    assert not analysis.connecting_worth_listing(option(4000), option(3851, 1, 1), 150)


def test_connecting_hidden_when_overall_is_nonstop():
    assert not analysis.connecting_worth_listing(option(4000), option(3000), 150)


def test_connecting_hidden_without_nonstop_to_compare():
    assert not analysis.connecting_worth_listing(None, option(3000, 1, 0), 150)


# ---------------------------------------------------------------- chart data

def test_chart_series_takes_min_per_run_and_counts_days():
    history = {
        E(K1): [("2026-10-01T06:00:00Z", 4200), ("2026-10-01T18:00:00Z", 4150), ("2026-10-02T06:00:00Z", 4100)],
        E(K2): [("2026-10-01T06:00:00Z", 4000), ("2026-10-02T06:00:00Z", 4300)],
    }
    series = analysis.chart_series(history, "Europe/London", ["economy"])
    assert [p for _, p in series["economy"]] == [4000, 4150, 4100]
    assert series["economy"][0][0].tzinfo is not None
    assert analysis.distinct_days(series) == 2


def test_chart_series_keeps_cabins_apart_in_config_order():
    history = {
        E(K1): [("2026-10-01T06:00:00Z", 4200)],
        E(K1, "premium_economy"): [("2026-10-01T06:00:00Z", 7000), ("2026-10-02T06:00:00Z", 6900)],
        E(K1, "business"): [("2026-10-01T06:00:00Z", 16000)],  # no longer configured
    }
    series = analysis.chart_series(history, "Europe/London", ["premium_economy", "economy", "first"])
    assert list(series) == ["premium_economy", "economy"]
    assert [p for _, p in series["premium_economy"]] == [7000, 6900]
    assert [p for _, p in series["economy"]] == [4200]
    assert analysis.distinct_days(series) == 2


def test_distinct_days_uses_uk_dates():
    # 23:30 UTC on 1 Oct is 00:30 on 2 Oct in London (BST).
    series = analysis.chart_series(
        {E(K1): [("2026-10-01T22:00:00Z", 1), ("2026-10-01T23:30:00Z", 2)]}, "Europe/London", ["economy"])
    assert analysis.distinct_days(series) == 2
    assert series["economy"][1][0].date() == dt.date(2026, 10, 2)


# ---------------------------------------------------------------- cabins

def test_history_is_matched_per_cabin():
    premium = combo(*K1, nonstop=7000)
    premium.cabin = "premium_economy"
    history = {E(K1): hist(4000), E(K1, "premium_economy"): hist(7100)}
    [econ, prem] = analysis.build_statuses([combo(*K1, nonstop=4000), premium], history)
    assert econ.change_since_last == 0
    assert prem.change_since_last == -100
    reasons = analysis.alert_reasons([econ, prem], 25)
    assert reasons == ["Premium economy · Mon 16 Aug → Tue 31 Aug: down £100 since last check",
                       "Premium economy · Mon 16 Aug → Tue 31 Aug: new all-time low £7,000"]
