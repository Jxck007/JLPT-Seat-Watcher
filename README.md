# JLPT Seat Watcher

[![CI](https://github.com/Jxck007/JLPT-Seat-Watcher/actions/workflows/ci.yml/badge.svg)](https://github.com/Jxck007/JLPT-Seat-Watcher/actions/workflows/ci.yml)
[![Monitor](https://github.com/Jxck007/JLPT-Seat-Watcher/actions/workflows/monitor.yml/badge.svg)](https://github.com/Jxck007/JLPT-Seat-Watcher/actions/workflows/monitor.yml)

JLPT Seat Watcher monitors the public examination table at
[jlptchennaiindia.com](https://www.jlptchennaiindia.com/) and sends an immediate
high-priority [ntfy](https://ntfy.sh/) notification when N4 seats become
available. It does not log in, submit forms, or interact with registration.

The monitor is designed for unattended operation over several months. It uses
lightweight static requests normally and launches Chromium only when the page
cannot be retrieved or safely parsed without JavaScript.

![CLI status showing a successful N4 check](docs/images/status-command.png)

## What it does

- Checks N4 `Total`, `Applied`, and `Remaining` counters every five minutes.
- Validates that counters are unique, non-negative, under the Afternoon session,
  and satisfy `Total = Applied + Remaining`.
- Retries transient failures with rotating user agents and exponential backoff.
- Falls back automatically to Playwright and captures diagnostic HTML/screenshots.
- Sends hourly silent heartbeats, urgent ten-minute repeats while seats remain,
  and a daily operational summary.
- Stores state atomically so restarts do not reset alert cadence.
- Runs as a local daemon, one-shot cron task, container, cloud worker, or GitHub
  Actions schedule.

## Quick start

Python 3.12 or newer and a free ntfy topic are required.

```bash
git clone https://github.com/Jxck007/JLPT-Seat-Watcher.git
cd JLPT-Seat-Watcher
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env
```

Set a hard-to-guess topic in `.env`:

```dotenv
NTFY_TOPIC=my-private-random-topic-name
```

Subscribe to that topic in the ntfy mobile app or web client, then test it:

```bash
python notify_test.py
python monitor.py
python status.py
python main.py
```

`main.py` runs continuously. `monitor.py` performs exactly one cycle and is the
right entrypoint for cron and GitHub Actions.

## Alert behavior

| Situation | ntfy priority | Behavior |
|---|---:|---|
| First successful run / hourly | 1 (silent) | Monitor heartbeat with current count |
| Remaining becomes positive | 4 (high) | Immediate availability alert |
| Positive count changes | 4 (high) | Immediate updated availability alert |
| Seats remain positive | 4 (high) | Repeat no more than every 10 minutes |
| Daily after 20:00 local time | 3 (normal) | Checks, range, and latency summary |
| Remaining returns to zero | — | Urgent repeats stop automatically |

Notification timestamps are committed to `data/state.json` only after ntfy
accepts the message. A failed send therefore remains eligible on the next run.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NTFY_TOPIC` | empty | Topic slug or complete ntfy publish URL |
| `NTFY_SERVER` | `https://ntfy.sh` | Server for topic slugs |
| `NTFY_TOKEN` | empty | Optional access token for a protected server |
| `TIMEZONE` | `Asia/Kolkata` | IANA timezone for timestamps and summaries |
| `CHECK_INTERVAL` | `300` | Continuous-mode seconds between cycles |
| `HEARTBEAT_INTERVAL` | `3600` | Seconds between silent heartbeats |
| `URGENT_INTERVAL` | `600` | Repeat interval while seats remain |
| `LOG_LEVEL` | `INFO` | Console and JSON log threshold |
| `SCRAPER_TIMEOUT` | `30` | HTTP/browser timeout in seconds |
| `MAX_RETRIES` | `3` | HTTP and ntfy delivery attempts |
| `ENABLE_SCREENSHOT` | `true` | Capture browser failure screenshots |
| `ENABLE_PLAYWRIGHT` | `true` | Permit rendered fallback |
| `ENABLE_DAILY_SUMMARY` | `true` | Enable normal-priority daily report |
| `DAILY_SUMMARY_HOUR` | `20` | First local hour eligible for the report |
| `LOG_RETENTION_DAYS` | `30` | Runtime artifact retention |

The topic and token are redacted from errors and structured logs. Never commit
`.env`; it is ignored by Git.

## Operator commands

```bash
python -m jlpt_seat_watcher check
python -m jlpt_seat_watcher daemon
python -m jlpt_seat_watcher status
python -m jlpt_seat_watcher stats
python -m jlpt_seat_watcher health
python -m jlpt_seat_watcher scraper-test
python -m jlpt_seat_watcher parser-test [saved-page.html]
python -m jlpt_seat_watcher notify-test --priority emergency
python -m jlpt_seat_watcher export-state --output state-export.json
python -m jlpt_seat_watcher cleanup
```

The health command returns a nonzero status when state is absent/corrupt or the
last successful check is older than the greater of 15 minutes and three check
intervals.

## GitHub Actions

Add `NTFY_TOPIC` under **Settings → Secrets and variables → Actions → New
repository secret**. Add `NTFY_TOKEN` only for a protected ntfy server. Optional
repository variables can override `NTFY_SERVER` and `TIMEZONE`.

The monitor workflow runs every five minutes and serializes executions. Updated
state is stored in immutable, run-specific caches restored through a common
prefix. Manual dispatch can independently run a live scraper test or a labelled
notification test. Every execution writes a summary; failed runs upload logs,
HTML, screenshots, and state for 14 days.

GitHub schedules are best-effort and may start late during busy periods. A VM,
cron, or continuously running container is preferable when ten-minute urgent
repeat timing must be precise.

## Quality checks

```bash
python -m pip install -r requirements-dev.txt
black --check .
isort --check-only .
ruff check .
mypy src
pytest
docker build -t jlpt-seat-watcher .
```

Unit tests never depend on the live website. The manual `scraper-test` command
is the explicit live integration check.

## Documentation

- [Architecture and data flow](docs/architecture.md)
- [Deployment guide](docs/deployment.md)
- [Troubleshooting and FAQ](docs/troubleshooting.md)
- [Notification examples](docs/notifications.md)

## Responsible operation

The five-minute default produces at most one lightweight request per run. Do not
lower the interval below the validated 30-second minimum. The project is an
availability notifier, not an automated registration client; always complete
registration manually on the official website.

## License

[MIT](LICENSE)

