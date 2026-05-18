"""Probe-cycle benchmark and regression gate (mock HTTP transport; no isocpp.org traffic)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from tests.conftest import FakePool, make_test_settings

from paperscout.sources import ISOProber, WG21Index
from paperscout.storage import ProbeState, UserWatchlist

# Captured at import time so ``patch('paperscout.sources.httpx.AsyncClient', ...)`` cannot recurse.
_REAL_HTTPX_ASYNC_CLIENT = httpx.AsyncClient


def _mock_wl(paper_nums: list[int] | None = None) -> MagicMock:
    wl = MagicMock(spec=UserWatchlist)
    wl.get_all_watched_paper_nums.return_value = set(paper_nums or [])
    return wl


BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _make_metrics() -> dict:
    return {
        "request_count": 0,
        "latencies_sec": [],
        "peak_concurrent": 0,
        "active": 0,
        "lock": threading.Lock(),
    }


def _build_mock_handler(
    metrics: dict,
    per_request_delay_sec: float,
) -> Callable[[httpx.Request], httpx.Response]:
    lm_recent = datetime.now(timezone.utc) - timedelta(hours=2)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        t0 = time.perf_counter()
        with metrics["lock"]:
            metrics["active"] += 1
            metrics["peak_concurrent"] = max(metrics["peak_concurrent"], metrics["active"])
        try:
            time.sleep(per_request_delay_sec)
            metrics["request_count"] += 1
            if request.method == "GET" and path.endswith((".pdf", ".html")):
                return httpx.Response(200, text="<html><body>x</body></html>")
            if request.method != "HEAD":
                return httpx.Response(404)
            headers = {"last-modified": format_datetime(lm_recent, usegmt=True)}
            return httpx.Response(200, headers=headers)
        finally:
            with metrics["lock"]:
                metrics["active"] -= 1
                metrics["latencies_sec"].append(time.perf_counter() - t0)

    return handler


def _build_prober(
    fake_pool,
    http_concurrency: int,
    poll_interval_minutes: int,
) -> ISOProber:
    index = WG21Index(fake_pool)
    index._max_p = 100
    index._max_rev = {99: 0, 100: 0}
    index._sorted_p_nums = [99, 100]
    state = ProbeState(fake_pool)
    wl = _mock_wl([9999])
    cfg = make_test_settings(
        http_concurrency=http_concurrency,
        poll_interval_minutes=poll_interval_minutes,
        hot_lookback_months=0,
        hot_revision_depth=1,
        frontier_window_above=0,
        frontier_window_below=0,
        gap_max_rev=0,
        cold_cycle_divisor=100,
        http_timeout_seconds=30,
        http_use_http2=False,
    )
    return ISOProber(index, state, user_watchlist=wl, cfg=cfg)


async def _run_one_cycle(
    prober: ISOProber,
    per_request_delay_sec: float,
) -> dict:
    metrics = _make_metrics()
    transport = httpx.MockTransport(_build_mock_handler(metrics, per_request_delay_sec))

    real_async_client = _REAL_HTTPX_ASYNC_CLIENT

    def client_factory(**kwargs):
        kwargs.pop("transport", None)
        return real_async_client(transport=transport, **kwargs)

    with patch("paperscout.sources.httpx.AsyncClient", side_effect=client_factory):
        t_wall0 = time.perf_counter()
        await prober.run_cycle()
        wall = time.perf_counter() - t_wall0

    lat = sorted(metrics["latencies_sec"])
    return {
        "wall_seconds": wall,
        "request_count": metrics["request_count"],
        "peak_concurrent": metrics["peak_concurrent"],
        "latency_p50_sec": _percentile(lat, 50),
        "latency_p95_sec": _percentile(lat, 95),
        "latency_p99_sec": _percentile(lat, 99),
    }


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_probe_cycle_regression(request):
    """Runs ``ISOProber.run_cycle`` against a mock transport; fails if wall time regresses vs baseline."""
    http_conc = request.config.getoption("--bench-http-concurrency")
    poll_min = request.config.getoption("--bench-poll-interval-minutes")
    delay_ms = request.config.getoption("--bench-per-request-delay-ms")
    delay_sec = delay_ms / 1000.0

    # Median of 3 wall-clock samples (fresh pool each iteration so discovered URLs
    # do not collapse the probe list on subsequent runs).
    walls: list[float] = []
    last_metrics: dict = {}
    for _ in range(3):
        pool = FakePool()
        prober = _build_prober(pool, http_conc, poll_min)
        m = await _run_one_cycle(prober, delay_sec)
        walls.append(m["wall_seconds"])
        last_metrics = m
    walls.sort()
    median_wall = walls[1]

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    threshold_pct = float(baseline.get("regression_threshold_pct", 20))
    baseline_wall = float(baseline["wall_seconds_median"])
    max_wall = baseline_wall * (1.0 + threshold_pct / 100.0)

    assert median_wall <= max_wall, (
        f"Probe-cycle wall time regression: median={median_wall:.4f}s > "
        f"allowed {max_wall:.4f}s (baseline {baseline_wall:.4f}s + {threshold_pct}%)"
    )

    # Sanity: we exercised HEAD/GET traffic.
    assert last_metrics["request_count"] >= int(baseline.get("min_request_count", 10))
