# Contributing to paperscout

Thank you for your interest in improving paperscout. This document describes how we work, how to run checks locally, and how releases are cut.

## Where to start

- **[docs/onboarding.md](docs/onboarding.md)** — clone, database, `.env`, tests, and running the app locally.
- **[docs/handoff.md](docs/handoff.md)** — maintainer-oriented design notes and operational gotchas.
- **[README.md](README.md)** — product behavior, Slack setup, deployment, and environment variable tables.

## Workflow

1. **Fork** the repository (if you lack direct push access) and **clone** your fork.
2. Create a **feature branch** from the active integration branch (currently `develop`; confirm repo default/protection rules before opening).
3. Make focused commits with clear messages.
4. Open a **pull request** against the designated target branch (`develop` or `main`, per current release flow). Use the PR template; link related issues when applicable.
5. Ensure **CI is green** (tests + coverage + lint hooks — see below).

### Code owners

[`.github/CODEOWNERS`](.github/CODEOWNERS) routes review requests. If GitHub reports unknown owners, maintainers should update that file with real `@username` or `@org/team` entries and ensure the team exists and has repository access.

## Local checks

Install **[uv](https://docs.astral.sh/uv/)** (recommended) and sync the locked dev environment from the repo root:

```bash
uv sync --extra dev
```

This installs the project and all dev tools from [`uv.lock`](uv.lock) (see **Dependency lockfile** below). Alternatively, with a classic venv:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
# if using a classic venv instead of uv:
pre-commit install
pre-commit run --all-files
```

### Dependency lockfile

Runtime and dev dependencies are pinned in **`uv.lock`**, generated from [`pyproject.toml`](pyproject.toml). CI runs `uv lock --check` so the lockfile cannot drift.

**To add or upgrade a dependency:**

1. Edit [`pyproject.toml`](pyproject.toml) (`dependencies` or `[project.optional-dependencies] dev`).
2. Regenerate the lockfile: `uv lock`
3. Commit both `pyproject.toml` and `uv.lock`.

**To verify locally before pushing:** `uv lock --check`

### Docker image rebuild

Production images install from [`uv.lock`](uv.lock) via `uv sync --frozen` in the multi-stage [`Dockerfile`](Dockerfile) (not a floating `pip install .`). The base `python:3.12-slim` image is pinned by digest in the Dockerfile.

**After changing dependencies** (`pyproject.toml` / `uv.lock`):

1. Commit the updated lockfile.
2. Rebuild: `docker compose build --no-cache` or `docker build -t paperscout:test .`

**When upgrading the Python base image:**

```bash
docker pull python:3.12-slim
docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
```

Update both `FROM` lines in the Dockerfile with the new digest, then rebuild.

**Verify tests inside the image** (no live Postgres required):

```bash
docker build --target test -t paperscout:test .
docker run --rm --entrypoint python \
  -e _PAPERSCOUT_TESTING=1 \
  -e SLACK_BOT_TOKEN=xoxb-test \
  -e SLACK_SIGNING_SECRET=test-secret \
  -e COVERAGE_FILE=/tmp/.coverage \
  paperscout:test \
  -m pytest tests/ -q --cov=paperscout --cov-fail-under=90
```

Production deploys use the default image target (runtime only, no dev dependencies).

See also [deploy/SERVER_SETUP.md](deploy/SERVER_SETUP.md) for operator rebuild steps on the server.

### Tests and coverage

```bash
./run check          # pytest + coverage, fails under 90% line coverage (matches CI)
# or: make check
```

CI uses **`uv sync --frozen --extra dev`** then **`uv run`** for tests and pre-commit (see `.github/workflows/ci.yml`).

### Lint and format (Ruff + pre-commit)

We use **[pre-commit](https://pre-commit.com/)** with **[Ruff](https://docs.astral.sh/ruff/)** for linting and formatting.

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

CI runs `uv run pre-commit run --all-files` on every push and pull request (see the `lint` job in `.github/workflows/ci.yml`).

## Expectations for changes

- **Tests** — Add or update tests for behavior changes. Keep coverage at or above the project floor (**90%**).
- **Docs** — Update README, onboarding, or handoff when you change operator-visible behavior, env vars, or deployment steps.
- **Style** — Let Ruff format the tree; avoid unrelated drive-by reformatting of untouched files in the same PR when possible.

## Releases

We follow **[Semantic Versioning](https://semver.org/)** and **[Keep a Changelog](https://keepachangelog.com/)** principles.

1. **Version** — Bump `version` in [`pyproject.toml`](pyproject.toml) (e.g. `0.1.0` → `0.2.0`).
2. **Changelog** — Move items from `## [Unreleased]` to a new section `## [x.y.z] - YYYY-MM-DD` in [`CHANGELOG.md`](CHANGELOG.md).
3. **Tag** — Create an annotated tag: `git tag -a v0.2.0 -m "Release v0.2.0"` and push it: `git push origin v0.2.0`.
4. **GitHub Release** — On GitHub, create a **Release** from that tag and paste the changelog section for that version into the release notes.

Optional follow-ups (not required today): PyPI publishing workflow, signed tags, or automated release notes.

## Questions

Use **GitHub Issues** for bugs and feature ideas (see issue templates). For organizational or access questions, contact the **CppAlliance** maintainers responsible for this repository (replace with a concrete contact when publishing internally).
