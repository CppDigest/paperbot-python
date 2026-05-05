# Maintainer handoff — paperscout

This document captures **design intent**, **operational gotchas**, and **deferred work** so a second maintainer can operate and extend the service without tribal knowledge. For step-by-step setup, see [onboarding.md](onboarding.md) and the [README](../README.md).

## Non-obvious design decisions

### 1. Two-frequency hot vs cold ISO probing

Every poll cycle could probe thousands of `isocpp.org` URLs. The prober splits P-numbers into:

- **Hot** — frontier band, watchlist numbers, and papers with recent index dates: probed **every** cycle so new D-drafts near the action surface quickly.
- **Cold** — the long tail: each number is visited on a **rotating slice** (`COLD_CYCLE_DIVISOR` cycles ≈ one full pass per day by default).

**Why:** Full HEAD sweep every 30 minutes would be noisy for operators and rough on isocpp.org; hot/cold keeps latency low where it matters while retaining eventual full coverage. See [README — Two-Frequency Probing Strategy](../README.md#two-frequency-probing-strategy).

### 2. HEAD-only probes and Last-Modified gating

ISO probing uses **HTTP HEAD**, not GET, to detect existence and metadata without downloading PDF/HTML bodies.

**Why HEAD:** Drafts can be large; bandwidth and server load stay bounded. Alerts use the **`Last-Modified`** header so old files discovered for the first time do not spam Slack; missing header is treated as “recent” (first discovery). Implemented in [`ISOProber`](../src/paperscout/sources.py) and summarized in [README — Alerting by Last-Modified](../README.md#alerting-by-last-modified).

### 3. D→P transition detection via stored probe state

When the wg21 index gains a **new P** row, the monitor checks whether a matching **D** URL was previously recorded in `discovered_urls`. If so, it emits a **D→P transition** for notification.

**Why:** The index alone does not tell you that _we_ saw the draft first; probe history is the bridge. Logic lives in [`monitor.py`](../src/paperscout/monitor.py) (`DPTransition` / `poll_once`).

### 4. Slack queue and HTTP 429

Outbound Slack messages go through a **background queue** (see [`scout.py`](../src/paperscout/scout.py)) so bursts from one poll do not violate Slack posting limits. The queue respects **HTTP 429** and `Retry-After`.

**Why:** Bolt handlers must stay responsive; rate limits are easier to reason about in one place than ad hoc sleeps in notifiers.

### 5. Watchlist DB work off the event loop

`poll_once` uses `asyncio.to_thread` for `user_watchlist.matches_for_users` because that path uses **synchronous psycopg2** I/O.

**Why:** Avoid blocking the asyncio loop during PostgreSQL-heavy match resolution while keeping a single-threaded pool model elsewhere.

## Operational gotchas

| Topic                 | What to know                                                                                                                                                                                                    |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **isocpp.org**        | Third-party availability and latency directly affect cycle time; long cycles increase sleep spacing via `POLL_OVERRUN_COOLDOWN_SECONDS` (see [onboarding — Scheduling](onboarding.md#scheduling-asyncio-loop)). |
| **HEAD volume**       | Typical **~1,600–2,000** HEAD requests per cycle at default settings (README architecture section). Tune `HTTP_CONCURRENCY` / windows if needed.                                                                |
| **Slack 429**         | Expected under burst; queue backs off using response headers — do not remove the queue “to simplify” without a replacement strategy.                                                                            |
| **Docker + Postgres** | Containers reach the host DB via `host.docker.internal`; Postgres must **listen** and **pg_hba** must allow the Docker bridge — [SERVER_SETUP.md](../deploy/SERVER_SETUP.md).                                   |
| **Logs vs DB**        | Rotating files under `DATA_DIR`; durable probe/index/watchlist state in **PostgreSQL** only.                                                                                                                    |

## Open TODOs and deferred items

- **`ENABLE_BULK_OPENSTD` / open-std.org** — Code paths exist in [`sources.py`](../src/paperscout/sources.py); bulk open-std scheduling is **not** integrated into the main poll loop yet (README notes “not yet scheduled”).
- **Eval / roadmap items** — If your org keeps a separate eval or ticket backlog, link it here; this repo does not ship a frozen “eval” document.

## Related documents

- [onboarding.md](onboarding.md) — linear setup for developers
- [CONTRIBUTING.md](../CONTRIBUTING.md) — PRs, hooks, releases
- [SECURITY.md](../SECURITY.md) — vulnerability reporting
