"""Pytest configuration for probe-cycle benchmarks (not collected with default ``tests/``)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Benchmarks do not load ``tests/conftest.py``; mirror slack/test env so ``paperscout.config`` can import.
os.environ.setdefault("_PAPERSCOUT_TESTING", "1")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-benchmark")
os.environ.setdefault("SLACK_SIGNING_SECRET", "benchmark-secret")

import pytest

# Repo root so ``from tests.conftest import ...`` resolves when only ``benchmarks/`` is targeted.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--bench-http-concurrency",
        type=int,
        default=5,
        help="HTTP concurrency cap for ISOProber during benchmark (maps to Settings.http_concurrency).",
    )
    parser.addoption(
        "--bench-poll-interval-minutes",
        type=int,
        default=30,
        help="Settings.poll_interval_minutes (recorded in metrics; scheduler not exercised here).",
    )
    parser.addoption(
        "--bench-per-request-delay-ms",
        type=float,
        default=0.15,
        help="Simulated server delay per HEAD/GET in the mock transport (milliseconds).",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "benchmark: probe cycle performance / regression (run via ``pytest benchmarks/ -m benchmark``).",
    )


@pytest.fixture
def fake_pool():
    """Fresh in-memory pool (same as ``tests/conftest``)."""
    from tests.conftest import FakePool

    return FakePool()
