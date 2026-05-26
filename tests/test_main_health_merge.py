"""Tests for __main__ health field merge helpers."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from paperscout.__main__ import _merge_extra_health_fields, _mq_health_fields
from paperscout.scout import MessageQueue


def test_merge_scheduler_wins_on_key_conflict(caplog):
    scheduler = {
        "last_updated": "2026-01-01T00:00:00+00:00",
        "poll_count": 1,
        "last_cycle_status": "empty",
    }
    mq_extra = {
        "mq_depth": 5,
        "last_updated": "should-not-win",
        "poll_count": 99,
    }
    with caplog.at_level(logging.DEBUG, logger="paperscout"):
        out = _merge_extra_health_fields(scheduler, mq_extra, {"max": 10})
    assert out["last_updated"] == "2026-01-01T00:00:00+00:00"
    assert out["poll_count"] == 1
    assert out["mq_depth"] == 5
    assert out["db_pool"] == {"max": 10}
    assert any("not allow-listed" in r.message for r in caplog.records)


def test_merge_drops_unknown_mq_keys(caplog):
    scheduler = {"last_updated": None, "poll_count": 0}
    mq_extra = {"mq_depth": 1, "evil_key": True}
    with caplog.at_level(logging.DEBUG, logger="paperscout"):
        out = _merge_extra_health_fields(scheduler, mq_extra, {})
    assert out["mq_depth"] == 1
    assert "evil_key" not in out
    assert any("not allow-listed" in r.message for r in caplog.records)


def test_mq_health_fields_uses_health_fields_method():
    mq = MessageQueue(MagicMock())
    fields = _mq_health_fields(mq)
    assert fields == mq.health_fields()
    assert fields["mq_depth"] == 0
    assert fields["mq_circuit_state"] == "closed"
    assert fields["mq_utilization"] == 0.0


def test_merge_includes_allowlisted_mq_fields():
    scheduler = {"last_updated": None, "poll_count": 0}
    mq_extra = {
        "mq_depth": 2,
        "mq_max_size": 1000,
        "mq_utilization": 0.002,
        "mq_circuit_state": "closed",
    }
    out = _merge_extra_health_fields(scheduler, mq_extra, {})
    assert out["mq_depth"] == 2
    assert out["mq_max_size"] == 1000
