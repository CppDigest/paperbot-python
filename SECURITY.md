# Security policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| `main`  | Yes — latest fixes |
| Tags    | Best-effort — use the latest tag for production |

Older branches may not receive backports unless agreed with maintainers.

## Reporting a vulnerability

**Please do not** file a public GitHub issue for undisclosed security vulnerabilities.

Instead:

1. Use **[GitHub private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)** for this repository (if enabled by org settings), **or**
2. Email or contact the **CppAlliance / repository maintainers** through an internal channel your organization documents for security.

Maintainers will acknowledge receipt as soon as practical, investigate, and coordinate a fix and disclosure timeline with you.

## Scope

This policy covers the **paperscout** application code, Docker image, and GitHub workflows in this repository. Infrastructure (servers, PostgreSQL host hardening, Slack workspace policy) is out of scope here but should follow your organization’s security baseline — see [`deploy/SERVER_SETUP.md`](deploy/SERVER_SETUP.md) for deployment hardening notes.
