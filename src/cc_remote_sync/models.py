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
    last_activity_ms: int
    turns: int
    transcript_path: Path
    content_hash: str
    schema: str = "unknown"       # "cli" | "desktop" | "unknown"
    archived: bool = False        # mac side only
    slug: str = ""                # linux project dir name
