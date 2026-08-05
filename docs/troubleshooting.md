# Troubleshooting and FAQ

## No notification arrived

Run `python notify_test.py`. Confirm `NTFY_TOPIC` has no surrounding whitespace,
the client is subscribed to the same topic, and the device allows ntfy
notifications. For a protected server, verify `NTFY_SERVER` and `NTFY_TOKEN`.
Errors intentionally omit the topic and token.

## Playwright says Chromium is missing

Run the browser installation from the active virtual environment:

```bash
playwright install --with-deps chromium
```

Docker already includes Chromium. GitHub Actions installs and caches it.

## The health check is unhealthy

Run `python status.py`, inspect `logs/monitor.jsonl`, and check
`logs/snapshots/`. Health becomes stale after the greater of 15 minutes or three
configured check intervals. A brand-new installation remains unhealthy until
its first successful monitored check.

## A `state.corrupt-*` file appeared

The state document was invalid or interrupted outside the application's atomic
writer. The monitor preserved it for analysis and safely started a new state.
Check storage health and ensure no external program edits `data/state.json`.

## Why did the parser stop instead of estimating remaining seats?

Incorrect availability is worse than a missed cycle. The parser never infers a
count from incomplete or contradictory data and invokes the browser fallback
before giving up.

## Why are GitHub checks late?

Scheduled Actions are queued on a best-effort basis. Their five-minute cron is
not a timing guarantee. Deploy continuous mode to a VM or container for more
predictable urgent repeats.

## Can I monitor another level?

This release deliberately fixes the target to N4 and validates its Afternoon
placement. Changing levels requires corresponding parser fixtures, alert copy,
and acceptance tests; an environment toggle could accidentally monitor the wrong
exam.

## Does it register automatically?

No. It reads the public home page and links the notification to the official
website. Registration, authentication, payment, and form submission remain
manual.

## Are heartbeats duplicated with urgent alerts?

Heartbeat and availability clocks are independent. Both can be due during one
cycle because they communicate different facts: operational liveness and seat
availability. Each type is deduplicated against its own persisted timestamp.

