import datetime as dt

import pytest

from tracker.schedule import slot_for_cron, slot_for_local_time

UTC = dt.timezone.utc
TZ = "Europe/London"


def at(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=UTC)


@pytest.mark.parametrize("cron,now,expected", [
    # Summer (BST, UTC+1): the 06:00/18:00 UTC triggers are the real ones.
    ("0 6 * * *", at(2027, 7, 1, 6, 4), "morning"),
    ("0 7 * * *", at(2027, 7, 1, 7, 3), None),
    ("0 18 * * *", at(2027, 7, 1, 18, 10), "evening"),
    ("0 19 * * *", at(2027, 7, 1, 19, 2), None),
    # Winter (GMT, UTC+0): the 07:00/19:00 UTC triggers are the real ones.
    ("0 6 * * *", at(2027, 1, 15, 6, 4), None),
    ("0 7 * * *", at(2027, 1, 15, 7, 3), "morning"),
    ("0 18 * * *", at(2027, 1, 15, 18, 1), None),
    ("0 19 * * *", at(2027, 1, 15, 19, 1), "evening"),
    # A badly delayed run still counts as the slot it was scheduled for.
    ("0 6 * * *", at(2027, 7, 1, 7, 55), "morning"),
    ("0 7 * * *", at(2027, 1, 15, 8, 40), "morning"),
    # DST change days: 28 Mar 2027 (clocks forward 01:00 UTC), 31 Oct 2027 (back).
    ("0 6 * * *", at(2027, 3, 28, 6, 5), "morning"),
    ("0 7 * * *", at(2027, 3, 28, 7, 5), None),
    ("0 7 * * *", at(2027, 10, 31, 7, 5), "morning"),
    ("0 6 * * *", at(2027, 10, 31, 6, 5), None),
])
def test_slot_for_cron(cron, now, expected):
    assert slot_for_cron(cron, now, TZ, 7, 19) == expected


def test_run_delayed_past_midnight_uses_previous_day():
    # 19:00 UTC trigger on 15 Jan starting at 00:30 UTC on 16 Jan.
    assert slot_for_cron("0 19 * * *", at(2027, 1, 16, 0, 30), TZ, 7, 19) == "evening"


def test_bad_cron_rejected():
    with pytest.raises(ValueError):
        slot_for_cron("*/5 * * * *", at(2027, 1, 1, 0), TZ, 7, 19)


def test_manual_slot_by_uk_time():
    assert slot_for_local_time(at(2027, 7, 1, 11, 30), TZ) == "morning"  # 12:30 BST
    assert slot_for_local_time(at(2027, 7, 1, 12, 30), TZ) == "evening"  # 13:30 BST
