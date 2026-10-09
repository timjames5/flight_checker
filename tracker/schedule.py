"""Map GitHub's UTC cron triggers onto UK local run slots.

GitHub cron only speaks UTC, so the workflow fires at both candidate UTC
hours for each UK slot (06:00 and 07:00 UTC for the 07:00 UK run). Only the
trigger whose scheduled time is 07:00 or 19:00 in London on that date does
any work; the other exits immediately. Using the scheduled cron time rather
than the actual start time keeps this correct when GitHub starts a run late.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def parse_cron_time(cron: str) -> tuple[int, int]:
    """Return (hour, minute) from a daily cron expression like '0 6 * * *'."""
    fields = cron.split()
    if len(fields) != 5 or not fields[0].isdigit() or not fields[1].isdigit():
        raise ValueError(f"expected a fixed daily cron like '0 6 * * *', got {cron!r}")
    return int(fields[1]), int(fields[0])


def slot_for_cron(cron: str, now_utc: dt.datetime, tz: str,
                  morning_hour: int, evening_hour: int) -> str | None:
    """'morning', 'evening', or None if this trigger is the off-season duplicate."""
    hour, minute = parse_cron_time(cron)
    now_utc = now_utc.astimezone(dt.timezone.utc)
    scheduled = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # A run delayed past midnight UTC belongs to the previous day's schedule.
    if scheduled > now_utc:
        scheduled -= dt.timedelta(days=1)
    local_hour = scheduled.astimezone(ZoneInfo(tz)).hour
    if local_hour == morning_hour:
        return "morning"
    if local_hour == evening_hour:
        return "evening"
    return None


def slot_for_local_time(now_utc: dt.datetime, tz: str) -> str:
    """Slot for manual runs: before 13:00 local is morning, after is evening."""
    return "morning" if now_utc.astimezone(ZoneInfo(tz)).hour < 13 else "evening"
