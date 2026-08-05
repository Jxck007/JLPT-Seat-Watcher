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


def test_rejects_bad_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHECK_INTERVAL", "fast")
    with pytest.raises(ConfigurationError, match="integer"):
        Settings.from_env(tmp_path)

    monkeypatch.setenv("CHECK_INTERVAL", "300")
    monkeypatch.setenv("ENABLE_SCREENSHOT", "perhaps")
    with pytest.raises(ConfigurationError, match="true or false"):
        Settings.from_env(tmp_path)
