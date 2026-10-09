import sqlite3

import pytest
from conftest import ROOT

from tracker import storage
from tracker.config import load_config


def test_old_database_is_migrated_with_rows_marked_economy(tmp_path):
    db = tmp_path / "p.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE quotes (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
                run_at_utc TEXT NOT NULL, depart_date TEXT NOT NULL, return_date TEXT NOT NULL,
                kind TEXT NOT NULL, price REAL);
            CREATE INDEX quotes_combo ON quotes (kind, depart_date, return_date, run_at_utc);
            INSERT INTO quotes (run_id, run_at_utc, depart_date, return_date, kind, price)
                VALUES (1, '2026-10-01T06:00:00Z', '2027-08-16', '2027-08-31', 'nonstop', 4100);
        """)
    conn = storage.connect(db)
    assert storage.nonstop_history(conn) == {
        ("economy", "2027-08-16", "2027-08-31"): [("2026-10-01T06:00:00Z", 4100)]}
    conn.close()


def _config(tmp_path, cabin_line):
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if "cabin_classes:" not in ln]
    i = next(n for n, ln in enumerate(lines) if ln.strip().startswith("adults:"))
    lines.insert(i, f"  {cabin_line}")
    path = tmp_path / "config.yaml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_config_lists_both_cabins(cfg):
    assert cfg.cabin_classes == ["economy", "premium_economy"]
    assert cfg.cabin_summary == "Economy + Premium economy"


def test_config_accepts_legacy_single_cabin_key(tmp_path):
    assert load_config(_config(tmp_path, "cabin_class: business")).cabin_classes == ["business"]


def test_config_rejects_unknown_cabin(tmp_path):
    with pytest.raises(ValueError, match="unknown cabin class"):
        load_config(_config(tmp_path, "cabin_classes: [economy, premium]"))
