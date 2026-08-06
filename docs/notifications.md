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

## Seat availability

**Title:** JLPT N4 SEATS AVAILABLE
**Priority:** High

```text
Level: N4
Session: Afternoon
Remaining: 3
Applied: 847
Total: 850
Website: https://www.jlptchennaiindia.com/
Timestamp: 2026-08-05T10:05:00+05:30
```

This is sent immediately when remaining seats become positive, whenever that
positive count changes, and at ten-minute intervals while it remains positive.
Each watched level/session target has an independent persisted alert clock, so
processing multiple levels or Both mode does not create duplicate alerts.

## Silent heartbeat

**Title:** JLPT Monitor Running
**Priority:** Min/silent

```text
Level: N4
Session: Afternoon
Remaining: 0
Applied: 850
Total: 850
Website: https://www.jlptchennaiindia.com/
Timestamp: 2026-08-05T11:00:00+05:30
```

When several targets are watched, one heartbeat contains one complete block per
level/session pair.

## Daily summary

**Title:** JLPT Monitor Daily Summary  
**Priority:** Default/normal

```text
Checks today: 120
Average website latency: 416 ms

Level: N4
Session: Afternoon
Remaining: 0
Applied: 850
Total: 850
Website: https://www.jlptchennaiindia.com/
Timestamp: 2026-08-05T20:00:00+05:30
```

## Manual test

Manual tests are always labelled and never alter monitor state:

```bash
python -m watchtower notify-test --priority silent
python -m watchtower notify-test --priority normal
python -m watchtower notify-test --priority high
python -m watchtower notify-test --priority emergency
```
