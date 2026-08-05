from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import requests
import responses

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.scraper import USER_AGENTS, Scraper, ScraperError


@responses.activate
def test_static_fetch_uses_requests(settings: Settings) -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    responses.get(settings.website_url, body=html, status=200)
    observation = Scraper(settings).fetch()
    assert observation.remaining == 0
    assert observation.fetch_method == "requests"
    assert responses.calls[0].request.headers["User-Agent"] in USER_AGENTS


@responses.activate
def test_retries_retryable_status(settings: Settings) -> None:
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    responses.get(settings.website_url, status=503)
    responses.get(settings.website_url, status=429)
    responses.get(settings.website_url, body=html, status=200)
    delays: list[float] = []
    result = Scraper(settings, sleep=delays.append).fetch()
    assert result.total == 850
    assert len(delays) == 2


@responses.activate
def test_disabled_fallback_fails_gracefully_and_saves_html(settings: Settings) -> None:
    disabled = replace(settings, enable_playwright=False, max_retries=1)
    responses.get(disabled.website_url, body="<html>changed</html>", status=200)
    with pytest.raises(ScraperError, match="fallback is disabled"):
        Scraper(disabled).fetch()
    snapshots = list((disabled.logs_dir / "snapshots").glob("*.html"))
    assert snapshots


@responses.activate
def test_http_failure_retries_then_raises_without_browser(settings: Settings) -> None:
    disabled = replace(settings, enable_playwright=False, max_retries=2)
    responses.get(disabled.website_url, body=requests.Timeout("timeout"))
    responses.get(disabled.website_url, body=requests.Timeout("timeout"))
    with pytest.raises(ScraperError, match="fallback is disabled"):
        Scraper(disabled, sleep=lambda _: None).fetch()
