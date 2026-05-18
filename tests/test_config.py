"""Tests for ``paperscout.config`` validation."""

from __future__ import annotations

import pytest

from paperscout.config import Settings
from paperscout.errors import ConfigurationError


def test_settings_rejects_blank_slack_when_not_testing(monkeypatch):
    monkeypatch.delenv("_PAPERSCOUT_TESTING", raising=False)
    with pytest.raises(ConfigurationError, match="Slack is not configured"):
        Settings(
            slack_bot_token="",
            slack_signing_secret="",
        )


def test_settings_accepts_slack_when_not_testing(monkeypatch):
    monkeypatch.delenv("_PAPERSCOUT_TESTING", raising=False)
    s = Settings(
        slack_bot_token="xoxb-real",
        slack_signing_secret="not-empty",
    )
    assert s.slack_bot_token == "xoxb-real"


def test_settings_allows_empty_slack_under_testing_flag(monkeypatch):
    monkeypatch.setenv("_PAPERSCOUT_TESTING", "1")
    s = Settings(slack_bot_token="", slack_signing_secret="")
    assert s.slack_bot_token == ""
