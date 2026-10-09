# Flight price tracker: LHR → ATL, August 2027

Checks round-trip economy fares for 3 adults + 1 child twice a day and emails you about them.

- **Dates:** every combination of outbound 16, 17 or 18 Aug 2027 and return 31 Aug or 1 Sep 2027 (6 round trips).
- **What it records:** for each date pair, the cheapest option where both legs are nonstop, and the cheapest option with any number of stops. It stores the airline, flight numbers, local departure/arrival times and a booking link for each.
- **Where it stores data:** every result goes into `data/prices.db` (SQLite) with a UTC timestamp. The GitHub workflow commits the file back to the repo after each run.
- **Emails, sent through Resend:**
  - **07:00 UK:** always sends a digest: the best nonstop deal, a table of all 6 date pairs, and a price chart once there are 3+ days of data.
  - **19:00 UK:** emails only if a nonstop price fell by £25+ since the last run, or hit a new all-time low. The subject starts with `PRICE DROP`.
  - **Any run with no nonstop price for any date pair** (bad key, Ignav down, etc.): sends a short "Flight tracker problem" email, and the Actions run shows as failed.
  - **Connecting flights:** listed only when they're at least £150 cheaper than the nonstop for the same dates.

Flight data comes from the [Ignav API](https://ignav.com/docs).

## Setup

### 1. Get API keys

| Secret | Where to get it |
|---|---|
| `IGNAV_API_KEY` | [ignav.com](https://ignav.com): sign up and create an API key. The first 1,000 requests are free, then $2 per 1,000. |
| `RESEND_API_KEY` | [resend.com](https://resend.com) → API Keys. |
| `ALERT_EMAIL` | The address that receives the emails. Separate several with commas. |

> **Resend's test sender:** with the default `onboarding@resend.dev` sender, Resend only delivers
> to the email address you signed up to Resend with. To send anywhere else, verify a domain
> in Resend and change `email.from` in `config.yaml`.

### 2. Add them as GitHub secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add all three.
Alternatively, use the `gh` CLI:

```bash
gh secret set IGNAV_API_KEY
gh secret set RESEND_API_KEY
gh secret set ALERT_EMAIL
```

### 3. Let the workflow push

Go to **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**.
The workflow needs this to commit `data/prices.db`.

### 4. Do a test run

Go to **Actions → Flight price tracker → Run workflow**. Tick **force_email** to get a digest
straight away, whatever time it is.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Real API, prints the email instead of sending it, writes nothing to the database
export IGNAV_API_KEY=...
python -m tracker --dry-run --slot morning

# No API key needed: fake data, to check the email layout
python -m tracker --mock --dry-run --slot morning --preview-dir preview/
# then open preview/email.html in a browser

# Send a real email now, regardless of the alert rules
export RESEND_API_KEY=... ALERT_EMAIL=you@example.com
python -m tracker --force-email

# Tests
pytest
```

| Flag | What it does |
|---|---|
| `--dry-run` | Prints the subject, plain text and HTML instead of sending. Doesn't write to the database unless you add `--save`. |
| `--force-email` | Sends the digest even when the evening rules say not to. |
| `--slot morning\|evening\|auto` | Picks which rules to apply. `auto` (the default) means morning before 13:00 UK time, evening after. |
| `--mock` | Uses fake, Ignav-shaped data instead of the API. |
| `--db PATH` | Uses a different SQLite file. |
| `--preview-dir DIR` | With `--dry-run`, also writes `email.html`, `email.txt` and `chart.png` to DIR. |

## Changing the trip or the rules

Edit `config.yaml`, where you can change:

- airports, dates and passengers
- the £25 evening drop threshold
- the £150 connecting-flight margin
- how many days of data the chart needs
- the UK run hours

The six date pairs are every outbound date crossed with every return date, so adding dates adds searches.

Each run makes 12 searches (a nonstop-only search and an any-stops search per date pair), plus up to 12 booking-link lookups. That's at most about 1,450 requests a month at two runs a day: roughly $1 a month after the free 1,000.

## How the UK-time schedule works

GitHub's cron runs in UTC, and the UK switches between GMT (UTC+0) and BST (UTC+1). So the workflow fires at
06:00, 07:00, 18:00 and 19:00 UTC. Each run checks which UK time its trigger was *scheduled*
for, and only the one that lands on 07:00 or 19:00 UK time does any work. The other exits in a
few seconds. Basing this on the scheduled time rather than the actual start time keeps it correct
even when GitHub starts a run late, which often happens by 5–30 minutes.

## Stopping the tracker after you've booked

Pick one:

- **Pause it (recommended):** go to **Actions → Flight price tracker → ⋯ → Disable workflow**, or
  run `gh workflow disable "Flight price tracker"`. Your price history stays in `data/prices.db`, and you can turn the tracker back on the same way.
- **Remove it:** delete `.github/workflows/track.yml` and commit.

Afterwards you can also revoke the Ignav and Resend API keys and delete the repo secrets.

## Things to know

- **Price totals:** Ignav's docs don't say whether `price.amount` is the total for all travellers or per person.
  The tracker shows the number exactly as Ignav returns it. Compare the first real email against the booking page
  to confirm which it is.
- **Live fares:** prices change constantly. A link may show a different price or fare class, so check the bags and the price before paying.
- **Stops:** "nonstop" means both legs have a single flight segment. The tracker filters on segment counts itself rather than relying only on the API's `max_stops` filter.
- **Inactivity:** GitHub disables scheduled workflows after 60 days with no repo activity. The tracker commits
  `data/prices.db` after each run, so it keeps the repo active.

## Layout

```
config.yaml          trip, thresholds, schedule
tracker/main.py      CLI and run flow
tracker/ignav.py     Ignav client and per-date-pair search
tracker/selection.py parse itineraries, pick cheapest nonstop/overall, pick booking link
tracker/analysis.py  price comparisons and alert rules (pure functions)
tracker/schedule.py  UTC cron → UK slot mapping
tracker/storage.py   SQLite
tracker/emailer.py   HTML/text emails and sending through Resend
tracker/chart.py     matplotlib price chart
tracker/http.py      retries with exponential backoff
tracker/mock.py      fake API for --mock
tests/               unit tests
```
