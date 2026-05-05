"""Unit tests for PDF text extraction using an in-memory PDF (no network)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from paperscout.sources import _fetch_pdf_text


def _make_stream_cm(status: int = 200, chunks: list[bytes] | None = None):
    """Match ``tests.test_sources._make_stream_cm`` (local copy to avoid circular imports)."""

    async def _aiter_bytes(chunk_size=65536):
        for chunk in chunks or []:
            yield chunk

    resp = MagicMock()
    resp.status_code = status
    resp.aiter_bytes = _aiter_bytes
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_fetch_pdf_text_extracts_embedded_marker():
    pytest.importorskip("fitz", reason="PyMuPDF not installed")
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "paperscout_marker_alpha")
    pdf_bytes = doc.tobytes()
    doc.close()

    client = MagicMock()
    client.stream = MagicMock(return_value=_make_stream_cm(200, chunks=[pdf_bytes]))

    text = await _fetch_pdf_text(client, "https://example.com/doc.pdf")
    assert "paperscout_marker_alpha" in text
