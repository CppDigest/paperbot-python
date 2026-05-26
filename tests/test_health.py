"""Tests for paperscout.health."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from paperscout.health import start_health_server


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _FakeState:
    def __init__(self, last_poll=None, discovered=None):
        self.last_poll = last_poll
        self._discovered = discovered or {}

    def get_all_discovered(self):
        return self._discovered


@pytest.fixture()
def health_url_with_extras():
    port = _find_free_port()
    launch = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
    state = _FakeState(last_poll=1742119200.0, discovered={"u1": 1})
    server = start_health_server(
        port,
        launch,
        state,
        lambda: 42,
        extra_fields_fn=lambda: {
            "last_updated": "2026-03-16T12:00:00+00:00",
            "last_successful_poll": "2026-03-16T12:00:00+00:00",
            "last_cycle_status": "success",
            "last_cycle_error": None,
            "poll_count": 1,
            "probe_stats": {},
            "probe_success_rate": 0.5,
            "mq_depth": 3,
            "db_pool": {"max": 10, "in_use": 1, "available": 9},
        },
    )
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture()
def health_url():
    port = _find_free_port()
    launch = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
    state = _FakeState(last_poll=1742119200.0, discovered={"u1": 1, "u2": 2})
    server = start_health_server(port, launch, state, lambda: 42)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestHealthEndpoint:
    def test_health_returns_200_with_json(self, health_url):
        resp = urllib.request.urlopen(f"{health_url}/health")
        assert resp.status == 200
        data = json.loads(resp.read())
        assert "version" in data
        assert "uptime_seconds" in data
        assert "launched_at" in data
        assert "papers_loaded" in data
        assert "last_poll" in data
        assert "discovered_via_probe" in data
        assert "iso_probe_enabled" in data

    def test_health_values(self, health_url):
        data = json.loads(urllib.request.urlopen(f"{health_url}/health").read())
        assert data["papers_loaded"] == 42
        assert data["discovered_via_probe"] == 2
        assert data["launched_at"] == "2026-03-16T10:00:00+00:00"
        assert isinstance(data["uptime_seconds"], int)

    def test_health_trailing_slash(self, health_url):
        resp = urllib.request.urlopen(f"{health_url}/health/")
        assert resp.status == 200

    def test_other_path_returns_404(self, health_url):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{health_url}/notfound")
        assert exc_info.value.code == 404

    def test_iso_probe_flag_follows_config_settings(self, health_url):
        import paperscout.config as cfg

        original = cfg.settings.enable_iso_probe
        try:
            cfg.settings.enable_iso_probe = False
            data = json.loads(urllib.request.urlopen(f"{health_url}/health").read())
            assert data["iso_probe_enabled"] is False

            cfg.settings.enable_iso_probe = True
            data = json.loads(urllib.request.urlopen(f"{health_url}/health").read())
            assert data["iso_probe_enabled"] is True
        finally:
            cfg.settings.enable_iso_probe = original

    def test_health_extra_fields_merged(self, health_url_with_extras):
        data = json.loads(urllib.request.urlopen(f"{health_url_with_extras}/health").read())
        assert "version" in data
        assert data["last_updated"] == "2026-03-16T12:00:00+00:00"
        assert data["last_cycle_status"] == "success"
        assert "last_successful_poll" in data
        assert data["last_successful_poll"] == "2026-03-16T12:00:00+00:00"
        assert data["probe_success_rate"] == 0.5
        assert data["mq_depth"] == 3
        assert data["db_pool"] == {"max": 10, "in_use": 1, "available": 9}


@dataclass(frozen=True, slots=True)
class _TestSnapshot:
    last_updated: str
    poll_count: int
    last_cycle_status: str


class _ConcurrentSnapshotPublisher:
    """Minimal stand-in for Scheduler health_snapshot under concurrent updates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap: _TestSnapshot | None = None
        self._stop = threading.Event()

    def publish(self, poll_count: int, status: str) -> None:
        snap = _TestSnapshot(
            last_updated=datetime.now(timezone.utc).isoformat(),
            poll_count=poll_count,
            last_cycle_status=status,
        )
        with self._lock:
            self._snap = snap

    def health_snapshot(self) -> dict:
        with self._lock:
            snap = self._snap
        if snap is None:
            return {
                "last_updated": None,
                "poll_count": 0,
                "last_cycle_status": None,
            }
        return dataclasses.asdict(snap)

    def run_updates(self) -> None:
        n = 0
        while not self._stop.is_set():
            self.publish(n, "success" if n % 2 == 0 else "empty")
            n += 1
            time.sleep(0.005)

    def stop(self) -> None:
        self._stop.set()


class TestHealthExtraFieldsSafety:
    def test_extra_fields_cannot_overwrite_base_handler_keys(self):
        port = _find_free_port()
        launch = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        state = _FakeState()
        server = start_health_server(
            port,
            launch,
            state,
            lambda: 42,
            extra_fields_fn=lambda: {
                "version": "evil",
                "uptime_seconds": -1,
                "mq_depth": 2,
            },
        )
        try:
            data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
            assert data["version"] != "evil"
            assert data["uptime_seconds"] >= 0
            assert data["mq_depth"] == 2
        finally:
            server.shutdown()

    def test_extra_fields_fn_failure_returns_base_only(self):
        port = _find_free_port()
        launch = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)

        def _boom():
            raise RuntimeError("snapshot unavailable")

        server = start_health_server(
            port,
            launch,
            _FakeState(),
            lambda: 0,
            extra_fields_fn=_boom,
        )
        try:
            data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
            assert "version" in data
            assert "last_poll" in data
            assert "last_updated" not in data
        finally:
            server.shutdown()


class TestHealthSnapshotConcurrency:
    def test_health_snapshot_consistent_under_concurrent_updates(self):
        port = _find_free_port()
        launch = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        publisher = _ConcurrentSnapshotPublisher()
        publisher.publish(0, "success")
        updater = threading.Thread(target=publisher.run_updates, daemon=True)
        updater.start()
        server = start_health_server(
            port,
            launch,
            _FakeState(),
            lambda: 0,
            extra_fields_fn=publisher.health_snapshot,
        )
        try:
            for _ in range(50):
                data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
                assert data["last_updated"] is not None
                assert data["poll_count"] >= 0
                assert data["last_cycle_status"] in ("success", "empty", None)
        finally:
            publisher.stop()
            updater.join(timeout=2)
            server.shutdown()
