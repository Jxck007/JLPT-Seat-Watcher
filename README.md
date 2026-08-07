# JLPT N4 Seat Monitor

A small GitHub-hosted monitor for the JLPT Chennai N4 Afternoon session. It checks the public seat counter every 15 minutes, stores state between GitHub Actions runs, and publishes a read-only dashboard at [jxck007.github.io/JLPT-Seat-Watcher](https://jxck007.github.io/JLPT-Seat-Watcher/).

The monitor does not log in, register candidates, submit forms, or expose notification credentials.

## Notification schedule

| Condition | ntfy priority | Behaviour |
|---|---:|---|
| Ordinary 15-minute check | none | State and dashboard update only |
| Seats remain full | 2 (low) | One quiet heartbeat every hour |
| Remaining changes to a positive value | 4 (high) | Immediate seat alert |
| Positive remaining value changes | 4 (high) | Immediate updated seat alert |
| Seats remain available | 4 (high) | Optional repeat after 15 minutes |

Successful heartbeat and seat-alert timestamps are written to `data/state.json`. A failed notification is recorded but remains eligible for retry. The monitor workflow uses concurrency protection and restores the latest run-specific state cache before each check.

## GitHub configuration

Add these repository settings under **Settings > Secrets and variables > Actions**:

- Secret `NTFY_TOPIC` (required)
- Secret `NTFY_TOKEN` (optional)
- Variable `NTFY_SERVER` (optional, defaults to `https://ntfy.sh`)
- Variable `TIMEZONE` (optional, defaults to `Asia/Kolkata`)

Configure GitHub Pages under **Settings > Pages**:

1. Select **Deploy from a branch**.
2. Select branch **main**.
3. Select folder **/docs**.
4. Save the setting.

No custom Pages deployment workflow is required. The monitor workflow commits safe dashboard JSON files into `docs/`, and GitHub Pages publishes that directory from `main`.

## Public dashboard data

Each monitor run refreshes:

- `docs/status.json`
- `docs/health.json`
- `docs/metrics.json`
- `docs/history.json`
- `docs/history.csv`

The dashboard reads the four JSON files every 60 seconds. It does not use the GitHub API and never publishes `NTFY_TOPIC`, `NTFY_TOKEN`, GitHub tokens, or request headers.

## Configuration

The checked target and timing are defined in `config.yaml`:

```yaml
watched_levels:
  - N4
session: Afternoon
timezone: Asia/Kolkata
check_interval: 900
heartbeat_interval: 3600
repeat_available_alerts: true
available_alert_interval: 900
quiet_heartbeat: true
enable_daily_summary: false
```

The scraper uses `requests` and BeautifulSoup first. Playwright is only the rendered-page fallback. GitHub Actions restores its browser cache and installs Chromium only when that cache is missing.

## Local validation

```bash
python -m pip install -r requirements-dev.txt
black --check .
isort --check-only .
ruff check .
mypy src
pytest
docker build -t jlpt-seat-watcher .
```

Unit tests use saved fixtures rather than the live JLPT website. The scheduled workflow runs on GitHub-hosted runners and continues when the repository owner's computer is turned off.

## Manual checks

The monitor workflow supports manual scraper and notification tests. The notification test can send either:

- `low`, mapped to ntfy priority 2
- `high`, mapped to ntfy priority 4

Phone sound, vibration, and heads-up behaviour depends on the ntfy Android app and channel settings. Code-level priority can be verified automatically, but device behaviour must be confirmed by the phone owner.

## License

[MIT](LICENSE)
