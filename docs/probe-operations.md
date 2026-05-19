# ISO probe operations guide

This document describes the **production** isocpp.org HEAD probe cycle: normal volume, timing, configuration, and what to do when something degrades. For the **synthetic CI benchmark** (mock server), see [probe-performance.md](probe-performance.md).

## Normal envelope (default settings)

At default configuration (~4,000 active P-numbers, `HTTP_CONCURRENCY=20`, 30-minute poll interval):

| Metric | Typical value |
|--------|----------------|
| HEAD requests per cycle | **~1,600–2,000** |
| Wall-clock duration | **~8–10 s** (depends on isocpp.org latency) |
| Hot probes | Watchlist + frontier window + recent index papers — every cycle |
| Cold probes | **1 / `COLD_CYCLE_DIVISOR`** of the cold pool per cycle (default 48 → full tail in ~24 h) |

Each cycle logs **`PROBE-START`** (human-readable) and **`PROBE-CYCLE-SUMMARY`** (JSON) with `cycle_requests`, `hot_probes`, `cold_probes`, `cycle_duration_s`, and per-outcome counts.

Hot/cold split is **not a fixed ratio** — it varies with frontier size, watchlist, and index dates. Use `hot_probes` / `cold_probes` in the summary line to see the split for a given cycle.

## Key settings

> **Note:** Some issue templates refer to `POLL_INTERVAL_SECONDS`; the actual environment variable is **`POLL_INTERVAL_MINUTES`**.

| Variable | Default | Operational effect | Recommended range |
|----------|---------|-------------------|-------------------|
| `HTTP_CONCURRENCY` | `20` | Max concurrent HEAD requests (semaphore) | **10–20**; lower if you see 429s or high `errors` |
| `POLL_INTERVAL_MINUTES` | `30` | Target time between poll cycles | **30** default; **increase** if cycles routinely overrun the interval |
| `POLL_OVERRUN_COOLDOWN_SECONDS` | `300` | Minimum sleep after a cycle longer than the interval | **300** default; prevents tight loops when work backs up |
| `COLD_CYCLE_DIVISOR` | `48` | Cold pool sliced across N cycles (48 × 30 min ≈ 24 h) | Raise to spread load; lower for faster cold coverage |
| `ALERT_MODIFIED_HOURS` | `24` | Only alert on hits with recent `Last-Modified` | — |

See [`.env.example`](../.env.example) and the README env tables for frontier, hot, and cold tuning (`FRONTIER_WINDOW_*`, `HOT_LOOKBACK_MONTHS`, etc.).

## Degradation signals

| Signal | What it means |
|--------|----------------|
| `cycle_duration_s` > `POLL_INTERVAL_MINUTES` × 60 | Cycle **overrun** — scheduler applies `POLL_OVERRUN_COOLDOWN_SECONDS` before the next poll |
| No successful poll for **> 2 × `POLL_INTERVAL_MINUTES`** | Stale-poll ops alert (see `monitor.py`) — treat as incident |
| `errors / cycle_requests` **> 5%** for 2+ consecutive cycles | Network or upstream outage — check logs for `PROBE-ERR` |
| HTTP **429** from isocpp.org | Rate limiting — reduce concurrency and/or widen poll interval |

Parse **`PROBE-CYCLE-SUMMARY`** from logs (grep or log aggregator) for machine-readable fields: `hit_total`, `miss`, `errors`, `skipped_discovered`, `skipped_in_index`.

## What to do if…

### Cycle takes longer than the poll interval

1. Grep logs for `PROBE-CYCLE-SUMMARY` — note `cycle_duration_s` and `cycle_requests`.
2. If duration tracks request count, isocpp.org may be slow; consider lowering `HTTP_CONCURRENCY` slightly (less burst) or increasing `POLL_INTERVAL_MINUTES`.
3. Confirm `POLL_OVERRUN_COOLDOWN_SECONDS` is in effect (see `SCHEDULER-SLEEP` lines).

### Error rate exceeds 5%

1. Compute `errors / cycle_requests` from the last few `PROBE-CYCLE-SUMMARY` lines.
2. If sustained, check network and isocpp.org status; avoid raising `HTTP_CONCURRENCY` until errors drop.
3. Review `PROBE-ERR` debug lines for `failure_category` (timeout vs network).

### isocpp.org returns 429

1. Halve `HTTP_CONCURRENCY` (e.g. 20 → 10).
2. Increase `POLL_INTERVAL_MINUTES` (e.g. 30 → 45) to reduce sustained request rate.
3. Monitor `errors` and 429 patterns for several cycles before tuning back up.

## Related documentation

- [README — Two-Frequency Probing Strategy](../README.md#two-frequency-probing-strategy)
- [handoff.md](handoff.md) — design rationale
- [architecture.md](architecture.md) — concurrency model
- [probe-performance.md](probe-performance.md) — CI benchmark and regression gate
