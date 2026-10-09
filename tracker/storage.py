"""SQLite persistence: one row per run, one row per (combo, kind) per run."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from tracker.models import ComboResult, FlightOption

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at_utc  TEXT NOT NULL,
    slot        TEXT NOT NULL,
    mock        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quotes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    run_at_utc     TEXT NOT NULL,
    depart_date    TEXT NOT NULL,
    return_date    TEXT NOT NULL,
    cabin_class    TEXT NOT NULL DEFAULT 'economy',
    kind          TEXT NOT NULL CHECK (kind IN ('nonstop', 'overall')),
    price          REAL,
    currency       TEXT,
    price_status   TEXT,
    out_stops      INTEGER,
    in_stops       INTEGER,
    airline        TEXT,
    out_flights    TEXT,
    in_flights     TEXT,
    out_depart     TEXT,
    out_arrive     TEXT,
    in_depart      TEXT,
    in_arrive      TEXT,
    self_transfer  INTEGER,
    ignav_id       TEXT,
    booking_url    TEXT,
    observed_at    TEXT,
    cache_hit      INTEGER,
    error          TEXT
);
"""

# Created after _migrate so the cabin_class column exists on older databases.
INDEXES = """
DROP INDEX IF EXISTS quotes_combo;
CREATE INDEX IF NOT EXISTS quotes_cabin_combo
    ON quotes (kind, cabin_class, depart_date, return_date, run_at_utc);
"""


def utc_iso(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(INDEXES)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add cabin_class to databases from before multi-cabin tracking (all economy)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(quotes)")}
    if "cabin_class" not in columns:
        with conn:
            conn.execute("ALTER TABLE quotes ADD COLUMN cabin_class TEXT NOT NULL DEFAULT 'economy'")


def save_run(conn: sqlite3.Connection, run_at: dt.datetime, slot: str,
             results: list[ComboResult], mock: bool = False) -> int:
    ts = utc_iso(run_at)
    with conn:
        run_id = conn.execute(
            "INSERT INTO runs (run_at_utc, slot, mock) VALUES (?, ?, ?)",
            (ts, slot, int(mock)),
        ).lastrowid
        for r in results:
            error = "; ".join(r.errors) or None
            for kind, opt in (("nonstop", r.nonstop), ("overall", r.overall)):
                _insert_quote(conn, run_id, ts, r, kind, opt, error)
    return run_id


def _insert_quote(conn, run_id, ts, r: ComboResult, kind: str,
                  opt: FlightOption | None, error: str | None) -> None:
    row = {
        "run_id": run_id, "run_at_utc": ts,
        "depart_date": r.depart.isoformat(), "return_date": r.ret.isoformat(),
        "cabin_class": r.cabin, "kind": kind, "observed_at": r.observed_at,
        "cache_hit": None if r.cache_hit is None else int(r.cache_hit),
        "error": error,
    }
    if opt is not None:
        row.update({
            "price": opt.price, "currency": opt.currency, "price_status": opt.price_status,
            "out_stops": opt.out_stops, "in_stops": opt.in_stops, "airline": opt.airline,
            "out_flights": opt.out_flights, "in_flights": opt.in_flights,
            "out_depart": opt.out_depart, "out_arrive": opt.out_arrive,
            "in_depart": opt.in_depart, "in_arrive": opt.in_arrive,
            "self_transfer": int(opt.self_transfer), "ignav_id": opt.ignav_id,
            "booking_url": opt.booking_url,
        })
    elif row["error"] is None:
        row["error"] = "no matching itineraries"
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO quotes ({cols}) VALUES ({marks})", list(row.values()))


def nonstop_history(conn: sqlite3.Connection) -> dict[tuple[str, str, str], list[tuple[str, float]]]:
    """All recorded nonstop prices per (cabin, depart, return), oldest first."""
    history: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
    rows = conn.execute(
        """SELECT cabin_class, depart_date, return_date, run_at_utc, price FROM quotes
           WHERE kind = 'nonstop' AND price IS NOT NULL
           ORDER BY run_at_utc, id"""
    )
    for row in rows:
        key = (row["cabin_class"], row["depart_date"], row["return_date"])
        history.setdefault(key, []).append(
            (row["run_at_utc"], row["price"])
        )
    return history
