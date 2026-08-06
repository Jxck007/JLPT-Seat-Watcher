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
def test_fetches_all_configured_levels_with_one_request(settings: Settings) -> None:
    configured = replace(settings, watched_levels=("N5", "N4", "N3", "N2", "N1"))
    html = Path("tests/fixtures/current.html").read_text(encoding="utf-8")
    responses.get(configured.website_url, body=html, status=200)
    observations = Scraper(configured).fetch_all()
    assert [item.level for item in observations] == ["N5", "N4", "N3", "N2", "N1"]
    assert [item.remaining for item in observations] == [671, 0, 512, 439, 187]
    assert len(responses.calls) == 1


@responses.activate
def test_fetches_same_level_from_both_sessions(settings: Settings) -> None:
    configured = replace(settings, watched_levels=("N4",), session_mode="Both")
    html = """
    <div class="table-container1">
      <div class="cell1">FORENOON EXAM APPLICATIONS</div>
      <div class="cell1">N4 Total: 100</div>
      <div class="cell1">Applied: 99</div>
      <div class="cell1">Remaining: 1</div>
      <div class="cell1">AFTERNOON EXAM APPLICATIONS</div>
      <div class="cell1">N4 Total: 200</div>
      <div class="cell1">Applied: 198</div>
      <div class="cell1">Remaining: 2</div>
    </div>
    """
    responses.get(configured.website_url, body=html, status=200)
    observations = Scraper(configured).fetch_all()
    assert [(item.session, item.remaining) for item in observations] == [
        ("Forenoon", 1),
        ("Afternoon", 2),
    ]
    assert len(responses.calls) == 1


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
