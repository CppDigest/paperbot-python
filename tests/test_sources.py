"""Tests for paperbot.sources."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from paperbot.models import Paper
from paperbot.sources import (
    ISOProber,
    OpenStdEntry,
    ProbeHit,
    WG21Index,
    _fetch_front_text,
    _parse_open_std_html,
    scrape_open_std,
)
from paperbot.storage import ProbeState
from tests.conftest import SAMPLE_INDEX_DATA, make_test_settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data or {})
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _make_async_client(head_resp=None, get_resp=None) -> AsyncMock:
    client = AsyncMock()
    client.head = AsyncMock(return_value=head_resp or _make_response(404))
    client.get = AsyncMock(return_value=get_resp or _make_response(404))
    return client


# ── WG21Index ────────────────────────────────────────────────────────────────

class TestWG21Index:
    async def test_refresh_downloads_when_no_cache(self, tmp_path):
        index = WG21Index(tmp_path)
        with patch.object(index, "_download", AsyncMock(return_value=SAMPLE_INDEX_DATA)):
            papers = await index.refresh()
        assert "P2300R10" in papers
        assert "N4950" in papers

    async def test_refresh_uses_cache_when_fresh(self, tmp_path):
        index = WG21Index(tmp_path)
        index._cache.write(SAMPLE_INDEX_DATA)

        mock_download = AsyncMock()
        with patch.object(index, "_download", mock_download):
            papers = await index.refresh()
        mock_download.assert_not_called()
        assert "P2300R10" in papers

    async def test_refresh_falls_back_to_stale_cache(self, tmp_path):
        index = WG21Index(tmp_path)
        index._cache.write(SAMPLE_INDEX_DATA)
        index._cache.ttl_seconds = 0  # Make it stale

        with patch.object(index, "_download", AsyncMock(return_value=None)):
            papers = await index.refresh()
        assert "P2300R10" in papers

    async def test_refresh_returns_empty_when_no_data(self, tmp_path):
        index = WG21Index(tmp_path)
        with patch.object(index, "_download", AsyncMock(return_value=None)):
            papers = await index.refresh()
        assert papers == {}

    async def test_download_success(self, tmp_path):
        index = WG21Index(tmp_path)
        mock_resp = _make_response(200, json_data=SAMPLE_INDEX_DATA)
        mock_client = _make_async_client(get_resp=mock_resp)

        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await index._download()
        assert result == SAMPLE_INDEX_DATA

    async def test_download_non_dict_response(self, tmp_path):
        index = WG21Index(tmp_path)
        mock_resp = _make_response(200, json_data=[1, 2, 3])  # list, not dict
        mock_client = _make_async_client(get_resp=mock_resp)

        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await index._download()
        assert result is None

    async def test_download_http_error(self, tmp_path):
        index = WG21Index(tmp_path)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connect failed"))

        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await index._download()
        assert result is None

    def test_parse_and_index(self, tmp_path):
        index = WG21Index(tmp_path)
        papers = index._parse_and_index(SAMPLE_INDEX_DATA)
        assert "P2300R10" in papers
        assert "P2301R0" in papers
        assert "N4950" in papers

    def test_highest_p_number(self, populated_index):
        assert populated_index.highest_p_number() == 2301

    def test_latest_revision_known(self, populated_index):
        assert populated_index.latest_revision(2300) == 10

    def test_latest_revision_unknown(self, populated_index):
        assert populated_index.latest_revision(9999) is None

    def test_parse_ignores_non_dict_entries(self, tmp_path):
        index = WG21Index(tmp_path)
        raw = {"P1234R0": "not a dict", "P5678R0": {"title": "Real"}}
        papers = index._parse_and_index(raw)
        assert "P1234R0" not in papers
        assert "P5678R0" in papers


# ── _fetch_front_text ─────────────────────────────────────────────────────────

class TestFetchFrontText:
    async def test_returns_plain_text_on_success(self):
        html = "<html><body><p>Author: Eric Niebler</p></body></html>"
        mock_resp = _make_response(200, text=html)
        client = _make_async_client(get_resp=mock_resp)
        result = await _fetch_front_text(client, "D", 2300, 11)
        assert "Niebler" in result
        assert "<" not in result

    async def test_returns_empty_on_non_200(self):
        mock_resp = _make_response(404)
        client = _make_async_client(get_resp=mock_resp)
        result = await _fetch_front_text(client, "D", 2300, 11)
        assert result == ""

    async def test_returns_empty_on_http_error(self):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.HTTPError("timeout"))
        result = await _fetch_front_text(client, "D", 2300, 11)
        assert result == ""

    async def test_truncates_to_1000_words(self):
        # Build HTML with more than 1000 words
        words = " ".join(["word"] * 1500)
        html = f"<p>{words}</p>"
        mock_resp = _make_response(200, text=html)
        client = _make_async_client(get_resp=mock_resp)
        result = await _fetch_front_text(client, "D", 2300, 11)
        assert len(result.split()) <= 1000


# ── ISOProber: tier list builders ────────────────────────────────────────────

class TestISOProberTiers:
    def _make_prober(self, tmp_path, **cfg_overrides) -> tuple[ISOProber, WG21Index, ProbeState]:
        index = WG21Index(tmp_path)
        state = ProbeState(tmp_path / "state.json")
        cfg = make_test_settings(**cfg_overrides)
        prober = ISOProber(index, state, cfg=cfg)
        return prober, index, state

    def test_tier_a_empty_watchlist(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path, watchlist_papers=[])
        assert prober._tier_a() == []

    def test_tier_a_generates_urls(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            watchlist_papers=[2300],
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=2,
        )
        index._max_rev = {2300: 10}
        results = prober._tier_a()
        urls = [r[0] for r in results]
        tiers = [r[1] for r in results]
        assert all(t == "A" for t in tiers)
        assert any("D2300R10.pdf" in u for u in urls)
        assert any("D2300R11.pdf" in u for u in urls)

    def test_tier_a_unknown_revision(self, tmp_path):
        prober, _, _ = self._make_prober(
            tmp_path,
            watchlist_papers=[9999],
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_unknown_max_rev=1,
        )
        # No entry in index → latest_revision returns None → probe R0..R1
        results = prober._tier_a()
        revisions = [r[4] for r in results]
        assert 0 in revisions
        assert 1 in revisions

    def test_tier_b_generates_frontier_range(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            frontier_window_above=2,
            frontier_window_below=1,
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=1,
        )
        index._max_p = 100
        results = prober._tier_b()
        numbers = {r[3] for r in results}
        # Should include 100 (frontier), 101, 102 (above), and 99 (below)
        assert 100 in numbers
        assert 101 in numbers
        assert 102 in numbers

    def test_tier_b_includes_explicit_ranges(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            frontier_window_above=0,
            frontier_window_below=0,
            frontier_explicit_ranges=[{"min": 200, "max": 202}],
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=1,
        )
        index._max_p = 100
        results = prober._tier_b()
        numbers = {r[3] for r in results}
        assert 200 in numbers
        assert 201 in numbers
        assert 202 in numbers

    def test_tier_b_skips_backoff_numbers(self, tmp_path):
        prober, index, state = self._make_prober(
            tmp_path,
            frontier_window_above=2,
            frontier_window_below=0,
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=1,
            backoff_miss_threshold=1,
            backoff_multiplier=2,
            backoff_max_skip=48,
        )
        index._max_p = 100
        prober._cycle = 1  # odd cycle
        # Record enough misses on 101 to trigger backoff (>= threshold)
        state.record_miss("101")
        state.record_miss("101")
        results = prober._tier_b()
        numbers = {r[3] for r in results}
        assert 101 not in numbers

    def test_tier_c_recent_papers_included(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            tier_c_lookback_months=18,
            tier_c_probe_prefixes=["D"],
            tier_c_revision_depth=1,
        )
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        index.papers = {
            "P5000R2": Paper(id="P5000R2", date=recent_date),
        }
        index._max_rev = {5000: 2}
        results = prober._tier_c()
        numbers = {r[3] for r in results}
        assert 5000 in numbers

    def test_tier_c_old_papers_excluded(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            tier_c_lookback_months=1,
        )
        old_date = (date.today() - timedelta(days=365)).isoformat()
        index.papers = {"P5000R2": Paper(id="P5000R2", date=old_date)}
        index._max_rev = {5000: 2}
        results = prober._tier_c()
        numbers = {r[3] for r in results}
        assert 5000 not in numbers

    def test_tier_c_excludes_watchlist_papers(self, tmp_path):
        prober, index, _ = self._make_prober(
            tmp_path,
            watchlist_papers=[5000],
            tier_c_lookback_months=18,
        )
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        index.papers = {"P5000R2": Paper(id="P5000R2", date=recent_date)}
        index._max_rev = {5000: 2}
        results = prober._tier_c()
        numbers = {r[3] for r in results}
        assert 5000 not in numbers

    def test_tier_c_skips_papers_with_no_known_revision(self, tmp_path):
        prober, index, _ = self._make_prober(tmp_path, tier_c_lookback_months=18)
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        index.papers = {"P5001R0": Paper(id="P5001R0", date=recent_date)}
        index._max_rev = {}  # No known revision → latest_revision returns None
        results = prober._tier_c()
        numbers = {r[3] for r in results}
        assert 5001 not in numbers

    def test_tier_c_skips_backoff_numbers(self, tmp_path):
        prober, index, state = self._make_prober(
            tmp_path,
            tier_c_lookback_months=18,
            tier_c_probe_prefixes=["D"],
            tier_c_revision_depth=1,
            backoff_miss_threshold=1,
            backoff_multiplier=2,
            backoff_max_skip=48,
        )
        prober._cycle = 1
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        index.papers = {"P5005R2": Paper(id="P5005R2", date=recent_date)}
        index._max_rev = {5005: 2}
        # Add enough misses to trigger backoff (> threshold=1)
        state.record_miss("5005")
        state.record_miss("5005")
        results = prober._tier_c()
        numbers = {r[3] for r in results}
        assert 5005 not in numbers

    def test_tier_c_skips_invalid_dates(self, tmp_path):
        prober, index, _ = self._make_prober(tmp_path, tier_c_lookback_months=18)
        index.papers = {
            "P5002R1": Paper(id="P5002R1", date="unknown"),
            "P5003R1": Paper(id="P5003R1", date=""),
            "P5004R1": Paper(id="P5004R1", date="not-a-date"),
        }
        index._max_rev = {5002: 1, 5003: 1, 5004: 1}
        # Should not raise
        results = prober._tier_c()
        assert isinstance(results, list)

    def test_revisions_for_known(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path, probe_revision_depth=3)
        assert prober._revisions_for(5) == [5, 6, 7]

    def test_revisions_for_unknown(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path, probe_unknown_max_rev=2)
        assert prober._revisions_for(None) == [0, 1, 2]


# ── ISOProber: _probe_one ─────────────────────────────────────────────────────

class TestISOProberProbeOne:
    def _make_prober(self, tmp_path) -> tuple[ISOProber, WG21Index, ProbeState]:
        index = WG21Index(tmp_path)
        state = ProbeState(tmp_path / "state.json")
        cfg = make_test_settings()
        prober = ISOProber(index, state, cfg=cfg)
        prober._cycle = 1
        return prober, index, state

    async def test_skips_already_discovered(self, tmp_path):
        prober, _, state = self._make_prober(tmp_path)
        url = "https://isocpp.org/files/papers/D2300R11.pdf"
        state.mark_discovered(url)
        sem = asyncio.Semaphore(5)
        client = AsyncMock()
        result = await prober._probe_one(client, sem, url, "D", 2300, 11, ".pdf", "A")
        assert result is None
        client.head.assert_not_called()

    async def test_skips_already_in_index(self, tmp_path):
        prober, index, _ = self._make_prober(tmp_path)
        index.papers = {"D2300R11": Paper(id="D2300R11")}
        url = "https://isocpp.org/files/papers/D2300R11.pdf"
        sem = asyncio.Semaphore(5)
        client = AsyncMock()
        result = await prober._probe_one(client, sem, url, "D", 2300, 11, ".pdf", "A")
        assert result is None
        client.head.assert_not_called()

    async def test_returns_none_on_404(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path)
        url = "https://isocpp.org/files/papers/D9999R0.pdf"
        sem = asyncio.Semaphore(5)
        head_resp = _make_response(404)
        client = _make_async_client(head_resp=head_resp)
        result = await prober._probe_one(client, sem, url, "D", 9999, 0, ".pdf", "B")
        assert result is None

    async def test_returns_hit_on_200(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path)
        url = "https://isocpp.org/files/papers/D9999R0.pdf"
        sem = asyncio.Semaphore(5)
        head_resp = _make_response(200)
        get_resp = _make_response(200, text="<body>Author: Eric Niebler content here</body>")
        client = _make_async_client(head_resp=head_resp, get_resp=get_resp)
        result = await prober._probe_one(client, sem, url, "D", 9999, 0, ".pdf", "B")
        assert result is not None
        assert isinstance(result, ProbeHit)
        assert result.prefix == "D"
        assert result.number == 9999
        assert result.revision == 0
        assert result.tier == "B"

    async def test_handles_http_error(self, tmp_path):
        prober, _, _ = self._make_prober(tmp_path)
        url = "https://isocpp.org/files/papers/D9999R0.pdf"
        sem = asyncio.Semaphore(5)
        client = AsyncMock()
        client.head = AsyncMock(side_effect=httpx.HTTPError("timeout"))
        result = await prober._probe_one(client, sem, url, "D", 9999, 0, ".pdf", "B")
        assert result is None


# ── ISOProber: run_cycle ──────────────────────────────────────────────────────

class TestISOProberRunCycle:
    async def test_run_cycle_records_hit_and_updates_state(self, tmp_path):
        index = WG21Index(tmp_path)
        index._max_p = 100
        state = ProbeState(tmp_path / "state.json")
        cfg = make_test_settings(
            watchlist_papers=[9999],
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=1,
            probe_unknown_max_rev=0,
            frontier_window_above=0,
            frontier_window_below=0,
            tier_c_lookback_months=0,
        )
        prober = ISOProber(index, state, cfg=cfg)

        hit_url = "https://isocpp.org/files/papers/D9999R0.pdf"
        head_resp_hit = _make_response(200)
        get_resp = _make_response(200, text="<p>content</p>")

        async def mock_head(url, **kwargs):
            if url == hit_url:
                return head_resp_hit
            return _make_response(404)

        async def mock_get(url, **kwargs):
            return get_resp

        mock_client = AsyncMock()
        mock_client.head = mock_head
        mock_client.get = mock_get

        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            hits = await prober.run_cycle()

        assert any(h.number == 9999 for h in hits)
        assert state.is_discovered(hit_url)

    async def test_run_cycle_increments_miss_counters(self, tmp_path):
        index = WG21Index(tmp_path)
        index._max_p = 0
        state = ProbeState(tmp_path / "state.json")
        cfg = make_test_settings(
            watchlist_papers=[9998],
            probe_prefixes=["D"],
            probe_extensions=[".pdf"],
            probe_revision_depth=1,
            probe_unknown_max_rev=0,
            frontier_window_above=0,
            frontier_window_below=0,
            tier_c_lookback_months=0,
        )
        prober = ISOProber(index, state, cfg=cfg)

        mock_client = _make_async_client(head_resp=_make_response(404))
        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await prober.run_cycle()

        assert state.get_miss_count("9998") >= 1


# ── open-std.org scraper ─────────────────────────────────────────────────────

OPEN_STD_HTML = """
<table>
  <tr>
    <td><a href="P2300R10.pdf">P2300R10</a></td>
    <td>Senders and Receivers</td>
    <td>Eric Niebler</td>
    <td>2024-01-15</td>
    <td>Adopted</td>
    <td>SG1</td>
    <td>EWG</td>
  </tr>
  <tr>
    <td><a href="N4950.pdf">N4950</a></td>
    <td>Working Draft</td>
    <td>Thomas Köppe</td>
    <td>2023-05-15</td>
    <td></td>
    <td></td>
    <td>WG21</td>
  </tr>
</table>
"""


class TestOpenStdScraper:
    def test_parse_open_std_html(self):
        entries = _parse_open_std_html(OPEN_STD_HTML)
        assert len(entries) == 2
        assert entries[0].paper_id == "P2300R10"
        assert entries[0].title == "Senders and Receivers"
        assert entries[0].author == "Eric Niebler"
        assert entries[0].doc_date == "2024-01-15"
        assert entries[0].subgroup == "EWG"

    def test_parse_open_std_html_empty(self):
        assert _parse_open_std_html("") == []

    def test_parse_open_std_html_skips_short_rows(self):
        html = "<table><tr><td>only one cell</td></tr></table>"
        entries = _parse_open_std_html(html)
        assert entries == []

    def test_parse_open_std_html_skips_no_paper_link(self):
        html = "<table><tr><td>no link</td><td>title</td><td>author</td><td>2024</td></tr></table>"
        entries = _parse_open_std_html(html)
        assert entries == []

    async def test_scrape_open_std_success(self):
        mock_resp = _make_response(200, text=OPEN_STD_HTML)
        mock_client = _make_async_client(get_resp=mock_resp)
        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            entries = await scrape_open_std(2024)
        assert len(entries) == 2

    async def test_scrape_open_std_http_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("fail"))
        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            entries = await scrape_open_std(2024)
        assert entries == []

    async def test_scrape_open_std_uses_current_year_by_default(self):
        mock_resp = _make_response(200, text="<table></table>")
        mock_client = _make_async_client(get_resp=mock_resp)
        with patch("paperbot.sources.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await scrape_open_std()  # No year argument
        call_url = mock_client.get.call_args[0][0]
        assert str(date.today().year) in call_url
