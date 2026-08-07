from pathlib import Path

import yaml


def test_monitor_workflow_contract() -> None:
    path = Path(".github/workflows/monitor.yml")
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"][0]["cron"] == "*/15 * * * *"
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {"force_notification_test", "force_scraper_test"} <= set(inputs)
    assert "GITHUB_STEP_SUMMARY" in raw
    assert "actions/cache/restore" in raw
    assert "actions/cache/save" in raw
    assert "if: failure()" in raw
    assert workflow["permissions"]["contents"] == "write"
    assert "scripts/publish_dashboard.py" in raw
    assert "--check-interval 900" in raw
    assert 'HEARTBEAT_INTERVAL: "3600"' in raw
    assert 'MAX_ALERT_INTERVAL: "21600"' in raw
    assert "--max-alert-interval 21600" in raw
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


def test_pages_uses_branch_deployment_without_custom_workflow() -> None:
    assert not Path(".github/workflows/pages.yml").exists()
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path(".github/workflows").glob("*.yml")
    )
    for action in (
        "actions/configure-pages",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    ):
        assert action not in workflow_text


def test_dashboard_assets_use_safe_public_data_contracts() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")
    javascript = Path("docs/app.js").read_text(encoding="utf-8")
    assert "JLPT N4 Seat Monitor" in html
    assert "Afternoon Session" in html
    assert "Open JLPT Registration" in html
    assert ">Refresh</button>" in html
    assert "remaining" in html
    for field in ("last-min", "last-default", "last-high", "last-max"):
        assert field in html
    for filename in ("status.json", "history.json", "metrics.json", "health.json"):
        assert f'"{filename}"' in javascript
        assert Path("docs", filename).is_file()
    assert "REFRESH_INTERVAL_MS = 60_000" in javascript
    assert "api.github.com" not in javascript
    assert "REFRESH_INTERVAL_MS" in javascript
    assert Path("docs/history.json").is_file()
    assert Path("docs/history.csv").is_file()
