from pathlib import Path

import yaml


def test_monitor_workflow_contract() -> None:
    path = Path(".github/workflows/monitor.yml")
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"][0]["cron"] == "*/5 * * * *"
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {"force_notification_test", "force_scraper_test"} <= set(inputs)
    assert "GITHUB_STEP_SUMMARY" in raw
    assert "actions/cache/restore" in raw
    assert "actions/cache/save" in raw
    assert "if: failure()" in raw
    assert workflow["permissions"]["contents"] == "write"
    assert "scripts/publish_dashboard.py" in raw
    assert "--max-checks 500" in raw
    assert "git push origin HEAD:main" in raw
    for filename in ("status.json", "history.json", "metrics.json", "health.json"):
        assert f"docs/{filename}" in raw


def test_ci_workflow_has_all_quality_gates() -> None:
    raw = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    for command in (
        "black --check",
        "isort --check-only",
        "ruff check",
        "mypy",
        "pytest",
    ):
        assert command in raw


def test_manual_operations_workflow_contract() -> None:
    path = Path(".github/workflows/manual-tools.yml")
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)

    expected_inputs = {
        "test_notification",
        "test_scraper",
        "test_parser",
        "print_current_seats",
        "health_check",
        "export_logs",
        "export_state",
    }
    dispatch = workflow["on"]["workflow_dispatch"]
    assert set(dispatch["inputs"]) == expected_inputs
    assert all(item["type"] == "boolean" for item in dispatch["inputs"].values())
    assert "schedule" not in workflow["on"]

    for command in (
        "notify-test",
        "scraper-test",
        "parser-test",
        "watchtower status",
        "watchtower health",
        "export-state",
        "gh api",
    ):
        assert command in raw

    assert "GITHUB_STEP_SUMMARY" in raw
    assert "actions/cache/restore@v5" in raw
    assert raw.count("actions/upload-artifact@v7") == 2


def test_pages_workflow_deploys_committed_dashboard_without_a_schedule() -> None:
    path = Path(".github/workflows/pages.yml")
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_run", "workflow_dispatch"}
    assert workflow["on"]["workflow_run"]["workflows"] == ["Monitor JLPT N4 seats"]
    assert "actions/cache/restore" not in raw
    assert "export-dashboard" not in raw
    assert "actions/upload-pages-artifact@v5" in raw
    assert "actions/deploy-pages@v5" in raw


def test_dashboard_assets_include_history_charts_and_downloads() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")
    javascript = Path("docs/app.js").read_text(encoding="utf-8")
    assert "chart.js@4.5.1" in html
    assert 'id="remaining-chart"' in html
    assert 'id="performance-chart"' in html
    assert 'href="history.csv"' in html
    for filename in ("status.json", "history.json", "metrics.json", "health.json"):
        assert f'"{filename}"' in javascript
        assert Path("docs", filename).is_file()
    assert "REFRESH_INTERVAL_MS = 60_000" in javascript
    assert "api.github.com" not in javascript
    assert "prefers-reduced-motion" in javascript
    assert Path("docs/history.json").is_file()
    assert Path("docs/history.csv").is_file()
