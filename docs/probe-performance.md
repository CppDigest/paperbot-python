# Probe cycle performance baseline

This document describes the **synthetic** probe-cycle benchmark under [`benchmarks/`](../benchmarks/). It does **not** hit isocpp.org; it uses `httpx.MockTransport` so CI and contributors get a stable, repeatable signal.

## What is measured

Each run executes `ISOProber.run_cycle()` with a small fixed index + watchlist (same shape as [`tests/test_sources.py`](../tests/test_sources.py) `TestISOProberRunCycle`). The mock server returns **200** with a recent `Last-Modified` header for every `HEAD`, and **200** HTML for `GET` when front text is fetched for recent hits (deterministic request counts for regression).

| Metric | Meaning |
|--------|---------|
| Wall seconds | Total time for one `run_cycle()` |
| Request count | Mock `HEAD` + `GET` calls |
| Peak concurrent | Max in-flight requests (bounded by `http_concurrency`) |
| Latency p50 / p95 / p99 | Per-request handler time in the mock |

## Baseline artifact

[`benchmarks/baseline.json`](../benchmarks/baseline.json) stores `wall_seconds_median` (with headroom for CI noise), `regression_threshold_pct` (default **20%**), and `min_request_count`.

The regression test takes the **median of three** wall-clock samples (each with a **fresh** in-memory DB pool so discovered URLs do not shrink the probe list between samples).

## Parameter knobs

Run locally:

```bash
uv run pytest benchmarks/ -m benchmark -v \
  --bench-http-concurrency=8 \
  --bench-poll-interval-minutes=30 \
  --bench-per-request-delay-ms=0.15
```

- **`--bench-http-concurrency`** — maps to `Settings.http_concurrency` (async client semaphore).  
- **`--bench-poll-interval-minutes`** — stored in `Settings.poll_interval_minutes` for parity with production config (the scheduler is not exercised here).  
- **`--bench-per-request-delay-ms`** — artificial delay inside the mock handler to simulate network latency.

## What is “normal” vs degraded

- **Normal:** The benchmark completes within `baseline.wall_seconds_median × (1 + threshold%)`.  
- **Degraded / investigate:** A sustained wall-clock increase **above that cap** after unrelated changes, or a large drop in `request_count` without intentional test changes (may indicate probes are being skipped earlier than expected).  
- **Not comparable:** Changing default benchmark CLI knobs or `baseline.json` without regenerating from a known-good tree.

## Updating the baseline

After an intentional performance change (or recalibrating mock delay defaults):

1. Temporarily relax or remove the assertion, or run the harness in a scratch script.  
2. Record stable median-of-three wall times with default CLI options on `ubuntu-latest` or locally.  
3. Set `wall_seconds_median` in `baseline.json` to a value with modest slack (e.g. 8–15× the raw median) so CI host variance does not flake.  
4. Commit `baseline.json` with the PR that justifies the new envelope.
