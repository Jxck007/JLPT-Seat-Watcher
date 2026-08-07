from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jlpt_seat_watcher.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_dir=tmp_path,
        website_url="https://example.test/",
        ntfy_topic="test-topic",
        ntfy_server="https://ntfy.test",
        ntfy_token="",
        timezone=ZoneInfo("Asia/Kolkata"),
        check_interval=900,
        heartbeat_interval=3600,
        urgent_interval=600,
        log_level="INFO",
        scraper_timeout=10,
        max_retries=3,
        enable_screenshot=True,
        enable_playwright=True,
        enable_daily_summary=False,
        daily_summary_hour=20,
        log_retention_days=30,
    )
