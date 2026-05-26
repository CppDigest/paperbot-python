"""Tests for CycleResult invariants (w4_issue_01)."""

from __future__ import annotations

import pytest

from paperscout.models import CycleResult, CycleStatus, ProbeHit, Tier


def _hit() -> ProbeHit:
    return ProbeHit(
        url="https://isocpp.org/files/papers/D0001R0.pdf",
        prefix="D",
        number=1,
        revision=0,
        extension=".pdf",
        tier=Tier.COLD,
    )


def test_cycle_result_empty_valid():
    r = CycleResult(CycleStatus.EMPTY)
    assert r.hits == []
    assert r.error is None


def test_cycle_result_success_valid():
    h = _hit()
    r = CycleResult(CycleStatus.SUCCESS, results=(h,))
    assert r.hits == [h]


def test_cycle_result_failed_valid():
    r = CycleResult(CycleStatus.FAILED, error="timeout")
    assert r.hits == []
    assert r.error == "timeout"


@pytest.mark.parametrize(
    "status,results,error",
    [
        (CycleStatus.FAILED, (), None),
        (CycleStatus.FAILED, (), ""),
        (CycleStatus.SUCCESS, (), None),
        (CycleStatus.EMPTY, (_hit(),), None),
        (CycleStatus.SUCCESS, (), "oops"),
    ],
)
def test_cycle_result_invalid(status, results, error):
    with pytest.raises(ValueError):
        CycleResult(status, results=results, error=error)
