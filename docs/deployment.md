# Deployment guide

All deployment modes need a persistent writable `data` directory. Persisting
`logs` is strongly recommended for diagnostics. Only one scheduling mechanism
should target a given state file.

## Local daemon

Follow the README quick start and run:

```bash
nohup .venv/bin/python main.py >> logs/daemon.log 2>&1 &
```

For a supervised service, prefer systemd rather than `nohup`.

## Linux cron

Install the application under `/opt/JLPT-Seat-Watcher`, configure `.env`, and
copy the line from `config/jlpt-seat-watcher.cron` into `crontab -e`. The process
lock makes a delayed prior run safe, but cron should not be combined with daemon
mode.

## systemd and Oracle Cloud VM

Create an unprivileged account and install the service:

```bash
sudo useradd --system --home /opt/JLPT-Seat-Watcher --shell /usr/sbin/nologin jlpt-watcher
sudo chown -R jlpt-watcher:jlpt-watcher /opt/JLPT-Seat-Watcher
sudo cp config/jlpt-seat-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jlpt-seat-watcher
sudo systemctl status jlpt-seat-watcher
```

Outbound HTTPS access to the JLPT site and ntfy server is sufficient; no inbound
port is required. The bundled service hardens the process and grants writes only
to `data` and `logs`.

## Docker and Docker Compose

```bash
cp .env.example .env
# Set NTFY_TOPIC in .env.
docker compose up --build -d
docker compose logs -f watcher
docker compose exec watcher python status.py
```

Named volumes preserve state and logs across container replacement. The image
runs as UID 10001 and includes the Playwright Chromium runtime.

## GitHub Actions

1. Add the `NTFY_TOPIC` Actions secret.
2. Optionally add `NTFY_TOKEN` and the `NTFY_SERVER` repository variable.
3. Open **Actions → Monitor JLPT N4 seats → Run workflow**.
4. Select `force_scraper_test` first, then run `force_notification_test`.
5. Confirm the ntfy message and execution summary.

Without a topic, scheduled runs perform a scraper validation and report a warning
instead of failing or mutating alert state. State caches are automatically
created once normal monitoring is enabled.

## Railway

Create a service from the repository using the Dockerfile, set the required
environment variables, and use `python main.py` as the worker command. Attach a
persistent volume mounted at `/app/data`; mount a second at `/app/logs` when log
retention is required. This is a background worker and does not expose a port.

## Render

Create a **Background Worker** from the repository, choose Docker runtime, add
the environment variables, and attach a persistent disk at `/app/data`. Use
`python main.py` as the start command. Free instances that sleep are unsuitable
for continuous seat monitoring.

## Updating

Stop the active scheduler, pull/build the new version, run the tests or scraper
test, and restart. Keep `data/state.json` and `.env`; schema-incompatible state is
preserved automatically rather than overwritten.

