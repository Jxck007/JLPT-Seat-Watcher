# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- YAML configuration with simultaneous N5, N4, N3, N2, and N1 monitoring.
- Auto, Forenoon, Afternoon, and Both session selection without fixed placement.
- Per-level/session state and alert deduplication from one website fetch per cycle.
- Complete level, session, count, website, and timestamp notification payloads.
- Self-registering Notifier base with ntfy, Telegram, Discord webhook, Slack
  webhook, and SMTP email providers.
- Bounded 30-day execution history with JSON, CSV, and daily statistics exports.
- Secret-free Pages publishing and responsive Chart.js history visualizations.
- Generic `MonitorEngine` and four-method website adapter contract.
- Default JLPT Chennai adapter with automatic adapter discovery.

### Changed

- Existing environment settings now override their matching `config.yaml` keys.
- Notification provider selection now comes from `notification_provider` while
  ntfy remains the backward-compatible default.
- Legacy N4 state and singular parser, scraper, result, and CLI output contracts
  remain supported.
- The canonical internal package is now `watchtower`; all previous
  `jlpt_seat_watcher` imports, module execution, and console commands remain
  compatible.

## [1.0.0] - 2026-08-05

### Added

- Static-first JLPT N4 scraper with automatic Playwright fallback.
- Persistent alert cadence, state comparison, metrics, heartbeats, and daily summaries.
- ntfy priority support, retries, CLI operations, structured logs, and diagnostics.
- Automated tests, Docker deployment, GitHub Actions monitoring, and CI quality gates.
