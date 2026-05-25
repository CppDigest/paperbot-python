# PaperScout architecture — concurrency

This document describes what runs on the asyncio event loop, what runs in threads, and how to add new data sources without introducing races.

## Event loop (async, cooperative single-thread)

These components share one thread and the main event loop. They may await I/O but must not block the loop with synchronous work:

- **`Scheduler.run_forever` / `poll_once`** — orchestrates index refresh, probing, and notifications.
- **`WG21Index.refresh`** — fetches and parses wg21.link index (httpx async).
- **`ISOProber.run_cycle` / `_probe_one`** — concurrent HEAD probes via `asyncio.gather` and an httpx async client. `run_cycle` returns a discriminated `CycleResult` (success / empty / failed).
- **Slack Bolt handlers** — run on Bolt’s thread; they should not read mutable source state directly (use snapshots or health callbacks).

`ISOProber._stats` is updated from many coroutines in one `run_cycle()`. This is safe on the event loop because asyncio never preempts between awaits. A `threading.Lock` guards `_stats` as defense-in-depth if code is ever called from a worker thread by mistake.

## Threads

| Thread | Role |
|--------|------|
| **Health server** (`health.py`) | Serves `GET /health`; reads `len(index.papers)` via a callback and scheduler fields from `Scheduler.health_snapshot()` (immutable snapshot, lock-protected publish). |
| **MessageQueue sender** (`scout.py`) | Drains Slack post queue with rate limiting. |
| **`run_blocking_io` / `asyncio.to_thread`** | Runs blocking psycopg2 calls (e.g. `UserWatchlist.matches_for_users`) off the loop. |

## Concurrency rules

When adding or changing code:

1. **Use `run_blocking_io()` (or `asyncio.to_thread`) only for pure blocking I/O** with no shared in-process mutable state. The function should use its own DB connection from the pool.
2. **Never access `ISOProber._stats`, `WG21Index.papers`, `WG21Index._max_rev`, or other source internals from a thread.** Read them only on the event loop, or use lock-protected snapshots (`snapshot_stats()`).
3. **`WG21Index.papers` is replaced wholesale on every `refresh()`** — do not mutate the dict in place. Assign a new dict from `_parse_and_index()`.
4. **New HTTP data sources** should follow the async pattern (`httpx` + coroutines on the loop), like `WG21Index` and `ISOProber`. The optional open-std.org scraper in `sources.py` is a future extension point: if integrated, either keep it async on the loop or isolate it in a thread with no shared mutable state.

## Related docs

- [probe-operations.md](probe-operations.md) — production probe volume, tuning, troubleshooting.
- [probe-performance.md](probe-performance.md) — synthetic CI benchmark (mock server, not isocpp.org).
