"""Shared failure taxonomy for logging and monitoring."""

from __future__ import annotations

import enum


class FailureCategory(str, enum.Enum):
    """Structured failure categories for poll / HTTP / probe errors."""

    RATE_LIMIT = "RATE_LIMIT"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    CONFIGURATION = "CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class ConfigurationError(Exception):
    """Permanent misconfiguration (credentials, required integration settings)."""
