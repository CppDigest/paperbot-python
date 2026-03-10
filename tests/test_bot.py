"""Tests for paperbot.bot."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from paperbot.models import Paper
from paperbot.monitor import DiffResult, PollResult, Watchlist
from paperbot.sources import ProbeHit
from paperbot.storage import ProbeState
from paperbot.bot import (
    _batch_lines,
    _handle_status,
    _handle_watchlist,
    _reply_opts,
    _show_watchlist,
    notify_channel,
    register_handlers,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _empty_diff() -> DiffResult:
    return DiffResult(new_papers=[], updated_papers=[])


def _make_result(
    new_papers=None,
    probe_hits=None,
    watchlist_matches=None,
    probe_watchlist_hits=None,
) -> PollResult:
    return PollResult(
        diff=DiffResult(new_papers=new_papers or [], updated_papers=[]),
        probe_hits=probe_hits or [],
        watchlist_matches=watchlist_matches or [],
        probe_watchlist_hits=probe_watchlist_hits or [],
    )


def _make_settings(channel="C123456", **overrides):
    defaults = dict(
        notification_channel=channel,
        notify_on_watchlist_author=True,
        notify_on_watchlist_paper=True,
        notify_on_frontier_hit=True,
        notify_on_tier_c_hit=True,
        poll_interval_minutes=30,
        enable_iso_probe=True,
    )
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# ── notify_channel ────────────────────────────────────────────────────────────

class TestNotifyChannel:
    def test_no_channel_returns_silently(self):
        mock_settings = _make_settings(channel="")
        app = MagicMock()
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, _make_result())
        app.client.chat_postMessage.assert_not_called()

    def test_empty_result_posts_nothing(self):
        mock_settings = _make_settings()
        app = MagicMock()
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, _make_result())
        app.client.chat_postMessage.assert_not_called()

    def test_watchlist_author_match_from_index(self):
        mock_settings = _make_settings()
        app = MagicMock()
        paper = Paper(id="P2300R11", title="Senders", author="Eric Niebler")
        result = _make_result(watchlist_matches=[paper])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "Niebler" in text

    def test_watchlist_author_suppressed_when_disabled(self):
        mock_settings = _make_settings(notify_on_watchlist_author=False)
        app = MagicMock()
        paper = Paper(id="P2300R11", title="Senders", author="Eric Niebler")
        result = _make_result(watchlist_matches=[paper])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_not_called()

    def test_probe_watchlist_hit_with_matching_author(self):
        mock_settings = _make_settings()
        app = MagicMock()
        wl = MagicMock()
        wl.authors = ["niebler"]
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B", front_text="written by niebler",
        )
        result = _make_result(probe_watchlist_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result, watchlist=wl)
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "niebler" in text

    def test_probe_watchlist_hit_no_matching_author_text(self):
        mock_settings = _make_settings()
        app = MagicMock()
        wl = MagicMock()
        wl.authors = ["baker"]
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B", front_text="text without matching name",
        )
        result = _make_result(probe_watchlist_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result, watchlist=wl)
        app.client.chat_postMessage.assert_called_once()

    def test_probe_hit_tier_a_notified(self):
        mock_settings = _make_settings()
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D2300R11.pdf",
            prefix="D", number=2300, revision=11, extension=".pdf",
            tier="A",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "Watched paper" in text

    def test_probe_hit_tier_b_notified(self):
        mock_settings = _make_settings()
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "Frontier" in text

    def test_probe_hit_tier_c_notified(self):
        mock_settings = _make_settings()
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="C",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "D-paper draft" in text

    def test_probe_hit_tier_a_suppressed_when_disabled(self):
        mock_settings = _make_settings(notify_on_watchlist_paper=False)
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D2300R11.pdf",
            prefix="D", number=2300, revision=11, extension=".pdf",
            tier="A",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_not_called()

    def test_probe_hit_tier_b_suppressed_when_disabled(self):
        mock_settings = _make_settings(notify_on_frontier_hit=False)
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_not_called()

    def test_probe_hit_tier_c_suppressed_when_disabled(self):
        mock_settings = _make_settings(notify_on_tier_c_hit=False)
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="C",
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        app.client.chat_postMessage.assert_not_called()

    def test_probe_hit_in_watchlist_hits_not_double_counted(self):
        """A hit already in probe_watchlist_hits should not also appear in probe_lines."""
        mock_settings = _make_settings()
        app = MagicMock()
        wl = MagicMock()
        wl.authors = ["niebler"]
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B", front_text="niebler",
        )
        result = _make_result(probe_hits=[hit], probe_watchlist_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result, watchlist=wl)
        # One post for watchlist section
        app.client.chat_postMessage.assert_called_once()
        text = app.client.chat_postMessage.call_args[1]["text"]
        assert "Frontier" not in text  # Not double-counted

    def test_notify_channel_no_watchlist_arg(self):
        mock_settings = _make_settings()
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B",
        )
        result = _make_result(probe_watchlist_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)  # No watchlist arg
        app.client.chat_postMessage.assert_called_once()

    def test_post_failure_does_not_raise(self):
        mock_settings = _make_settings()
        app = MagicMock()
        app.client.chat_postMessage.side_effect = Exception("Slack down")
        paper = Paper(id="P2300R11", author="Niebler")
        result = _make_result(watchlist_matches=[paper])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)  # Should not propagate exception

    def test_unknown_tier_label(self):
        mock_settings = _make_settings()
        app = MagicMock()
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="X",  # Unknown tier
        )
        result = _make_result(probe_hits=[hit])
        with patch("paperbot.bot.settings", mock_settings):
            notify_channel(app, result)
        # Tier "X" won't trigger any of the specific notify flags → nothing posted
        app.client.chat_postMessage.assert_not_called()


# ── _batch_lines ──────────────────────────────────────────────────────────────

class TestBatchLines:
    def test_single_batch_when_small(self):
        lines = ["line1", "line2", "line3"]
        batches = _batch_lines(lines, max_len=1000)
        assert len(batches) == 1
        assert "line1" in batches[0]
        assert "line3" in batches[0]

    def test_splits_when_over_limit(self):
        lines = ["x" * 100] * 10
        batches = _batch_lines(lines, max_len=250)
        assert len(batches) > 1

    def test_empty_lines(self):
        assert _batch_lines([], max_len=1000) == []

    def test_single_line_exceeding_limit(self):
        lines = ["x" * 500]
        batches = _batch_lines(lines, max_len=100)
        assert len(batches) == 1


# ── _reply_opts ───────────────────────────────────────────────────────────────

class TestReplyOpts:
    def test_no_thread(self):
        opts = _reply_opts({"ts": "123"})
        assert "thread_ts" not in opts
        assert opts["unfurl_links"] is False

    def test_with_thread(self):
        opts = _reply_opts({"ts": "123", "thread_ts": "456"})
        assert opts["thread_ts"] == "456"


# ── _handle_watchlist ─────────────────────────────────────────────────────────

class TestHandleWatchlist:
    def _wl(self, tmp_path) -> Watchlist:
        return Watchlist(tmp_path / "wl.json")

    def test_add_new_author(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["add", "Niebler"], self._wl(tmp_path), say, {})
        say.assert_called_once()
        assert "Added" in say.call_args[1]["text"]

    def test_add_existing_author(self, tmp_path):
        wl = self._wl(tmp_path)
        wl.add_author("Niebler")
        say = MagicMock()
        _handle_watchlist(["add", "Niebler"], wl, say, {})
        assert "already" in say.call_args[1]["text"]

    def test_add_multi_word_name(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["add", "Eric", "Niebler"], self._wl(tmp_path), say, {})
        assert "Added" in say.call_args[1]["text"]

    def test_remove_existing_author(self, tmp_path):
        wl = self._wl(tmp_path)
        wl.add_author("Niebler")
        say = MagicMock()
        _handle_watchlist(["remove", "Niebler"], wl, say, {})
        assert "Removed" in say.call_args[1]["text"]

    def test_remove_nonexistent_author(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["remove", "Nobody"], self._wl(tmp_path), say, {})
        assert "not on the watchlist" in say.call_args[1]["text"]

    def test_list_shows_authors(self, tmp_path):
        wl = self._wl(tmp_path)
        wl.add_author("Niebler")
        say = MagicMock()
        _handle_watchlist(["list"], wl, say, {})
        assert "niebler" in say.call_args[1]["text"]

    def test_no_args_shows_list(self, tmp_path):
        wl = self._wl(tmp_path)
        wl.add_author("Stroustrup")
        say = MagicMock()
        _handle_watchlist([], wl, say, {})
        assert "stroustrup" in say.call_args[1]["text"]

    def test_add_without_name(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["add"], self._wl(tmp_path), say, {})
        assert "Usage" in say.call_args[1]["text"]

    def test_invalid_action(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["bogus", "name"], self._wl(tmp_path), say, {})
        assert "Usage" in say.call_args[1]["text"]

    def test_reply_opts_forwarded(self, tmp_path):
        say = MagicMock()
        _handle_watchlist(["list"], self._wl(tmp_path), say, {"thread_ts": "t1"})
        assert say.call_args[1]["thread_ts"] == "t1"


# ── _show_watchlist ───────────────────────────────────────────────────────────

class TestShowWatchlist:
    def test_empty_watchlist(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        say = MagicMock()
        _show_watchlist(wl, say, {})
        assert "empty" in say.call_args[1]["text"].lower()

    def test_non_empty_watchlist(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Baker")
        say = MagicMock()
        _show_watchlist(wl, say, {})
        assert "baker" in say.call_args[1]["text"]


# ── _handle_status ────────────────────────────────────────────────────────────

class TestHandleStatus:
    def test_status_never_polled(self, tmp_path):
        mock_settings = _make_settings()
        state = ProbeState(tmp_path / "state.json")
        say = MagicMock()
        with patch("paperbot.bot.settings", mock_settings):
            _handle_status(state, lambda: 42, say, {})
        text = say.call_args[1]["text"]
        assert "42" in text
        assert "never" in text

    def test_status_after_poll(self, tmp_path):
        mock_settings = _make_settings()
        import time
        state = ProbeState(tmp_path / "state.json")
        state.touch_poll()
        say = MagicMock()
        with patch("paperbot.bot.settings", mock_settings):
            _handle_status(state, lambda: 100, say, {})
        text = say.call_args[1]["text"]
        assert "100" in text
        assert "never" not in text


# ── register_handlers (event integration) ────────────────────────────────────

class TestRegisterHandlers:
    def _setup(self, tmp_path):
        """Register handlers on a mock App and return the captured handlers."""
        app = MagicMock()
        registered: dict = {}

        def capture_event(name):
            def decorator(fn):
                registered[name] = fn
                return fn
            return decorator

        app.event.side_effect = capture_event
        wl = Watchlist(tmp_path / "wl.json")
        state = ProbeState(tmp_path / "state.json")
        register_handlers(app, wl, state, lambda: 99)
        return registered, wl, state

    def test_app_mention_status(self, tmp_path):
        registered, _, state = self._setup(tmp_path)
        say = MagicMock()
        mock_settings = _make_settings()
        with patch("paperbot.bot.settings", mock_settings):
            registered["app_mention"](
                event={"text": "<@U1> status", "ts": "1"},
                context={"bot_user_id": "U1"},
                say=say,
            )
        say.assert_called_once()
        assert "Status" in say.call_args[1]["text"]

    def test_app_mention_empty_text(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["app_mention"](
            event={"text": "", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_app_mention_no_bot_id_in_text(self, tmp_path):
        registered, _, state = self._setup(tmp_path)
        say = MagicMock()
        mock_settings = _make_settings()
        with patch("paperbot.bot.settings", mock_settings):
            registered["app_mention"](
                event={"text": "status", "ts": "1"},
                context={"bot_user_id": ""},
                say=say,
            )
        say.assert_called_once()

    def test_message_dm_dispatches(self, tmp_path):
        registered, _, state = self._setup(tmp_path)
        say = MagicMock()
        mock_settings = _make_settings()
        with patch("paperbot.bot.settings", mock_settings):
            registered["message"](
                event={"text": "status", "channel_type": "im", "ts": "1"},
                context={"bot_user_id": "U1"},
                say=say,
            )
        say.assert_called_once()

    def test_message_dm_strips_mention(self, tmp_path):
        registered, _, state = self._setup(tmp_path)
        say = MagicMock()
        mock_settings = _make_settings()
        with patch("paperbot.bot.settings", mock_settings):
            registered["message"](
                event={"text": "<@U1> status", "channel_type": "im", "ts": "1"},
                context={"bot_user_id": "U1"},
                say=say,
            )
        say.assert_called_once()

    def test_message_dm_empty_after_strip(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "<@U1>", "channel_type": "im", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_message_channel_with_mention_ignored(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "<@U1> status", "channel_type": "channel", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_message_subtype_ignored(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "status", "subtype": "message_changed", "channel_type": "im"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_message_bot_id_ignored(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "status", "bot_id": "B123", "channel_type": "im"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_message_empty_text_ignored(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "", "channel_type": "im"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_not_called()

    def test_dispatch_help(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "help", "channel_type": "im", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        assert "Commands" in say.call_args[1]["text"]

    def test_dispatch_unknown_command(self, tmp_path):
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "foobar", "channel_type": "im", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        assert "Unknown" in say.call_args[1]["text"]

    def test_dispatch_empty_text(self, tmp_path):
        """_dispatch with only whitespace should not call say."""
        registered, _, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "   ", "channel_type": "im", "ts": "1"},
            context={"bot_user_id": ""},
            say=say,
        )
        say.assert_not_called()

    def test_dispatch_watchlist_command(self, tmp_path):
        """The 'watchlist' branch in _dispatch should route to _handle_watchlist."""
        registered, wl, _ = self._setup(tmp_path)
        say = MagicMock()
        registered["message"](
            event={"text": "watchlist list", "channel_type": "im", "ts": "1"},
            context={"bot_user_id": "U1"},
            say=say,
        )
        say.assert_called_once()
        assert "empty" in say.call_args[1]["text"].lower()


# ── create_app ────────────────────────────────────────────────────────────────

class TestCreateApp:
    def test_create_app_uses_settings(self):
        from paperbot.bot import create_app
        mock_settings = MagicMock()
        mock_settings.slack_bot_token = "xoxb-test"
        mock_settings.slack_signing_secret = "secret"
        with patch("paperbot.bot.settings", mock_settings):
            with patch("paperbot.bot.App") as mock_app_cls:
                create_app()
        mock_app_cls.assert_called_once_with(
            token="xoxb-test",
            signing_secret="secret",
        )
