"""Shared value types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionRef:
    uuid: str
    side: str                     # "linux" | "mac"
    cwd: str
    title: str | None
    model: str | None
    last_activity_ms: int          # transcript time, or file mtime fallback (display/index)
    turns: int
    transcript_path: Path
    content_hash: str
    activity_ms: int = 0          # transcript time ONLY (0 if unknown) — the live signal
    schema: str = "unknown"       # "cli" | "desktop" | "unknown"
    archived: bool = False        # mac side only
    slug: str = ""                # linux project dir name
