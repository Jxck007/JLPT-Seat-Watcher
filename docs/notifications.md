# Notification examples

## Seat availability

**Title:** 🚨 JLPT N4 SEATS AVAILABLE  
**Priority:** High

```text
Remaining: 3
Applied: 847
Total: 850
Website: https://www.jlptchennaiindia.com/
Checked: 2026-08-05T10:05:00+05:30
```

This is sent immediately when remaining seats become positive, whenever that
positive count changes, and at ten-minute intervals while it remains positive.

## Silent heartbeat

**Title:** ✅ JLPT Monitor Running  
**Priority:** Min/silent

```text
Remaining Seats: 0
Checked: 2026-08-05T11:00:00+05:30
```

## Daily summary

**Title:** JLPT Monitor Daily Summary  
**Priority:** Default/normal

```text
Checks today: 120
Remaining now: 0
Range: 0–0
Average website latency: 416 ms
Last successful check: 2026-08-05T20:00:00+05:30
```

## Manual test

Manual tests are always labelled and never alter monitor state:

```bash
python -m jlpt_seat_watcher notify-test --priority silent
python -m jlpt_seat_watcher notify-test --priority normal
python -m jlpt_seat_watcher notify-test --priority high
python -m jlpt_seat_watcher notify-test --priority emergency
```

