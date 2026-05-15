"""Entry point: python -m paperscout"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .db import init_db, init_pool
from .health import start_health_server
from .monitor import Scheduler
from .scout import (
    MessageQueue,
    create_app,
    enqueue_startup_status,
    notify_channel,
    notify_users,
    register_handlers,
)
from .sources import ISOProber, WG21Index
from .storage import ProbeState, UserWatchlist

log = logging.getLogger("paperscout")


def _setup_logging(data_dir: Path, console_level: str = "INFO", retention_days: int = 7) -> None:
    """Console + daily rotating file logging; third-party loggers capped at WARNING."""
    data_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-22s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.handlers.TimedRotatingFileHandler(
        filename=data_dir / "paperscout.log",
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
        utc=True,
    )
    fh.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    for lib in ("httpx", "httpcore", "slack_bolt", "slack_sdk", "urllib3", "psycopg2"):
        logging.getLogger(lib).setLevel(logging.WARNING)


async def _async_main() -> None:
    """Start DB, Slack app, health server, and the polling scheduler."""
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    _setup_logging(
        data_dir,
        console_level=settings.log_level,
        retention_days=settings.log_retention_days,
    )

    log.info(
        "=== Paperscout starting  port=%d  poll=%dmin  data=%s  log=%s ===",
        settings.port,
        settings.poll_interval_minutes,
        data_dir,
        data_dir / "paperscout.log",
    )
    log.info(
        "Settings: hot_lookback=%dmo  hot_depth=%d  cold_divisor=%d  "
        "alert_hours=%d  gap_max_rev=%d  frontier_gap=%d",
        settings.hot_lookback_months,
        settings.hot_revision_depth,
        settings.cold_cycle_divisor,
        settings.alert_modified_hours,
        settings.gap_max_rev,
        settings.frontier_gap_threshold,
    )

    if not settings.database_url:
        log.error("DATABASE_URL is not set — cannot start")
        sys.exit(1)

    launch_time = datetime.now(timezone.utc)

    pool = init_pool(settings.database_url)
    init_db(pool)

    state = ProbeState(pool)
    user_watchlist = UserWatchlist(pool)
    index = WG21Index(pool, cfg=settings)
    prober = ISOProber(index, state, user_watchlist)
    app = create_app()
    mq = MessageQueue(app)
    mq.start()

    def paper_count_fn() -> int:
        return len(index.papers)

    def _on_poll_result(result):
        notify_channel(app, result, mq)
        notify_users(app, result, mq)

    def _ops_alert(msg: str) -> None:
        if settings.ops_alert_channel:
            mq.enqueue(
                settings.ops_alert_channel,
                f":rotating_light: PaperScout alert: {msg}",
            )

    def _pool_status(p) -> dict:
        """Best-effort pool stats (psycopg2 ThreadedConnectionPool uses private attrs)."""
        status: dict = {"max": getattr(p, "maxconn", None)}
        try:
            status["in_use"] = len(p._used)
            status["available"] = len(p._pool)
        except AttributeError:
            status["in_use"] = None
            status["available"] = None
        return status

    scheduler = Scheduler(
        index=index,
        prober=prober,
        user_watchlist=user_watchlist,
        state=state,
        notify_callback=_on_poll_result,
        ops_alert_fn=_ops_alert,
    )

    def _extra_health_fields() -> dict:
        lsp = scheduler._last_successful_poll
        s = scheduler._last_probe_stats
        total = sum(s.get(k, 0) for k in ("hit_recent", "hit_old", "hit_no_lm", "miss", "error"))
        hit_rate = (s.get("hit_recent", 0) + s.get("hit_old", 0)) / total if total > 0 else None
        return {
            "last_successful_poll": (
                datetime.fromtimestamp(lsp, tz=timezone.utc).isoformat() if lsp else None
            ),
            "probe_hit_rate": hit_rate,
            "mq_depth": mq.depth(),
            "db_pool": _pool_status(pool),
        }

    register_handlers(app, user_watchlist, state, paper_count_fn, launch_time)

    start_health_server(
        settings.health_port,
        launch_time,
        state,
        paper_count_fn,
        bind_host=settings.health_bind_host,
        extra_fields_fn=_extra_health_fields,
    )
    log.info("Starting Slack Bolt app on port %d", settings.port)
    bolt_thread = threading.Thread(
        target=app.start,
        kwargs={"port": settings.port},
        daemon=True,
    )
    bolt_thread.start()

    enqueue_startup_status(mq, state, paper_count_fn)

    await scheduler.run_forever()


def main() -> None:
    """CLI entry: run ``_async_main`` until interrupt."""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        log.info("=== Paperscout shutting down (KeyboardInterrupt) ===")
        sys.exit(0)


if __name__ == "__main__":
    main()
