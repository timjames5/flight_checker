import sqlite3

from conftest import ROOT

from tracker.main import main

CONFIG = str(ROOT / "config.yaml")


def test_missing_api_key_prints_problem_email_and_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IGNAV_API_KEY", raising=False)
    code = main(["--config", CONFIG, "--db", str(tmp_path / "p.db"), "--dry-run", "--slot", "evening"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Flight tracker problem" in out and "IGNAV_API_KEY is not set" in out


def test_mock_runs_record_history_and_evening_stays_quiet_without_drop(tmp_path, capsys):
    db = str(tmp_path / "p.db")
    base = ["--config", CONFIG, "--db", db, "--mock", "--dry-run", "--save"]
    assert main(base + ["--slot", "morning", "--now", "2026-10-02T06:05:00Z"]) == 0
    assert "Subject: " in capsys.readouterr().out

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 24  # 2 cabins x 6 combos x 2 kinds

    # Same mock tick again: identical prices, so an evening run sends nothing.
    assert main(base + ["--slot", "evening", "--now", "2026-10-02T06:10:00Z"]) == 0
    assert "Subject: " not in capsys.readouterr().out


def test_dry_run_without_save_leaves_db_untouched(tmp_path):
    db = tmp_path / "p.db"
    main(["--config", CONFIG, "--db", str(db), "--mock", "--dry-run", "--slot", "morning"])
    assert not db.exists()
