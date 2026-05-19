"""Helpers for running blocking I/O off the asyncio event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


async def run_blocking_io(fn: Callable[..., _T], /, *args, **kwargs) -> _T:
    """Run *fn* in a worker thread without blocking the event loop.

    Use only for pure blocking I/O (e.g. psycopg2 queries) that does **not**
    touch shared in-process mutable state such as ``ISOProber._stats``,
    ``WG21Index.papers``, or other source internals. Each call should use its
    own database connection from the pool.

    See ``docs/architecture.md`` for the full concurrency model.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
