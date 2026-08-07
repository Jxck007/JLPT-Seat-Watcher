from pathlib import Path


def test_dashboard_is_small_read_only_and_refreshes_public_feeds() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")
    javascript = Path("docs/app.js").read_text(encoding="utf-8")

    for text in (
        "JLPT N4 Seat Monitor",
        "Afternoon Session",
        "Open JLPT Registration",
        "Refresh",
        "Auto refresh: 60 seconds",
    ):
        assert text in html
    for removed in (
        "Run Monitor",
        "Test Notification",
        "View Logs",
        "Architecture",
        "Deploy your own",
        "FAQ",
    ):
        assert removed not in html
    for filename in ("status.json", "health.json", "metrics.json", "history.json"):
        assert f'"{filename}"' in javascript
    assert "REFRESH_INTERVAL_MS = 60_000" in javascript
    assert "api.github.com" not in javascript


def test_dashboard_guards_missing_nested_and_invalid_values() -> None:
    javascript = Path("docs/app.js").read_text(encoding="utf-8")

    assert 'typeof value === "object"' in javascript
    assert "Number.isNaN" in javascript
    assert "Promise.allSettled" in javascript
    assert 'timeZone: "Asia/Kolkata"' in javascript
    assert '"Waiting for first successful check"' in javascript
    assert '"Not sent yet"' in javascript
    assert '"No seat alert yet"' in javascript
    assert '"Temporarily unavailable"' in javascript
    assert "textContent" in javascript
    assert "innerHTML" not in javascript


def test_mobile_layout_prevents_horizontal_overflow() -> None:
    css = Path("docs/styles.css").read_text(encoding="utf-8")

    assert "overflow-x: hidden" in css
    assert "@media (max-width: 720px)" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "min-width: 0" in css
