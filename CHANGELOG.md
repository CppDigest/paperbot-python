# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Discriminated ISO probe cycle outcomes (`CycleResult`: success / empty / failed) with distinct logging and `/health` fields (`last_cycle_status`, `last_cycle_error`).
- Atomic `SchedulerSnapshot` for `/health` scheduler extras (`last_updated`, `poll_count`, probe stats) published under a lock from `Scheduler.health_snapshot()`.
- Post the same Slack **status** summary as the interactive command to `NOTIFICATION_CHANNEL` once when the process starts (when that channel is configured).
- Open-source hygiene: contributing guide, security policy, code of conduct, onboarding and handoff docs, pre-commit (Ruff), GitHub issue templates, Dependabot, CodeQL, CODEOWNERS template, and `.gitattributes`.

### Changed

- Documentation: deployment URLs (Slack Request URL behind nginx `/paperscout/`), clone URL in server setup, staging-style placeholders.
- `db-backup.yml`: matrix parallel backups for `staging` / `production` using environment-level SSH secrets; uploads under `gs://insights-db-backups/paperscout/<environment>/` with unique temp files and object keys (UTC timestamp + `run_id` + `run_attempt` + environment); `EXIT` trap removes temp dump on failure. `SERVER_SETUP` restore examples updated (`--no-owner`, listing/copy by object name).
- `cd.yml`: validate `DEPLOY_PATH`, `DEPLOY_BRANCH`, and `HEALTH_PORT` GitHub Environment variables before SSH so missing `HEALTH_PORT` fails with a clear error instead of curling `http://localhost:/health`.

## [0.1.0] - 2026-05-05

### Added

- Initial public release as tracked in `pyproject.toml` (WG21 paper tracking, Slack integration, PostgreSQL storage, Docker deploy, CI/CD workflows).
