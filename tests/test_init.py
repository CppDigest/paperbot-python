"""Tests for paperscout package metadata (__version__)."""

from __future__ import annotations

import importlib
import importlib.metadata
from unittest.mock import patch

import pytest

import paperscout


@pytest.fixture(autouse=True)
def restore_paperscout_module():
    yield
    importlib.reload(paperscout)


def test_version_uses_installed_metadata():
    with patch.object(importlib.metadata, "version", return_value="9.9.9-test"):
        importlib.reload(paperscout)
        assert paperscout.__version__ == "9.9.9-test"


def test_version_fallback_when_package_not_found():
    def _missing(_name: str):
        raise importlib.metadata.PackageNotFoundError()

    with patch.object(importlib.metadata, "version", side_effect=_missing):
        importlib.reload(paperscout)
        assert paperscout.__version__ == "0.0.0-dev"
