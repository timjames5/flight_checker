"""Command-line entry point: python -m tracker [options]."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

from tracker import analysis, storage
from tracker.chart import price_chart_png
from tracker.config import cabin_name, load_config
from tracker.emailer import render_digest, render_problem, send_email
from tracker.http import ApiError
from tracker.ignav import IgnavClient, search_all
from tracker.models import ComboResult
from tracker.schedule import slot_for_cron, slot_for_local_time

log = logging.getLogger("tracker")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m tracker", description=__doc__)
    p.add_argument("--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="print the email instead of sending it; doesn't write to the database unless --save")
    p.add_argument("--force-email", action="store_true",
                   help="send (or print) the digest even when the alert rules say not to")
    p.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto",
                   help="which run this is; auto picks from the current UK time")
    p.add_argument("--scheduled-cron", default="",
                   help="the cron expression that triggered a scheduled GitHub run; "
                        "runs that don't land on a UK slot exit without doing anything")
    p.add_argument("--db", help="SQLite path (defaults to storage.database in config.yaml)")
    p.add_argument("--save", action="store_true", help="with --dry-run, still record results")
    p.add_argument("--mock", action="store_true", help="use fake API data instead of calling Ignav")
    p.add_argument("--now", help="pretend the current UTC time is this ISO timestamp (testing)")
    p.add_argument("--preview-dir", help="with --dry-run, also write email.html, email.txt, chart.png here")
    p.add_argument("--html-only", action="store_true", help="with --dry-run, print only the HTML")
    return p.parse_args(argv)


def _now(arg: str | None) -> dt.datetime:
    if not arg:
        return dt.datetime.now(dt.timezone.utc)
    when = dt.datetime.fromisoformat(arg.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _failed_results(cfg, message: str) -> list[ComboResult]:
    return [ComboResult(depart=d, ret=r, cabin=c, errors=[message])
            for c in cfg.cabin_classes for d, r in cfg.combos]


def _print_summary(statuses: list[analysis.ComboStatus]) -> None:
    for s in statuses:
        r = s.result
        line = f"{analysis.result_label(r)}  nonstop={s.current}  "
        line += f"overall={r.overall.price if r.overall else None}"
        if r.overall and not r.overall.is_nonstop:
            line += f" ({r.overall.stops_label})"
        if r.errors:
            line += f"  errors={r.errors}"
        log.info(line)


def main(argv=None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # email text contains → and £
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    now = _now(args.now)

    if args.scheduled_cron:
        slot = slot_for_cron(args.scheduled_cron, now, cfg.timezone, cfg.morning_hour, cfg.evening_hour)
        if slot is None:
            log.info("trigger %r isn't a UK %02d:00/%02d:00 slot today (DST duplicate); nothing to do",
                     args.scheduled_cron, cfg.morning_hour, cfg.evening_hour)
            return 0
    elif args.slot != "auto":
        slot = args.slot
    else:
        slot = slot_for_local_time(now, cfg.timezone)
    log.info("running %s check at %s", slot, storage.utc_iso(now))

    save = args.save or not args.dry_run
    db_path = args.db or cfg.database
    conn = storage.connect(db_path if save or Path(db_path).exists() else ":memory:")
    history = storage.nonstop_history(conn)

    if args.mock:
        from tracker.mock import MockIgnavClient
        results = search_all(MockIgnavClient(now), cfg)
    else:
        try:
            client = IgnavClient(os.environ.get("IGNAV_API_KEY", ""), cfg)
        except ApiError as exc:
            results = _failed_results(cfg, str(exc))
        else:
            results = search_all(client, cfg)

    if save:
        storage.save_run(conn, now, slot, results, mock=args.mock)
    conn.close()

    statuses = analysis.build_statuses(results, history)
    _print_summary(statuses)
    problem = analysis.is_problem(results)
    reasons = [] if problem else analysis.alert_reasons(statuses, cfg.evening_drop_threshold)

    if not analysis.should_send(slot, problem, reasons, args.force_email):
        log.info("evening run: no drop of £%.0f+ and no new low, so no email", cfg.evening_drop_threshold)
        return 0

    chart_png = None
    if problem:
        email = render_problem(cfg, results, run_at=now, slot=slot)
    else:
        merged = {k: list(v) for k, v in history.items()}
        for r in results:
            if r.nonstop:
                merged.setdefault(r.key, []).append((storage.utc_iso(now), r.nonstop.price))
        series = analysis.chart_series(merged, cfg.timezone, cfg.cabin_classes)
        if analysis.distinct_days(series) >= cfg.chart_min_days:
            chart_png = price_chart_png({cabin_name(c): s for c, s in series.items()})
        email = render_digest(cfg, statuses, run_at=now, slot=slot, reasons=reasons, chart_png=chart_png)

    if args.dry_run:
        if args.html_only:
            print(email.html)
        else:
            print(f"Subject: {email.subject}\n")
            print("=" * 30, "PLAIN TEXT", "=" * 30)
            print(email.text)
            print("\n" + "=" * 30, "HTML", "=" * 30)
            print(email.html)
            if chart_png:
                print(f"\n[inline chart attached as cid:price-chart, {len(chart_png):,} bytes]")
        if args.preview_dir:
            out = Path(args.preview_dir)
            out.mkdir(parents=True, exist_ok=True)
            html = email.html
            if chart_png:
                (out / "chart.png").write_bytes(chart_png)
                html = html.replace("cid:price-chart", "chart.png")
            (out / "email.html").write_text(html, encoding="utf-8")
            (out / "email.txt").write_text(f"Subject: {email.subject}\n\n{email.text}", encoding="utf-8")
            log.info("preview written to %s", out.resolve())
    else:
        message_id = send_email(cfg, email, api_key=os.environ.get("RESEND_API_KEY", ""),
                                to=os.environ.get("ALERT_EMAIL", ""))
        log.info("sent %r (resend id %s)", email.subject, message_id)

    # A problem email is sent, but the run is still marked failed so it shows red in Actions.
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
