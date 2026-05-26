"""Tests for paperscout.scout.MessageQueue (Slack chat.postMessage worker)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

import paperscout.config as cfg
from paperscout.scout import CircuitState, MessageQueue


def _slack_error(status: int, headers: dict | None = None) -> SlackApiError:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers if headers is not None else {}
    return SlackApiError("slack error", resp)


@pytest.fixture()
def mq_settings(monkeypatch):
    """Fast, small queue/breaker settings for tests."""
    monkeypatch.setattr(cfg.settings, "mq_max_retries", 3)
    monkeypatch.setattr(cfg.settings, "mq_circuit_breaker_threshold", 2)
    monkeypatch.setattr(cfg.settings, "mq_circuit_breaker_cooldown_seconds", 10)
    monkeypatch.setattr(cfg.settings, "mq_max_size", 5)


class TestMessageQueueDirect:
    """Exercise ``_throttle`` / ``_send_with_retry`` without starting the daemon thread."""

    def test_health_fields_reports_depth_and_utilization(self):
        mq = MessageQueue(MagicMock())
        mq.enqueue("C1", "x")
        fields = mq.health_fields()
        assert fields["mq_depth"] == 1
        assert fields["mq_max_size"] >= 1
        assert 0.0 <= fields["mq_utilization"] <= 1.0
        assert fields["mq_circuit_state"] == "closed"

    def test_health_fields_clamps_utilization_when_depth_exceeds_max(self):
        mq = MessageQueue(MagicMock())
        with patch("paperscout.scout.settings") as cfg:
            cfg.mq_max_size = 2
            for i in range(5):
                mq.enqueue(f"C{i}", "x")
            fields = mq.health_fields()
        assert fields["mq_depth"] == 5
        assert fields["mq_max_size"] == 2
        assert fields["mq_utilization"] == 1.0

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

    def test_429_retry_cap_exhaustion_dead_letters(self, mq_settings, caplog):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = _slack_error(429, {"Retry-After": "1"})
        mq = MessageQueue(app)

        with patch.object(mq, "_throttle"):
            with patch("paperscout.scout.time.sleep"):
                with caplog.at_level(logging.ERROR):
                    mq._send_with_retry("C1", "stuck message", {})

        assert app.client.chat_postMessage.call_count == cfg.settings.mq_max_retries + 1
        assert any("MQ-DEAD-LETTER" in r.message for r in caplog.records)
        assert any("retry_exhausted" in r.message for r in caplog.records)

    def test_circuit_breaker_trips_after_consecutive_failures(self, mq_settings, caplog):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = _slack_error(500)
        mq = MessageQueue(app)

        with patch.object(mq, "_throttle"):
            with caplog.at_level(logging.ERROR):
                mq._send_with_retry("C1", "a", {})
                mq._send_with_retry("C1", "b", {})

        assert mq._breaker.state == CircuitState.OPEN
        assert any("MQ-CIRCUIT-OPEN" in r.message for r in caplog.records)

        with patch.object(mq, "_throttle"):
            with caplog.at_level(logging.ERROR):
                mq._send_with_retry("C1", "c", {})

        assert app.client.chat_postMessage.call_count == 2
        assert any("circuit_open" in r.message for r in caplog.records)

    def test_circuit_breaker_half_open_recovery(self, mq_settings, caplog):
        app = MagicMock()
        mq = MessageQueue(app)
        mq._breaker._state = CircuitState.OPEN
        mq._breaker._opened_at = 1000.0
        mq._breaker._consecutive_failures = cfg.settings.mq_circuit_breaker_threshold

        mono = [1000.0]

        def fake_monotonic():
            return mono[0]

        with patch.object(mq, "_throttle"):
            with patch("paperscout.scout.time.monotonic", side_effect=fake_monotonic):
                with caplog.at_level(logging.INFO):
                    mq._send_with_retry("C1", "blocked", {})
                    assert mq._breaker.state == CircuitState.OPEN

                    mono[0] = 1011.0
                    app.client.chat_postMessage.side_effect = None
                    mq._send_with_retry("C1", "probe ok", {})

        assert mq._breaker.state == CircuitState.CLOSED
        assert any("MQ-CIRCUIT-HALF-OPEN" in r.message for r in caplog.records)

    def test_circuit_breaker_half_open_failure_reopens(self, mq_settings):
        app = MagicMock()
        app.client.chat_postMessage.side_effect = _slack_error(500)
        mq = MessageQueue(app)
        mq._breaker._state = CircuitState.HALF_OPEN

        with patch.object(mq, "_throttle"):
            mq._send_with_retry("C1", "fail probe", {})

        assert mq._breaker.state == CircuitState.OPEN

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


class TestMessageQueueBounded:
    def test_enqueue_normal_returns_true(self, mq_settings):
        app = MagicMock()
        mq = MessageQueue(app)
        assert mq.enqueue("C1", "hello") is True
        assert mq.depth() == 1

    def test_enqueue_respects_max_size_drop_oldest(self, mq_settings, caplog):
        app = MagicMock()
        mq = MessageQueue(app)
        for i in range(cfg.settings.mq_max_size):
            assert mq.enqueue("C", f"msg-{i}") is True

        with caplog.at_level(logging.WARNING):
            assert mq.enqueue("C", "newest") is True

        assert mq.depth() == cfg.settings.mq_max_size
        assert any("drop-oldest" in r.message for r in caplog.records)

        with mq._queue_lock:
            items = []
            while True:
                try:
                    items.append(mq._q.get_nowait())
                except queue.Empty:
                    break
        texts = [t for _, t, _ in items]
        assert "msg-0" not in texts
        assert "newest" in texts

    def test_enqueue_rejected_when_circuit_open(self, mq_settings, caplog):
        app = MagicMock()
        mq = MessageQueue(app)
        mq._breaker._state = CircuitState.OPEN
        mq._breaker._opened_at = time.monotonic()

        with caplog.at_level(logging.WARNING):
            assert mq.enqueue("C1", "blocked") is False

        assert mq.depth() == 0
        assert any("enqueue-rejected" in r.message for r in caplog.records)

    def test_health_fields_reports_depth_and_utilization(self, mq_settings):
        app = MagicMock()
        mq = MessageQueue(app)
        mq.enqueue("C1", "a")
        mq.enqueue("C1", "b")
        fields = mq.health_fields()
        assert fields["mq_depth"] == 2
        assert fields["mq_max_size"] == cfg.settings.mq_max_size
        assert fields["mq_utilization"] == pytest.approx(2 / cfg.settings.mq_max_size, rel=1e-3)
        assert fields["mq_circuit_state"] == "closed"

    def test_high_water_warning_at_80_percent(self, monkeypatch, caplog):
        monkeypatch.setattr(cfg.settings, "mq_max_size", 10)
        app = MagicMock()
        mq = MessageQueue(app)
        threshold = int(0.8 * cfg.settings.mq_max_size)
        for i in range(threshold):
            mq.enqueue("C", f"m{i}")

        with caplog.at_level(logging.WARNING):
            mq.enqueue("C", "tip")

        assert any("high-water" in r.message for r in caplog.records)


class TestMessageQueueThreaded:
    def test_enqueue_processed_by_background_thread(self):
        app = MagicMock()
        mq = MessageQueue(app)
        done = threading.Event()

        def side_effect(**kwargs):
            done.set()

        app.client.chat_postMessage.side_effect = side_effect

        mq.start()
        assert mq.enqueue("D123", "queued message") is True
        assert done.wait(timeout=5.0), "chat_postMessage was not invoked in time"
        app.client.chat_postMessage.assert_called()
