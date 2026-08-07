from __future__ import annotations

import json
import smtplib
from dataclasses import replace
from email.message import EmailMessage
from typing import Any

import pytest
import requests
import responses

from jlpt_seat_watcher.config import Settings
from jlpt_seat_watcher.notifier import (
    DiscordWebhookNotifier,
    EmailSmtpNotifier,
    NotificationError,
    Notifier,
    NtfyNotifier,
    Priority,
    SlackWebhookNotifier,
    TelegramNotifier,
)


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
def test_low_priority_ntfy_heartbeat_uses_click_url(settings: Settings) -> None:
    responses.post("https://ntfy.test/test-topic", status=200)
    NtfyNotifier(settings).send(
        "JLPT N4 Monitor Active",
        "Remaining: 0",
        Priority.LOW,
        tags=("white_check_mark", "clock1"),
    )
    request = responses.calls[0].request
    assert request.headers["Priority"] == "2"
    assert request.headers["Tags"] == "white_check_mark,clock1"
    assert request.headers["Click"] == settings.website_url


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


def test_factory_selects_registered_providers(settings: Settings) -> None:
    expected = {
        "ntfy": NtfyNotifier,
        "telegram": TelegramNotifier,
        "discord": DiscordWebhookNotifier,
        "slack": SlackWebhookNotifier,
        "email": EmailSmtpNotifier,
    }
    for provider, notifier_class in expected.items():
        notifier = Notifier.create(replace(settings, notification_provider=provider))
        assert isinstance(notifier, notifier_class)

    with pytest.raises(NotificationError, match="Unknown notification provider"):
        Notifier.create(replace(settings, notification_provider="missing"))


def test_future_provider_only_requires_one_subclass(settings: Settings) -> None:
    class FutureNotifier(Notifier):
        provider = "future-test"

        @property
        def configured(self) -> bool:
            return True

        def send(
            self,
            title: str,
            message: str,
            priority: Priority,
            *,
            tags: tuple[str, ...] = (),
        ) -> None:
            del title, message, priority, tags

    selected = Notifier.create(replace(settings, notification_provider="future-test"))
    assert isinstance(selected, FutureNotifier)


@responses.activate
def test_telegram_payload(settings: Settings) -> None:
    configured = replace(
        settings,
        telegram_bot_token="bot-secret",
        telegram_chat_id="12345",
    )
    endpoint = "https://api.telegram.org/botbot-secret/sendMessage"
    responses.post(endpoint, status=200)
    TelegramNotifier(configured).send("Seats", "N4 available", Priority.HIGH)
    payload = json.loads(responses.calls[0].request.body)
    assert payload["chat_id"] == "12345"
    assert "Seats\n\nN4 available" in payload["text"]
    assert settings.website_url in payload["text"]


@responses.activate
def test_discord_payload_and_retry(settings: Settings) -> None:
    configured = replace(
        settings,
        discord_webhook_url="https://discord.test/webhook-secret",
        max_retries=2,
    )
    responses.post(configured.discord_webhook_url, status=503)
    responses.post(configured.discord_webhook_url, status=204)
    delays: list[float] = []
    DiscordWebhookNotifier(configured, sleep=delays.append).send(
        "Seats", "N4 available", Priority.HIGH
    )
    payload = json.loads(responses.calls[1].request.body)
    assert payload["content"].startswith("**Seats**\nN4 available")
    assert delays == [1]


@responses.activate
def test_slack_payload(settings: Settings) -> None:
    configured = replace(
        settings, slack_webhook_url="https://slack.test/webhook-secret"
    )
    responses.post(configured.slack_webhook_url, status=200)
    SlackWebhookNotifier(configured).send("Seats", "N4 available", Priority.NORMAL)
    payload = json.loads(responses.calls[0].request.body)
    assert payload["text"].startswith("*Seats*\nN4 available")
    assert "|Open website>" in payload["text"]


@pytest.mark.parametrize(
    "notifier_class",
    (TelegramNotifier, DiscordWebhookNotifier, SlackWebhookNotifier),
)
def test_http_providers_require_configuration(
    settings: Settings, notifier_class: type[Notifier]
) -> None:
    notifier = notifier_class(settings)
    assert notifier.configured is False
    with pytest.raises(NotificationError, match="not configured"):
        notifier.send("Test", "body", Priority.NORMAL)


class _FakeSmtp:
    def __init__(self) -> None:
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.message: EmailMessage | None = None

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def starttls(self, *, context: object) -> None:
        del context
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


def test_email_smtp_tls_authentication_and_payload(settings: Settings) -> None:
    configured = replace(
        settings,
        smtp_host="smtp.example.test",
        smtp_port=2525,
        smtp_username="mailer",
        smtp_password="smtp-secret",
        smtp_from="watcher@example.test",
        smtp_to=("one@example.test", "two@example.test"),
        smtp_use_tls=True,
    )
    client = _FakeSmtp()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def factory(*args: object, **kwargs: object) -> Any:
        calls.append((args, kwargs))
        return client

    notifier = EmailSmtpNotifier(
        configured,
        smtp_factory=factory,
    )
    notifier.send("Seats", "N4 available", Priority.HIGH)
    assert calls[0][0] == ("smtp.example.test", 2525)
    assert calls[0][1]["timeout"] == settings.scraper_timeout
    assert client.started_tls is True
    assert client.login_args == ("mailer", "smtp-secret")
    assert client.message is not None
    assert client.message["Subject"] == "Seats"
    assert client.message["To"] == "one@example.test, two@example.test"
    assert client.message["X-Priority"] == "1"
    assert "N4 available" in client.message.get_content()
    assert settings.website_url in client.message.get_content()


def test_email_requires_configuration_and_retries_safely(settings: Settings) -> None:
    notifier = EmailSmtpNotifier(settings)
    assert notifier.configured is False
    with pytest.raises(NotificationError, match="not configured"):
        notifier.send("Test", "body", Priority.NORMAL)

    configured = replace(
        settings,
        smtp_host="smtp.example.test",
        smtp_from="watcher@example.test",
        smtp_to=("one@example.test",),
        max_retries=2,
    )
    delays: list[float] = []

    def failing_factory(*args: object, **kwargs: object) -> smtplib.SMTP:
        del args, kwargs
        raise OSError("smtp-secret")

    with pytest.raises(NotificationError) as raised:
        EmailSmtpNotifier(
            configured,
            smtp_factory=failing_factory,
            sleep=delays.append,
        ).send("Test", "body", Priority.NORMAL)
    assert delays == [1]
    assert "smtp-secret" not in str(raised.value)
