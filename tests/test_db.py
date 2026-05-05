"""Tests for paperscout.db (mocked psycopg2 pool — no real PostgreSQL)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from paperscout.db import init_db, init_pool


@patch("paperscout.db.pg_pool.ThreadedConnectionPool")
def test_init_pool_defaults(mock_tp_class):
    mock_tp_class.return_value = MagicMock(name="pool")
    pool = init_pool("postgresql://localhost/db")
    mock_tp_class.assert_called_once_with(1, 10, "postgresql://localhost/db")
    assert pool is mock_tp_class.return_value


@patch("paperscout.db.pg_pool.ThreadedConnectionPool")
def test_init_pool_custom_sizes(mock_tp_class):
    mock_tp_class.return_value = MagicMock()
    pool = init_pool("postgresql://x", minconn=3, maxconn=15)
    mock_tp_class.assert_called_once_with(3, 15, "postgresql://x")
    assert pool is mock_tp_class.return_value


def test_init_db_executes_ddl_commits_putconn():
    pool = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = None
    conn.cursor.return_value = cm
    pool.getconn.return_value = conn

    init_db(pool)

    cur.execute.assert_called_once()
    ddl = cur.execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS paper_cache" in ddl
    assert "discovered_urls" in ddl
    assert "probe_miss_counts" in ddl
    assert "poll_state" in ddl
    assert "user_watchlist" in ddl
    conn.commit.assert_called_once()
    pool.putconn.assert_called_once_with(conn)


def test_init_db_putconn_even_when_execute_fails():
    pool = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = None
    conn.cursor.return_value = cm
    pool.getconn.return_value = conn
    cur.execute.side_effect = RuntimeError("DDL failed")

    with pytest.raises(RuntimeError, match="DDL failed"):
        init_db(pool)

    pool.putconn.assert_called_once_with(conn)
