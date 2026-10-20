# Troubleshooting and FAQ

## No notification arrived

Run `python notify_test.py` and confirm `notification_provider` selects the
intended provider. For ntfy, verify `NTFY_TOPIC` and optional `NTFY_TOKEN`. For
Telegram, verify the bot token, chat ID, and that the bot can message the chat.
For Discord or Slack, verify the incoming webhook is active. For email, verify
the SMTP host, sender, recipients, TLS mode, and credentials. Errors
intentionally omit topics, tokens, passwords, and webhook URLs.

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

Yes. Add any unique combination of N5, N4, N3, N2, and N1 under
`watched_levels` in `config.yaml`. Session placement is not fixed by level.
Choose `session: Auto` to detect placement, a named session to filter it, or
`session: Both` to monitor matches in both sections. `WATCHED_LEVELS=N4,N2` and
`WATCHED_SESSION=Both` environment overrides are also supported.

## Why does Auto reject a level found in both sessions?

Auto intentionally requires one unambiguous session per selected level. Use
`session: Both` when the same level should be monitored independently in
Forenoon and Afternoon.

## Does it register automatically?

No. It reads the public home page and links the notification to the official
website. Registration, authentication, payment, and form submission remain
manual.

## Can one run send several seat-status notifications?

Normally no. The engine selects one notification using MAX, HIGH, DEFAULT, then
MIN precedence. Failed deliveries do not advance their successful timestamp, so
the selected notification remains eligible for retry.
