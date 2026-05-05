# Onboarding — paperscout

This guide is ordered so a new developer can **run the test suite** and **start the service locally** without reading the whole [README](../README.md) first. For Slack app setup, production deploy, and deep architecture, follow links from each section.

## Prerequisites

- **Python** 3.10, 3.11, or 3.12 (`requires-python` in [pyproject.toml](../pyproject.toml))
- **PostgreSQL** (local or remote) — the app stores all durable state in Postgres
- **Git**
- Optional: **Docker** + Docker Compose for containerized runs (see [Deployment](#deployment))

## Repository layout

| Path | Role |
| ---- | ---- |
| [`src/paperscout/__init__.py`](../src/paperscout/__init__.py) | Package marker / version surface for the distribution. |
| [`src/paperscout/__main__.py`](../src/paperscout/__main__.py) | Entry point for `python -m paperscout`: logging, DB pool, Slack app, health server, async scheduler. |
| [`src/paperscout/config.py`](../src/paperscout/config.py) | Pydantic `Settings` — all configuration from environment / `.env`. |
| [`src/paperscout/models.py`](../src/paperscout/models.py) | `Paper` dataclass and enums for paper IDs, types, and file extensions. |
| [`src/paperscout/sources.py`](../src/paperscout/sources.py) | `WG21Index` (index fetch + cache), `ISOProber` (async HEAD probing of isocpp.org), open-std scraper hooks. |
| [`src/paperscout/monitor.py`](../src/paperscout/monitor.py) | `Scheduler`, index diffing, D→P transition detection, per-user watchlist match orchestration. |
| [`src/paperscout/scout.py`](../src/paperscout/scout.py) | Slack Bolt app, message queue, channel/DM notifications, command handlers. |
| [`src/paperscout/storage.py`](../src/paperscout/storage.py) | PostgreSQL-backed paper cache, probe state, and per-user watchlists. |
| [`src/paperscout/db.py`](../src/paperscout/db.py) | Connection pool setup and schema DDL. |
| [`src/paperscout/health.py`](../src/paperscout/health.py) | Small HTTP server exposing `GET /health` for orchestration and CD checks. |

Supporting directories: [`tests/`](../tests/) (pytest), [`deploy/`](../deploy/) (nginx sample + server provisioning), [`.github/workflows/`](../.github/workflows/) (CI/CD).

## Local development

### 1. Clone and virtual environment

```bash
git clone https://github.com/cppalliance/paperscout-python.git
cd paperscout-python
python -m venv .venv
source .venv/bin/activate   # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
```

### 2. PostgreSQL

Create a database and user (example names; adjust as needed):

```sql
CREATE USER paperscout WITH PASSWORD 'your-secret';
CREATE DATABASE paperscout OWNER paperscout;
```

Full host provisioning (listen addresses, `pg_hba.conf`, Docker bridge) is in [deploy/SERVER_SETUP.md](../deploy/SERVER_SETUP.md) (especially §3 and “Allow Docker containers to connect”).

### 3. Environment file

```bash
cp .env.example .env
```

**Minimum to run the process** (Slack endpoints will not work until tokens and signing secret are set):

- `DATABASE_URL` — e.g. `postgresql://paperscout:your-secret@localhost:5432/paperscout`
- For Slack: `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` — see [README § Slack App Setup](../README.md#slack-app-setup)

### 4. Run tests

Fast run (no coverage gate):

```bash
./run test
# or: make test
# or: python -m pytest tests/ -v
```

Same checks as CI, including the **90% coverage** floor:

```bash
./run check
# or: make check
```

CI configuration: [.github/workflows/ci.yml](../.github/workflows/ci.yml) (Python 3.10–3.12 on `ubuntu-latest`, `main` only).

### 5. Code quality hooks (recommended)

Install [pre-commit](https://pre-commit.com/) hooks after `pip install -e ".[dev]"`:

```bash
pre-commit install
pre-commit run --all-files
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for PR expectations.

## Run the service locally

```bash
python -m paperscout
```

- **Slack HTTP app** listens on `PORT` (default **3000**).
- **Health** endpoint listens on `health_port` from settings (default **8080**) — `GET /health`.

For Slack Event Subscriptions you need a public URL (e.g. ngrok); see [README](../README.md#7-set-the-request-url).

## Deployment (summary)

Production-style flow:

1. Configure `.env` on the server (or use `env_file` in Compose).
2. Build and start:

   ```bash
   docker compose up -d --build
   ```

3. Health check from the host (see [docker-compose.yml](../docker-compose.yml) port mappings):

   - App (Slack): `127.0.0.1:9100` → container `3000`
   - Health: `127.0.0.1:9101` → container `8080` → e.g. `curl -sf http://127.0.0.1:9101/health`

Full CD narrative, GitHub Environments, and branch mapping: [README — Deployment](../README.md#deployment).

## nginx

Use [deploy/paperscout.conf](../deploy/paperscout.conf) as a reference for TLS termination and proxying `443` → app `3000`, with `/health` routed to the health port. Step-by-step integration with an existing site is in [deploy/SERVER_SETUP.md](../deploy/SERVER_SETUP.md) (§4 nginx + TLS).

## Environment variables (complete reference)

Every key from [`.env.example`](../.env.example) is listed below. Names in `.env` use **SCREAMING_SNAKE_CASE**; the runtime [Settings](../src/paperscout/config.py) class maps them to lowercase fields.

### Slack and server

| Variable | Required | Default / example | Meaning |
| -------- | -------- | ----------------- | ------- |
| `SLACK_SIGNING_SECRET` | Yes (for Slack) | — | Slack app signing secret; verifies incoming requests. |
| `SLACK_BOT_TOKEN` | Yes (for Slack) | — | Bot User OAuth token (`xoxb-…`). |
| `PORT` | No | `3000` | Port for the Slack Bolt HTTP listener. |

### Database

| Variable | Required | Meaning |
| -------- | -------- | ------- |
| `DATABASE_URL` | Yes | PostgreSQL DSN, e.g. `postgresql://user:pass@host:5432/paperscout`. In Docker against host Postgres, `host.docker.internal` is typical (see `.env.example`). |

### Scheduling and sources

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `POLL_INTERVAL_MINUTES` | `30` | Target wall-clock spacing between poll cycles (see [Scheduling](#scheduling-asyncio-loop) below). |
| `POLL_OVERRUN_COOLDOWN_SECONDS` | `300` | **Minimum** sleep after any cycle that ran longer than one interval — avoids hammering the network if a cycle overruns. |
| `ENABLE_BULK_WG21` | `true` | Fetch and parse wg21.link index each cycle when enabled. |
| `ENABLE_BULK_OPENSTD` | `true` | Reserved for open-std.org bulk fetch (not yet wired into the scheduler). |
| `ENABLE_ISO_PROBE` | `true` | Run isocpp.org HEAD probing each cycle when enabled. |

### Probe prefixes / extensions

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `PROBE_PREFIXES` | `["D","P"]` | JSON list of URL prefixes for gap / unknown numbers. |
| `PROBE_EXTENSIONS` | `[".pdf",".html"]` | JSON list of file extensions to probe. |

### Frontier

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `FRONTIER_WINDOW_ABOVE` | `60` | How many P-numbers above the effective frontier to treat as hot each cycle. |
| `FRONTIER_WINDOW_BELOW` | `30` | How many below the frontier window. |
| `FRONTIER_EXPLICIT_RANGES` | `[]` | JSON list of `{"min": n, "max": m}` extra hot ranges. |
| `FRONTIER_GAP_THRESHOLD` | `50` | Max gap between consecutive P-numbers before a number is treated as an outlier for frontier calculation. |

### Hot / cold probing

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `HOT_LOOKBACK_MONTHS` | `6` | Papers with index dates in this window are probed every cycle (hot). |
| `HOT_REVISION_DEPTH` | `2` | Extra revision indices ahead of the known latest for hot numbers. |
| `COLD_REVISION_DEPTH` | `1` | Revisions ahead of known latest for cold pool. |
| `COLD_CYCLE_DIVISOR` | `48` | Cold pool split into this many slices; one slice per cycle (48×30 min ≈ 24 h full sweep). |
| `GAP_MAX_REV` | `1` | For gap/unknown numbers, probe revisions `R0` … `R` this value. |

### Alerting and HTTP client

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `ALERT_MODIFIED_HOURS` | `24` | Only Slack-notify probe hits whose `Last-Modified` is within this many hours (see README). |
| `HTTP_CONCURRENCY` | `20` | Max concurrent async HTTP requests for probing. |
| `HTTP_TIMEOUT_SECONDS` | `10` | Per-request timeout. |
| `HTTP_USE_HTTP2` | `true` | Use HTTP/2 where supported. |

### Notifications

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `NOTIFICATION_CHANNEL` | empty | Slack channel ID for shared alerts (frontier, D→P, etc.); empty disables channel posts. |
| `NOTIFY_ON_FRONTIER_HIT` | `true` | Notify on recent draft hits near the frontier. |
| `NOTIFY_ON_ANY_DRAFT` | `true` | Notify on other recent draft hits. |
| `NOTIFY_ON_DP_TRANSITION` | `true` | Notify when a tracked D URL’s paper appears as P in the index. |

### Storage and logging

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `DATA_DIR` | `./data` | Log directory (and local file layout); created if missing. |
| `CACHE_TTL_HOURS` | `1` | Staleness window for cached wg21 index blob in Postgres. |
| `LOG_LEVEL` | `INFO` | Console/file log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LOG_RETENTION_DAYS` | `7` | Days of rotated log files to retain. |

**Note:** `health_port` (default `8080`) exists in [Settings](../src/paperscout/config.py) but is not in `.env.example`; set `HEALTH_PORT` only if you add it to settings or extend `.env.example` in the future.

## Scheduling (asyncio loop)

The [`Scheduler`](../src/paperscout/monitor.py) runs inside the same asyncio event loop as the HTTP clients:

1. **`seed()`** (first cycle only): loads the wg21 index if enabled, snapshots papers, optionally runs one ISO probe pass and records discoveries — **no Slack notifications** on this pass.
2. **`poll_once()`** on later cycles: refresh index, diff against previous snapshot, run ISO probe if enabled, compute D→P transitions, match watchlists, invoke the notify callback with a `PollResult`.
3. **`run_forever()`** loop:
   - `interval = POLL_INTERVAL_MINUTES * 60` seconds (target spacing).
   - After each `poll_once()`, measure elapsed time.
   - `sleep_for = max(interval - elapsed, POLL_OVERRUN_COOLDOWN_SECONDS)` then `await asyncio.sleep(sleep_for)`.
   - So: short cycles wait out the remainder of the interval; **long or failed cycles** still sleep at least `POLL_OVERRUN_COOLDOWN_SECONDS` before retrying.

**Hot vs cold probing** (what runs inside each cycle) is documented in the README: [Two-Frequency Probing Strategy](../README.md#two-frequency-probing-strategy).

## Where to go next

- Maintainer context and ops notes: [handoff.md](handoff.md)
- Contributing and releases: [CONTRIBUTING.md](../CONTRIBUTING.md)
- Product and Slack: [README](../README.md)
