"""Domain types for WG21 papers parsed from the wg21.link index."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


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
    def from_index_entry(key: str, entry: dict) -> Paper:
        """Build a ``Paper`` from a wg21.link index key and value dict."""
        return Paper(
            id=key,
            title=entry.get("title", ""),
            author=entry.get("author", "") or entry.get("submitter", ""),
            date=entry.get("date", ""),
            paper_type=PaperType(entry["type"]) if "type" in entry else PaperType.PAPER,
            subgroup=entry.get("subgroup", ""),
            url=entry.get("link", ""),
            long_link=entry.get("long_link", ""),
            github_url=entry.get("github_url", ""),
            issues=entry.get("issues", []) or [],
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
    # True when Last-Modified is within alert_modified_hours of now,
    # or when the header is absent (first-ever discovery of a new file).
    is_recent: bool = False


@dataclass
class PerUserMatches:
    """One user's watchlist hits: ``(paper|hit, 'author'|'paper')`` tuples."""

    papers: list[tuple[Paper, str]] = field(default_factory=list)
    probe_hits: list[tuple[ProbeHit, str]] = field(default_factory=list)
