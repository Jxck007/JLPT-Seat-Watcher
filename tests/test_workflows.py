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
