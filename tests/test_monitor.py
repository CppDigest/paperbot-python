"""Tests for paperbot.monitor."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paperbot.models import Paper
from paperbot.monitor import (
    DiffResult,
    PollResult,
    Scheduler,
    Watchlist,
    diff_snapshots,
)
from paperbot.sources import ISOProber, ProbeHit, WG21Index
from paperbot.storage import ProbeState
from tests.conftest import make_test_settings


# ── Watchlist ─────────────────────────────────────────────────────────────────

class TestWatchlist:
    def test_initial_empty(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.authors == []

    def test_add_author(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.add_author("Niebler") is True
        assert "niebler" in wl.authors

    def test_add_author_duplicate_returns_false(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Niebler")
        assert wl.add_author("Niebler") is False
        assert wl.authors.count("niebler") == 1

    def test_add_author_case_insensitive_dedup(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("NIEBLER")
        assert wl.add_author("niebler") is False

    def test_add_empty_string_returns_false(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.add_author("") is False
        assert wl.add_author("   ") is False

    def test_remove_author(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Niebler")
        assert wl.remove_author("Niebler") is True
        assert "niebler" not in wl.authors

    def test_remove_nonexistent_returns_false(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        assert wl.remove_author("Nobody") is False

    def test_persists_to_file(self, tmp_path):
        path = tmp_path / "wl.json"
        wl = Watchlist(path)
        wl.add_author("Stroustrup")
        # Load a fresh instance
        wl2 = Watchlist(path)
        assert "stroustrup" in wl2.authors

    def test_loads_from_existing_file(self, tmp_path):
        import json
        path = tmp_path / "wl.json"
        path.write_text(json.dumps({"authors": ["baker", "niebler"]}), encoding="utf-8")
        wl = Watchlist(path)
        assert "baker" in wl.authors
        assert "niebler" in wl.authors

    def test_corrupt_file_starts_empty(self, tmp_path):
        path = tmp_path / "wl.json"
        path.write_text("not json", encoding="utf-8")
        wl = Watchlist(path)
        assert wl.authors == []

    def test_matches_paper_author(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Niebler")
        paper = Paper(id="P2300R10", author="Eric Niebler")
        matches = wl.matches(paper)
        assert "niebler" in matches

    def test_matches_no_author(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Niebler")
        paper = Paper(id="P2300R10", author="")
        assert wl.matches(paper) == []

    def test_matches_empty_watchlist(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        paper = Paper(id="P2300R10", author="Eric Niebler")
        assert wl.matches(paper) == []

    def test_authors_returns_copy(self, tmp_path):
        wl = Watchlist(tmp_path / "wl.json")
        wl.add_author("Test")
        authors = wl.authors
        authors.clear()
        assert "test" in wl.authors  # Internal state unaffected


# ── diff_snapshots ────────────────────────────────────────────────────────────

class TestDiffSnapshots:
    def _paper(self, pid, **kwargs) -> Paper:
        defaults = dict(title="T", author="A", date="2024-01-01")
        defaults.update(kwargs)
        return Paper(id=pid, **defaults)

    def test_new_paper_detected(self):
        prev = {}
        curr = {"P2300R10": self._paper("P2300R10")}
        result = diff_snapshots(prev, curr)
        assert len(result.new_papers) == 1
        assert result.new_papers[0].id == "P2300R10"
        assert result.updated_papers == []

    def test_updated_paper_detected_title_change(self):
        old = self._paper("P2300R10", title="Old Title")
        new = self._paper("P2300R10", title="New Title")
        result = diff_snapshots({"P2300R10": old}, {"P2300R10": new})
        assert result.new_papers == []
        assert len(result.updated_papers) == 1

    def test_updated_paper_detected_author_change(self):
        old = self._paper("P2300R10", author="Old")
        new = self._paper("P2300R10", author="New")
        result = diff_snapshots({"P2300R10": old}, {"P2300R10": new})
        assert len(result.updated_papers) == 1

    def test_updated_paper_detected_date_change(self):
        old = self._paper("P2300R10", date="2024-01-01")
        new = self._paper("P2300R10", date="2024-06-01")
        result = diff_snapshots({"P2300R10": old}, {"P2300R10": new})
        assert len(result.updated_papers) == 1

    def test_updated_paper_detected_long_link_change(self):
        old = Paper(id="P2300R10", long_link="old.pdf")
        new = Paper(id="P2300R10", long_link="new.pdf")
        result = diff_snapshots({"P2300R10": old}, {"P2300R10": new})
        assert len(result.updated_papers) == 1

    def test_unchanged_paper_not_reported(self):
        paper = self._paper("P2300R10")
        result = diff_snapshots({"P2300R10": paper}, {"P2300R10": paper})
        assert result.new_papers == []
        assert result.updated_papers == []

    def test_removed_paper_not_in_diff(self):
        old = {"P2300R10": self._paper("P2300R10"), "P2301R0": self._paper("P2301R0")}
        curr = {"P2300R10": self._paper("P2300R10")}
        result = diff_snapshots(old, curr)
        assert result.new_papers == []
        assert result.updated_papers == []

    def test_new_papers_sorted_by_date_descending(self):
        prev = {}
        curr = {
            "P2300R10": self._paper("P2300R10", date="2024-01-01"),
            "P2301R0": self._paper("P2301R0", date="2024-06-01"),
            "P2302R0": self._paper("P2302R0", date="2024-03-01"),
        }
        result = diff_snapshots(prev, curr)
        dates = [p.date for p in result.new_papers]
        assert dates == sorted(dates, reverse=True)

    def test_empty_to_empty(self):
        result = diff_snapshots({}, {})
        assert result.new_papers == []
        assert result.updated_papers == []


# ── PollResult ────────────────────────────────────────────────────────────────

class TestPollResult:
    def test_default_probe_watchlist_hits(self):
        diff = DiffResult(new_papers=[], updated_papers=[])
        result = PollResult(diff=diff, probe_hits=[], watchlist_matches=[])
        assert result.probe_watchlist_hits == []

    def test_explicit_probe_watchlist_hits(self):
        hit = ProbeHit(url="u", prefix="D", number=1, revision=0, extension=".pdf", tier="A")
        diff = DiffResult(new_papers=[], updated_papers=[])
        result = PollResult(
            diff=diff, probe_hits=[], watchlist_matches=[],
            probe_watchlist_hits=[hit],
        )
        assert len(result.probe_watchlist_hits) == 1


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _make_scheduler(tmp_path, **cfg_overrides):
    index = MagicMock(spec=WG21Index)
    index.refresh = AsyncMock()
    index.papers = {}
    prober = MagicMock(spec=ISOProber)
    prober.run_cycle = AsyncMock(return_value=[])
    watchlist = Watchlist(tmp_path / "wl.json")
    state = ProbeState(tmp_path / "state.json")
    cfg = make_test_settings(**cfg_overrides)
    scheduler = Scheduler(
        index=index, prober=prober,
        watchlist=watchlist, state=state, cfg=cfg,
    )
    return scheduler, index, prober, watchlist, state


class TestScheduler:
    async def test_poll_once_seeds_on_first_call(self, tmp_path):
        scheduler, index, prober, _, state = _make_scheduler(tmp_path)
        result = await scheduler.poll_once()
        index.refresh.assert_called_once()
        prober.run_cycle.assert_called_once()
        assert scheduler._seeded

    async def test_poll_once_seeded_returns_empty_diff_on_seed(self, tmp_path):
        scheduler, _, _, _, _ = _make_scheduler(tmp_path)
        result = await scheduler.poll_once()
        assert result.diff.new_papers == []
        assert result.diff.updated_papers == []

    async def test_poll_once_detects_new_papers(self, tmp_path):
        scheduler, index, prober, _, _ = _make_scheduler(tmp_path)
        # Seed first
        await scheduler.poll_once()

        # Now simulate new papers appearing
        new_paper = Paper(id="P9999R0", title="New", author="Author", date="2024-01-01")
        index.papers = {"P9999R0": new_paper}
        prober.run_cycle = AsyncMock(return_value=[])

        result = await scheduler.poll_once()
        assert len(result.diff.new_papers) == 1
        assert result.diff.new_papers[0].id == "P9999R0"

    async def test_poll_once_detects_watchlist_match(self, tmp_path):
        scheduler, index, prober, watchlist, _ = _make_scheduler(tmp_path)
        watchlist.add_author("niebler")
        # Seed first
        await scheduler.poll_once()

        new_paper = Paper(id="P9999R0", title="Senders", author="Eric Niebler", date="2024-01-01")
        index.papers = {"P9999R0": new_paper}
        prober.run_cycle = AsyncMock(return_value=[])

        result = await scheduler.poll_once()
        assert len(result.watchlist_matches) == 1

    async def test_poll_once_detects_probe_watchlist_hit(self, tmp_path):
        scheduler, index, prober, watchlist, _ = _make_scheduler(tmp_path)
        watchlist.add_author("niebler")
        await scheduler.poll_once()

        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D9999R0.pdf",
            prefix="D", number=9999, revision=0, extension=".pdf",
            tier="B", front_text="this is by eric niebler",
        )
        prober.run_cycle = AsyncMock(return_value=[hit])
        index.papers = {}

        result = await scheduler.poll_once()
        assert len(result.probe_watchlist_hits) == 1

    async def test_poll_once_filters_already_known_probe_hits(self, tmp_path):
        scheduler, index, prober, _, _ = _make_scheduler(tmp_path)
        await scheduler.poll_once()

        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D2300R11.pdf",
            prefix="D", number=2300, revision=11, extension=".pdf",
            tier="A",
        )
        # Paper is already in the previous snapshot → should be filtered out
        index.papers = {"D2300R11": Paper(id="D2300R11")}
        scheduler._previous_papers = {"D2300R11": Paper(id="D2300R11")}
        prober.run_cycle = AsyncMock(return_value=[hit])

        result = await scheduler.poll_once()
        assert len(result.probe_hits) == 0

    async def test_poll_once_calls_notify_callback(self, tmp_path):
        notified = []
        scheduler, _, _, _, _ = _make_scheduler(tmp_path)
        scheduler.notify_callback = notified.append
        await scheduler.poll_once()  # seed
        await scheduler.poll_once()  # real poll
        assert len(notified) == 1

    async def test_poll_once_skips_refresh_when_disabled(self, tmp_path):
        scheduler, index, _, _, _ = _make_scheduler(tmp_path, enable_bulk_wg21=False)
        scheduler._seeded = True
        scheduler._previous_papers = {}
        await scheduler.poll_once()
        index.refresh.assert_not_called()

    async def test_poll_once_skips_probe_when_disabled(self, tmp_path):
        scheduler, _, prober, _, _ = _make_scheduler(tmp_path, enable_iso_probe=False)
        scheduler._seeded = True
        scheduler._previous_papers = {}
        await scheduler.poll_once()
        prober.run_cycle.assert_not_called()

    async def test_seed_marks_discovered(self, tmp_path):
        scheduler, index, prober, _, state = _make_scheduler(tmp_path)
        hit = ProbeHit(
            url="https://isocpp.org/files/papers/D1234R0.pdf",
            prefix="D", number=1234, revision=0, extension=".pdf", tier="A",
        )
        prober.run_cycle = AsyncMock(return_value=[hit])
        await scheduler.seed()
        assert state.is_discovered(hit.url)

    async def test_run_forever_calls_poll_and_sleeps(self, tmp_path):
        scheduler, _, _, _, _ = _make_scheduler(tmp_path)
        call_count = 0

        async def mock_poll_once():
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()
            return MagicMock()

        scheduler.poll_once = mock_poll_once
        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_forever()
        assert call_count == 1

    async def test_run_forever_continues_after_poll_exception(self, tmp_path):
        scheduler, _, _, _, _ = _make_scheduler(tmp_path, poll_interval_minutes=0)
        call_count = 0

        async def mock_poll_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("poll failed")
            raise asyncio.CancelledError()

        async def mock_sleep(_):
            pass

        scheduler.poll_once = mock_poll_once
        with patch("asyncio.sleep", mock_sleep):
            with pytest.raises(asyncio.CancelledError):
                await scheduler.run_forever()
        assert call_count == 2
