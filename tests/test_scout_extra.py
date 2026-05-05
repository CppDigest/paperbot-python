"""Additional scout notification and helper coverage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from paperscout.monitor import DiffResult, PerUserMatches, PollResult
from paperscout.scout import _batch_lines, notify_channel, notify_users
from tests.test_scout import _make_result


class TestNotifyUsersEmptyInner:
    def test_skips_user_when_both_match_lists_empty(self):
        app = MagicMock()
        mq = MagicMock()
        pum = PerUserMatches(papers=[], probe_hits=[])
        result = PollResult(
            diff=DiffResult(new_papers=[], updated_papers=[]),
            probe_hits=[],
            per_user_matches={"U1": pum},
        )
        notify_users(app, result, mq)
        mq.enqueue.assert_not_called()


class TestNotifyChannelEarlyExit:
    def test_returns_when_notification_channel_empty(self):
        app = MagicMock()
        mq = MagicMock()
        result = _make_result()
        with patch("paperscout.scout.settings") as st:
            st.notification_channel = ""
            notify_channel(app, result, mq)
        mq.enqueue.assert_not_called()


class TestBatchLinesBoundary:
    def test_two_lines_stay_one_batch_when_under_limit(self):
        batches = _batch_lines(["aa", "bb"], max_len=100)
        assert len(batches) == 1

    def test_splits_when_combined_exceeds_limit(self):
        # Each line is len 80; with newlines the second batch begins when over max_len
        lines = ["n" * 80, "m" * 80]
        batches = _batch_lines(lines, max_len=120)
        assert len(batches) >= 2

    def test_single_oversize_line_still_one_batch(self):
        batches = _batch_lines(["z" * 500], max_len=100)
        assert len(batches) == 1
