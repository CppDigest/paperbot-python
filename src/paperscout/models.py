"""Domain types for WG21 papers parsed from the wg21.link index."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class PaperPrefix(str, Enum):
    """Paper ID prefix letters (P/D/N, subgroup codes, etc.)."""

    D = "D"
    P = "P"
    N = "N"
    CWG = "CWG"
    EWG = "EWG"
    LWG = "LWG"
    LEWG = "LEWG"
    FS = "FS"
    SD = "SD"
    EDIT = "EDIT"


class PaperType(str, Enum):
    """Classification from the wg21.link index ``type`` field."""

    PAPER = "paper"
    ISSUE = "issue"
    EDITORIAL = "editorial"
    STANDING_DOCUMENT = "standing-document"
    DRAFT = "draft"


class FileExt(str, Enum):
    """Published file extension for a paper artifact."""

    PDF = ".pdf"
    HTML = ".html"


_P_RE = re.compile(r"^([PD])(\d+)R(\d+)$", re.IGNORECASE)
_N_RE = re.compile(r"^N(\d+)$", re.IGNORECASE)
_ISSUE_RE = re.compile(r"^(CWG|EWG|LWG|LEWG|FS)(\d+)$", re.IGNORECASE)


@dataclass(slots=True)
class Paper:
    """One indexed paper: id, metadata, and derived number/prefix/revision."""

    id: str
    title: str = ""
    author: str = ""
    date: str = ""
    paper_type: PaperType = PaperType.PAPER
    subgroup: str = ""
    url: str = ""
    long_link: str = ""
    github_url: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def number(self) -> int | None:
        m = _P_RE.match(self.id)
        if m:
            return int(m.group(2))
        m = _N_RE.match(self.id)
        if m:
            return int(m.group(1))
        m = _ISSUE_RE.match(self.id)
        if m:
            return int(m.group(2))
        return None

    @property
    def prefix(self) -> str:
        m = _P_RE.match(self.id)
        if m:
            return m.group(1).upper()
        m = _N_RE.match(self.id)
        if m:
            return "N"
        m = _ISSUE_RE.match(self.id)
        if m:
            return m.group(1).upper()
        return ""

    @property
    def revision(self) -> int | None:
        m = _P_RE.match(self.id)
        return int(m.group(3)) if m else None

    @staticmethod
    def from_index_entry(key: str, entry: dict[str, Any]) -> Paper:
        """Build a ``Paper`` from a wg21.link index key and value dict."""
        paper_type = PaperType.PAPER
        if "type" in entry:
            raw = entry["type"]
            if isinstance(raw, str):
                try:
                    paper_type = PaperType(raw)
                except ValueError:
                    log.warning(
                        "Unknown index paper type %r for key %s — defaulting to %s",
                        raw,
                        key,
                        PaperType.PAPER.value,
                    )
            else:
                log.warning(
                    "Invalid index paper type %r (expected str) for key %s — defaulting to %s",
                    raw,
                    key,
                    PaperType.PAPER.value,
                )
        author_val = entry.get("author", "")
        submitter_val = entry.get("submitter", "")
        author_s = author_val if isinstance(author_val, str) else ""
        submitter_s = submitter_val if isinstance(submitter_val, str) else ""
        issues_raw = entry.get("issues", []) or []
        issues_list: list[str]
        if isinstance(issues_raw, list):
            issues_list = [str(x) for x in issues_raw]
        else:
            issues_list = []

        def _s(field: str, default: str = "") -> str:
            v = entry.get(field, default)
            return v if isinstance(v, str) else default

        return Paper(
            id=key,
            title=_s("title"),
            author=author_s or submitter_s,
            date=_s("date"),
            paper_type=paper_type,
            subgroup=_s("subgroup"),
            url=_s("link"),
            long_link=_s("long_link"),
            github_url=_s("github_url"),
            issues=issues_list,
        )


# ── ISO probe / watchlist match shapes (kept here to avoid storage↔monitor cycles) ─


class Tier(str, Enum):
    """Probe priority bucket for isocpp HEAD requests."""

    WATCHLIST = "watchlist"
    FRONTIER = "frontier"
    RECENT = "recent"
    COLD = "cold"


@dataclass(slots=True)
class ProbeHit:
    """Successful HEAD to an unpublished draft URL plus optional excerpt text."""

    url: str
    prefix: str
    number: int
    revision: int
    extension: str
    tier: Tier
    front_text: str = ""
    last_modified: datetime | None = field(default=None)
    # True when Last-Modified is within alert_modified_hours of now, when the
    # header is absent, or when the header is present but unusable (first-ever
    # discovery or bad Last-Modified — both treated as recent for alerting).
    is_recent: bool = False


@dataclass
class PerUserMatches:
    """One user's watchlist hits: ``(paper|hit, 'author'|'paper')`` tuples."""

    papers: list[tuple[Paper, str]] = field(default_factory=list)
    probe_hits: list[tuple[ProbeHit, str]] = field(default_factory=list)
