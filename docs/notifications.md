# Notification examples

The same alert content is delivered through the provider selected by
`notification_provider` in `config.yaml`. ntfy retains its original headers,
priority mapping, click URL, tags, authentication, and retry behavior. Telegram,
Discord, and Slack format the title and body for their APIs. Email uses the title
as its subject and includes the website in the plain-text body.

## Provider configuration

| Provider | YAML value | Credential environment variables |
|---|---|---|
| ntfy | `ntfy` | `NTFY_TOPIC`, optional `NTFY_TOKEN` |
| Telegram Bot API | `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Discord webhook | `discord` | `DISCORD_WEBHOOK_URL` |
| Slack incoming webhook | `slack` | `SLACK_WEBHOOK_URL` |
| SMTP email | `email` | optional `SMTP_USERNAME`, `SMTP_PASSWORD` |

SMTP host, port, sender, recipients, and TLS mode are configured in
`config.yaml`. Secrets and webhook URLs must remain in `.env` or deployment
secrets.

## Every successful 15-minute check

**Title:** JLPT N4 Check
**Priority:** 1 / min

```text
Remaining: 0
Applied: 850 / 850
Checked: 12:15 PM
```

## Hourly replacement

**Title:** JLPT N4 — Still Monitoring
**Priority:** 3 / default

```text
Remaining: 0
Applied: 850 / 850
Monitor: Healthy
Checked: 1:00 PM
```

The hourly notification replaces the normal MIN notification for that run.

## Seat availability

**Title:** 🚨 JLPT N4 SEATS AVAILABLE
**Priority:** 4 / high

```text
Remaining: 3
Applied: 847 / 850

REGISTER NOW
```

This is sent immediately when remaining seats become positive, whenever that
positive count changes. It replaces the lower-priority notification for that
run.

## Six-hour availability escalation

**Title:** 🚨🚨 JLPT N4 — SEATS STILL AVAILABLE
**Priority:** 5 / max

```text
Remaining: 3

Seats have remained available for 6 hours.
Register immediately.
```

MAX repeats at most once every six hours while availability remains continuously
positive. Returning to zero resets the timer. The selection order is MAX, HIGH,
DEFAULT, then MIN, so only one seat-status notification is sent per run.

## Manual test

Manual tests are always labelled and never alter monitor state:

```bash
python -m watchtower notify-test --priority silent
python -m watchtower notify-test --priority normal
python -m watchtower notify-test --priority high
python -m watchtower notify-test --priority emergency
```
