from pathlib import Path

import pytest

from jlpt_seat_watcher.config import ConfigurationError, Settings


def test_defaults_and_empty_topic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    settings = Settings.from_env(tmp_path)
    assert settings.check_interval == 300
    assert settings.ntfy_topic == ""
    assert settings.enable_playwright is True
    assert str(settings.timezone) == "Asia/Kolkata"
    assert settings.session_mode == "Auto"
    assert settings.history_retention_days == 30
    assert settings.adapter == "jlpt_chennai"


def test_rejects_bad_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHECK_INTERVAL", "fast")
    with pytest.raises(ConfigurationError, match="integer"):
        Settings.from_env(tmp_path)

    monkeypatch.setenv("CHECK_INTERVAL", "300")
    monkeypatch.setenv("ENABLE_SCREENSHOT", "perhaps")
    with pytest.raises(ConfigurationError, match="true or false"):
        Settings.from_env(tmp_path)


def test_reads_watched_levels_and_runtime_values_from_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "config.yaml").write_text(
        """
watched_levels: [N5, N4, N3, N2, N1]
session: Both
notification_provider: discord
adapter: custom_adapter
check_interval: 600
history_retention_days: 21
enable_playwright: false
website_url: https://jlpt.example.test/
""",
        encoding="utf-8",
    )
    settings = Settings.from_env(tmp_path)
    assert settings.watched_levels == ("N5", "N4", "N3", "N2", "N1")
    assert settings.check_interval == 600
    assert settings.enable_playwright is False
    assert settings.website_url == "https://jlpt.example.test/"
    assert settings.session_mode == "Both"
    assert settings.notification_provider == "discord"
    assert settings.history_retention_days == 21
    assert settings.adapter == "custom_adapter"

    monkeypatch.setenv("WATCHED_LEVELS", "N2,N1")
    monkeypatch.setenv("CHECK_INTERVAL", "900")
    monkeypatch.setenv("WATCHED_SESSION", "afternoon")
    monkeypatch.setenv("NOTIFICATION_PROVIDER", "telegram")
    overridden = Settings.from_env(tmp_path)
    assert overridden.watched_levels == ("N2", "N1")
    assert overridden.check_interval == 900
    assert overridden.session_mode == "Afternoon"
    assert overridden.notification_provider == "telegram"

    monkeypatch.setenv("WATCHTOWER_ADAPTER", "runtime_adapter")
    assert Settings.from_env(tmp_path).adapter == "runtime_adapter"


@pytest.mark.parametrize(
    "yaml_text, message",
    [
        ("watched_levels: []", "non-empty"),
        ("watched_levels: [N4, N4]", "duplicates"),
        ("watched_levels: [N6]", "may only contain"),
        ("- N4", "YAML mapping"),
        ("website_url: ftp://example.test", "HTTP"),
        ("session: Evening", "session must be one of"),
        ("notification_provider: ''", "cannot be empty"),
        ("adapter: ''", "adapter cannot be empty"),
        ("smtp_use_tls: true\nsmtp_use_ssl: true", "cannot both be true"),
    ],
)
def test_rejects_invalid_yaml_config(
    tmp_path: Path, yaml_text: str, message: str
) -> None:
    (tmp_path / "config.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(tmp_path)


def test_reads_smtp_config_and_secret_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "config.yaml").write_text(
        """
notification_provider: email
smtp_host: smtp.yaml.test
smtp_port: 465
smtp_from: watcher@yaml.test
smtp_to: [first@yaml.test]
smtp_use_tls: false
smtp_use_ssl: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SMTP_HOST", "smtp.env.test")
    monkeypatch.setenv("SMTP_FROM", "watcher@env.test")
    monkeypatch.setenv("SMTP_TO", "first@env.test,second@env.test")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    settings = Settings.from_env(tmp_path)
    assert settings.notification_provider == "email"
    assert settings.smtp_host == "smtp.env.test"
    assert settings.smtp_port == 465
    assert settings.smtp_from == "watcher@env.test"
    assert settings.smtp_to == ("first@env.test", "second@env.test")
    assert settings.smtp_username == "mailer"
    assert settings.smtp_password == "secret"
    assert settings.smtp_use_tls is False
    assert settings.smtp_use_ssl is True
