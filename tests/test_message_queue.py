"""Tests for paperscout.scout.MessageQueue (Slack chat.postMessage worker)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from paperscout.scout import MessageQueue


def _slack_error(status: int, headers: dict | None = None) -> SlackApiError:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers if headers is not None else {}
    return SlackApiError("slack error", resp)


class TestMessageQueueDirect:
    """Exercise ``_throttle`` / ``_send_with_retry`` without starting the daemon thread."""

    def test_send_success_updates_last_send(self):
        app = MagicMock()
        mq = MessageQueue(app)
        with patch.object(mq, "_throttle"):
            mq._send_with_retry("C1", "hello", {})
        app.client.chat_postMessage.assert_called_once_with(
            channel="C1",
            text="hello",
            unfurl_links=False,
            unfurl_media=False,
        )

    def test_send_forwards_extra_kwargs(self):
        app = MagicMock()
        mq = MessageQueue(app)
        with patch.object(mq, "_throttle"):
            mq._send_with_retry("C1", "x", {"thread_ts": "99.9"})
        app.client.chat_postMessage.assert_called_once_with(
            channel="C1",
            text="x",
            unfurl_links=False,
            unfurl_media=False,
            thread_ts="99.9",
        )

    def test_429_retries_then_success(self):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = [
            _slack_error(429, {"Retry-After": "2"}),
            None,
        ]
        mq = MessageQueue(app)
        sleeps: list[float] = []

        with patch.object(mq, "_throttle"):
            with patch("paperscout.scout.time.sleep", side_effect=sleeps.append):
                mq._send_with_retry("C1", "hi", {})

        assert app.client.chat_postMessage.call_count == 2
        assert sleeps == [2.0]

    def test_429_default_retry_after_when_header_missing(self):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = [
            _slack_error(429, {}),
            None,
        ]
        mq = MessageQueue(app)
        sleeps: list[float] = []

        with patch.object(mq, "_throttle"):
            with patch("paperscout.scout.time.sleep", side_effect=sleeps.append):
                mq._send_with_retry("C1", "hi", {})

        assert sleeps == [5.0]

    def test_non_429_slack_error_stops(self):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = _slack_error(500)
        mq = MessageQueue(app)

        with patch.object(mq, "_throttle"):
            mq._send_with_retry("C1", "hi", {})

        assert app.client.chat_postMessage.call_count == 1

    def test_generic_exception_stops(self):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = RuntimeError("network down")
        mq = MessageQueue(app)

        with patch.object(mq, "_throttle"):
            mq._send_with_retry("C1", "hi", {})

        assert app.client.chat_postMessage.call_count == 1

    def test_throttle_sleeps_when_within_one_second(self):
        app = MagicMock()
        mq = MessageQueue(app)
        mq._last_send["C1"] = 1000.0

        sleeps: list[float] = []

        with patch("paperscout.scout.time.monotonic", return_value=1000.4):
            with patch("paperscout.scout.time.sleep", side_effect=sleeps.append):
                mq._throttle("C1")

        assert len(sleeps) == 1
        assert sleeps[0] == pytest.approx(0.6, rel=1e-3)

    def test_throttle_no_sleep_when_idle(self):
        app = MagicMock()
        mq = MessageQueue(app)
        mq._last_send["C1"] = 0.0

        sleeps: list[float] = []

        with patch("paperscout.scout.time.monotonic", return_value=5000.0):
            with patch("paperscout.scout.time.sleep", side_effect=sleeps.append):
                mq._throttle("C1")

        assert sleeps == []


class TestMessageQueueThreaded:
    def test_enqueue_processed_by_background_thread(self):
        app = MagicMock()
        mq = MessageQueue(app)
        done = threading.Event()

        def side_effect(**kwargs):
            done.set()

        app.client.chat_postMessage.side_effect = side_effect

        mq.start()
        mq.enqueue("D123", "queued message")
        assert done.wait(timeout=5.0), "chat_postMessage was not invoked in time"
        app.client.chat_postMessage.assert_called()
