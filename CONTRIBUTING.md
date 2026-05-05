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

Install the package in editable mode with dev dependencies:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"
```

### Tests and coverage

```bash
./run check          # pytest + coverage, fails under 90% line coverage (matches CI)
# or: make check
```

CI runs `pre-commit run --all-files` for pushes/PRs on configured branches (currently `main` and `develop`; see `.github/workflows/ci.yml`).

### Lint and format (Ruff + pre-commit)

We use **[pre-commit](https://pre-commit.com/)** with **[Ruff](https://docs.astral.sh/ruff/)** for linting and formatting.

```bash
pre-commit install
pre-commit run --all-files
```

CI runs `pre-commit run --all-files` on every push and pull request (see the `lint` job in `.github/workflows/ci.yml`).

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
