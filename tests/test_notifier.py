from __future__ import annotations

from dataclasses import replace

import pytest
import requests
import responses

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.notifier import NotificationError, NtfyNotifier, Priority


@responses.activate
def test_sends_expected_ntfy_headers(settings: Settings) -> None:
    responses.post("https://ntfy.test/test-topic", status=200)
    NtfyNotifier(settings).send(
        "Seats", "Available", Priority.HIGH, tags=("rotating_light", "jlpt")
    )
    request = responses.calls[0].request
    assert request.headers["Priority"] == "4"
    assert request.headers["Tags"] == "rotating_light,jlpt"
    assert request.headers["Click"] == settings.website_url
    assert request.body == b"Available"


@responses.activate
def test_retries_without_exposing_topic(settings: Settings) -> None:
    responses.post("https://ntfy.test/test-topic", status=503)
    responses.post("https://ntfy.test/test-topic", status=500)
    responses.post("https://ntfy.test/test-topic", status=429)
    delays: list[float] = []
    with pytest.raises(NotificationError) as raised:
        NtfyNotifier(settings, sleep=delays.append).send(
            "Test", "body", Priority.NORMAL
        )
    assert delays == [1, 2]
    assert "test-topic" not in str(raised.value)


def test_requires_topic(settings: Settings) -> None:
    notifier = NtfyNotifier(replace(settings, ntfy_topic=""))
    assert notifier.configured is False
    with pytest.raises(NotificationError, match="not configured"):
        notifier.send("Test", "body", Priority.SILENT)


class _FailingSession(requests.Session):
    def post(self, *args: object, **kwargs: object) -> requests.Response:
        raise requests.Timeout("secret topic URL")


def test_request_exception_is_redacted(settings: Settings) -> None:
    with pytest.raises(NotificationError) as raised:
        NtfyNotifier(settings, session=_FailingSession(), sleep=lambda _: None).send(
            "Test", "body", Priority.EMERGENCY
        )
    assert "secret topic" not in str(raised.value)
