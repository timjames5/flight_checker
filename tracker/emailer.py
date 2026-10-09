"""Render digest / alert / problem emails and send them through Resend."""

from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass, field
from html import escape
from zoneinfo import ZoneInfo

import requests

from tracker.analysis import ComboStatus, best_nonstop, combo_label, connecting_worth_listing
from tracker.config import Config
from tracker.http import request_with_retry
from tracker.models import ComboResult, FlightOption

RESEND_URL = "https://api.resend.com/emails"
CHART_CID = "price-chart"

# Light-surface palette; email clients are unreliable with dark mode CSS.
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#7a7974"
RULE = "#e4e3df"
SURFACE = "#ffffff"
PAGE = "#f4f3f0"
ACCENT = "#1c5cab"
HIGHLIGHT = "#eaf2fc"
DOWN = "#137a2c"
UP = "#b42318"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


@dataclass
class Email:
    subject: str
    html: str
    text: str
    attachments: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- formatting

def money(value: float | None) -> str:
    return "—" if value is None else f"£{value:,.0f}"


def change_text(change: float | None) -> str:
    if change is None:
        return "—"
    if abs(change) < 0.5:
        return "no change"
    arrow = "▼" if change < 0 else "▲"
    return f"{arrow} £{abs(change):,.0f}"


def change_html(change: float | None) -> str:
    text = escape(change_text(change))
    if change is None or abs(change) < 0.5:
        return f'<span style="color:{INK_3}">{text}</span>'
    color = DOWN if change < 0 else UP
    return f'<span style="color:{color};font-weight:600">{text}</span>'


def _time(local_iso: str) -> str:
    try:
        return dt.datetime.fromisoformat(local_iso).strftime("%H:%M")
    except ValueError:
        return local_iso or "?"


def _day(local_iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(local_iso)
        return f"{d:%a} {d.day} {d:%b}"
    except ValueError:
        return ""


def _arrival(depart_iso: str, arrive_iso: str) -> str:
    """Arrival time, with +N when it lands on a later day than it left."""
    try:
        days = (dt.date.fromisoformat(arrive_iso[:10]) - dt.date.fromisoformat(depart_iso[:10])).days
    except ValueError:
        days = 0
    return _time(arrive_iso) + (f" (+{days})" if days > 0 else "")


def itinerary_lines(opt: FlightOption) -> tuple[str, str]:
    out = (f"Out {_day(opt.out_depart)}: {opt.out_flights} "
           f"dep {_time(opt.out_depart)} → arr {_arrival(opt.out_depart, opt.out_arrive)}")
    back = (f"Back {_day(opt.in_depart)}: {opt.in_flights} "
            f"dep {_time(opt.in_depart)} → arr {_arrival(opt.in_depart, opt.in_arrive)}")
    return out, back


def _button(url: str | None, label: str = "Book this trip") -> str:
    if not url:
        return f'<span style="color:{INK_3};font-size:13px">No booking link returned</span>'
    return (f'<a href="{escape(url)}" style="display:inline-block;background:{ACCENT};color:#ffffff;'
            f'text-decoration:none;font-weight:600;font-size:14px;padding:10px 18px;border-radius:6px">'
            f'{escape(label)}</a>')


def _shell(cfg: Config, title: str, body: str, footer: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{PAGE};font-family:{FONT};color:{INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE}">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:640px;background:{SURFACE};border-radius:10px;border:1px solid {RULE}">
<tr><td style="padding:24px 24px 8px">
  <div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{INK_2}">
    {escape(cfg.origin)} → {escape(cfg.destination)} · {escape(cfg.passenger_summary)} · {escape(cfg.cabin_class)}
  </div>
</td></tr>
{body}
<tr><td style="padding:16px 24px 24px;border-top:1px solid {RULE};font-size:12px;line-height:1.5;color:{INK_3}">
{footer}
</td></tr>
</table></td></tr></table></body></html>"""


# ---------------------------------------------------------------- digest

def render_digest(cfg: Config, statuses: list[ComboStatus], *, run_at: dt.datetime,
                  slot: str, reasons: list[str], chart_png: bytes | None) -> Email:
    best = best_nonstop(statuses)
    assert best is not None and best.result.nonstop is not None
    opt = best.result.nonstop
    label = combo_label(best.result.depart, best.result.ret)
    local = run_at.astimezone(ZoneInfo(cfg.timezone))

    tag = "PRICE DROP" if reasons else ("Daily digest" if slot == "morning" else "Update")
    subject = f"{tag}: {cfg.origin}→{cfg.destination} nonstop from {money(opt.price)} ({label})"

    connecting = [
        s for s in statuses
        if connecting_worth_listing(s.result.nonstop, s.result.overall, cfg.connecting_min_saving)
    ]
    errors = [(s.result, e) for s in statuses for e in s.result.errors]

    # ---- HTML
    out_line, back_line = itinerary_lines(opt)
    alert_html = ""
    if reasons:
        items = "".join(f"<li>{escape(r)}</li>" for r in reasons)
        alert_html = f"""<tr><td style="padding:8px 24px 0">
  <div style="border-left:4px solid {DOWN};background:#eef7f0;padding:10px 14px;border-radius:4px;font-size:14px">
    <strong>Price drop</strong><ul style="margin:6px 0 0;padding-left:18px">{items}</ul></div>
</td></tr>"""

    hero = f"""<tr><td style="padding:8px 24px 20px">
  <div style="font-size:14px;color:{INK_2}">Best nonstop round trip right now</div>
  <div style="font-size:34px;font-weight:700;line-height:1.2;margin:4px 0 2px">{money(opt.price)}</div>
  <div style="font-size:16px;font-weight:600">{escape(label)} 2027</div>
  <div style="font-size:14px;color:{INK_2};margin:6px 0 14px;line-height:1.5">
    {escape(opt.airline)}<br>{escape(out_line)}<br>{escape(back_line)}</div>
  {_button(opt.booking_url)}
</td></tr>"""

    rows = []
    for s in statuses:
        is_best = s is best
        bg = f"background:{HIGHLIGHT};" if is_best else ""
        edge = f"border-left:4px solid {ACCENT};" if is_best else "border-left:4px solid transparent;"
        badge = (f' <span style="font-size:11px;font-weight:700;color:{ACCENT};'
                 f'text-transform:uppercase;letter-spacing:.04em">Cheapest</span>') if is_best else ""
        flights = ""
        if s.result.nonstop:
            n = s.result.nonstop
            flights = f'<div style="font-size:12px;color:{INK_3}">{escape(n.out_flights)} / {escape(n.in_flights)}</div>'
        new_low = (f' <span style="font-size:11px;color:{DOWN};font-weight:700">NEW LOW</span>'
                   if s.is_new_low else "")
        td = f"padding:10px 8px;border-top:1px solid {RULE};font-size:14px;{bg}"
        rows.append(f"""<tr>
  <td style="{td}{edge}">{escape(combo_label(s.result.depart, s.result.ret))}{badge}{flights}</td>
  <td style="{td}text-align:right;font-weight:600;white-space:nowrap">{money(s.current) if s.current is not None else '<span style="color:' + UP + '">none found</span>'}</td>
  <td style="{td}text-align:right;white-space:nowrap">{change_html(s.change_since_last)}</td>
  <td style="{td}text-align:right;white-space:nowrap">{change_html(s.change_since_start)}</td>
  <td style="{td}text-align:right;white-space:nowrap">{money(s.all_time_low)}{new_low}</td>
</tr>""")
    th = f"padding:6px 8px;font-size:11px;font-weight:600;color:{INK_2};text-transform:uppercase;letter-spacing:.04em"
    table = f"""<tr><td style="padding:0 16px 20px">
  <div style="font-size:16px;font-weight:700;padding:0 8px 8px">All dates · nonstop prices</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
    <tr><th align="left" style="{th};padding-left:12px">Dates</th><th align="right" style="{th}">Now</th>
        <th align="right" style="{th}">Since last</th><th align="right" style="{th}">Since start</th>
        <th align="right" style="{th}">All-time low</th></tr>
    {''.join(rows)}
  </table>
</td></tr>"""

    connecting_html = ""
    if connecting:
        blocks = []
        for s in connecting:
            o = s.result.overall
            saving = s.result.nonstop.price - o.price
            ol, bl = itinerary_lines(o)
            blocks.append(f"""<div style="padding:10px 0;border-top:1px solid {RULE};font-size:14px;line-height:1.5">
  <strong>{escape(combo_label(s.result.depart, s.result.ret))}: {money(o.price)}</strong>
  <span style="color:{DOWN};font-weight:600">({money(saving)} less than nonstop)</span><br>
  <span style="color:{INK_2}">{escape(o.airline)} · {escape(o.stops_label)}{' · self-transfer' if o.self_transfer else ''}<br>
  {escape(ol)}<br>{escape(bl)}</span><br>
  {f'<a href="{escape(o.booking_url)}" style="color:{ACCENT}">Booking link</a>' if o.booking_url else ''}
</div>""")
        connecting_html = f"""<tr><td style="padding:0 24px 20px">
  <div style="font-size:16px;font-weight:700;padding-bottom:4px">Connecting options worth a look</div>
  <div style="font-size:13px;color:{INK_2};padding-bottom:6px">Shown only when at least {money(cfg.connecting_min_saving)} cheaper than the nonstop for the same dates.</div>
  {''.join(blocks)}
</td></tr>"""

    chart_html = ""
    attachments = []
    if chart_png:
        chart_html = f"""<tr><td style="padding:0 24px 20px">
  <div style="font-size:16px;font-weight:700;padding-bottom:8px">Cheapest nonstop over time</div>
  <img src="cid:{CHART_CID}" width="560" alt="Line chart of the cheapest nonstop price at each check"
       style="width:100%;max-width:560px;height:auto;display:block;border:0">
</td></tr>"""
        attachments.append({
            "filename": "price-chart.png",
            "content": base64.b64encode(chart_png).decode(),
            "content_id": CHART_CID,
            "content_type": "image/png",
        })

    footer_bits = [
        f"Checked {local:%a %d %b %Y, %H:%M} UK time ({slot} run). "
        f"Prices are as quoted by Ignav for {escape(cfg.passenger_summary)}, {escape(cfg.cabin_class)}, in {escape(cfg.currency)}. "
        "Fares change constantly; confirm the price on the booking page."
    ]
    if errors:
        err_items = "".join(
            f"<li>{escape(combo_label(r.depart, r.ret))}: {escape(e)}</li>" for r, e in errors)
        footer_bits.append(f'Some searches had problems:<ul style="margin:4px 0;padding-left:18px">{err_items}</ul>')
    html = _shell(cfg, subject, alert_html + hero + table + connecting_html + chart_html,
                  "<br>".join(footer_bits))

    # ---- plain text
    lines = []
    if reasons:
        lines += ["PRICE DROP", *[f"  - {r}" for r in reasons], ""]
    lines += [
        f"{cfg.origin} -> {cfg.destination} | {cfg.passenger_summary} | {cfg.cabin_class}",
        "",
        f"BEST NONSTOP RIGHT NOW: {money(opt.price)}  {label} 2027",
        f"  {opt.airline}",
        f"  {out_line}",
        f"  {back_line}",
        f"  Book: {opt.booking_url or 'no booking link returned'}",
        "",
        "ALL DATES (nonstop)",
        f"  {'Dates':<24}{'Now':>9}{'Since last':>13}{'Since start':>13}{'All-time low':>15}",
    ]
    for s in statuses:
        mark = " *" if s is best else ""
        low = money(s.all_time_low) + (" NEW" if s.is_new_low else "")
        lines.append(
            f"  {combo_label(s.result.depart, s.result.ret):<24}"
            f"{money(s.current) if s.current is not None else 'none':>9}"
            f"{change_text(s.change_since_last):>13}{change_text(s.change_since_start):>13}"
            f"{low:>15}{mark}"
        )
    lines.append("  (* = cheapest)")
    if connecting:
        lines += ["", f"CONNECTING OPTIONS (at least {money(cfg.connecting_min_saving)} cheaper than nonstop)"]
        for s in connecting:
            o = s.result.overall
            ol, bl = itinerary_lines(o)
            lines += [
                f"  {combo_label(s.result.depart, s.result.ret)}: {money(o.price)} "
                f"({money(s.result.nonstop.price - o.price)} less), {o.airline}, {o.stops_label}",
                f"    {ol}", f"    {bl}", f"    Book: {o.booking_url or 'n/a'}",
            ]
    lines += ["", f"Checked {local:%a %d %b %Y, %H:%M} UK time ({slot} run)."]
    if errors:
        lines += ["Some searches had problems:"] + [
            f"  - {combo_label(r.depart, r.ret)}: {e}" for r, e in errors]

    return Email(subject=subject, html=html, text="\n".join(lines), attachments=attachments)


# ---------------------------------------------------------------- problem

def render_problem(cfg: Config, results: list[ComboResult], *, run_at: dt.datetime,
                   slot: str) -> Email:
    local = run_at.astimezone(ZoneInfo(cfg.timezone))
    subject = f"Flight tracker problem: no nonstop prices for {cfg.origin}→{cfg.destination}"
    details = []
    for r in results:
        msg = "; ".join(r.errors) or "searches succeeded but returned no nonstop round trips"
        details.append((combo_label(r.depart, r.ret), msg))

    summary = (f"The {slot} check at {local:%H:%M} UK time on {local:%a %d %b} got no nonstop "
               "prices for any of the date combinations, so there is no digest this time.")
    hint = ("If every line says HTTP 401 or 403, check the IGNAV_API_KEY secret. "
            "402 means the Ignav account needs credit. Other errors are usually temporary; "
            "the next scheduled run will try again.")
    items = "".join(f"<li><strong>{escape(d)}</strong>: {escape(m)}</li>" for d, m in details)
    body = f"""<tr><td style="padding:8px 24px 20px;font-size:14px;line-height:1.55">
  <div style="font-size:20px;font-weight:700;margin-bottom:8px">Tracker problem</div>
  <p style="margin:0 0 10px">{escape(summary)}</p>
  <ul style="margin:0 0 10px;padding-left:18px">{items}</ul>
  <p style="margin:0;color:{INK_2}">{escape(hint)}</p>
</td></tr>"""
    html = _shell(cfg, subject, body, "Sent by the flight price tracker GitHub Action.")
    text = "\n".join(["TRACKER PROBLEM", "", summary, ""]
                     + [f"  - {d}: {m}" for d, m in details] + ["", hint])
    return Email(subject=subject, html=html, text=text)


# ---------------------------------------------------------------- sending

def send_email(cfg: Config, email: Email, *, api_key: str, to: str,
               session: requests.Session | None = None) -> str:
    """Send via Resend. Returns the Resend message id."""
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set")
    if not to:
        raise RuntimeError("ALERT_EMAIL is not set")
    payload = {
        "from": cfg.email_from,
        "to": [addr.strip() for addr in to.split(",") if addr.strip()],
        "subject": email.subject,
        "html": email.html,
        "text": email.text,
    }
    if email.attachments:
        payload["attachments"] = email.attachments
    resp = request_with_retry(
        session or requests.Session(), "POST", RESEND_URL,
        json=payload, headers={"Authorization": f"Bearer {api_key}"},
        max_attempts=cfg.api_max_attempts, backoff_base=cfg.api_backoff_base, timeout=30,
    )
    return resp.json().get("id", "")
