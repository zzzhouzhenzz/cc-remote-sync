"""Forge / update / remove the app's session index entries and transcript cache.
This is what actually makes a terminal session appear (and resume) in the app."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import paths
from .config import Config
from .models import SessionRef


def _backup(p: Path) -> None:
    if not p.exists():
        return
    paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    shutil.copy2(p, paths.BACKUP_DIR / f"{p.name}.{stamp}.bak")


def write_entry(cfg: Config, ref: SessionRef) -> Path:
    """Create or update local_<uuid>.json so the app lists + SSH-resumes it."""
    entry_path = paths.index_entry_path(cfg.org, cfg.acct, ref.uuid)
    existing: dict = {}
    if entry_path.exists():
        try:
            existing = json.loads(entry_path.read_text())
        except json.JSONDecodeError:
            existing = {}

    now = int(time.time() * 1000)
    created = existing.get("createdAt") or ref.last_activity_ms or now
    entry = {
        **existing,
        "sessionId": f"local_{ref.uuid}",
        "cliSessionId": ref.uuid,
        "cwd": ref.cwd or existing.get("cwd", ""),
        "originCwd": existing.get("originCwd") or ref.cwd or "",
        "createdAt": created,
        "lastActivityAt": ref.last_activity_ms or now,
        "model": ref.model or existing.get("model"),
        "title": ref.title or existing.get("title") or "(untitled session)",
        "completedTurns": ref.turns,
        "isArchived": existing.get("isArchived", False),
        "permissionMode": existing.get("permissionMode", "default"),
        "remoteMcpServersConfig": existing.get("remoteMcpServersConfig", []),
        "sshConfig": {**cfg.ssh_config, "source": "cc-remote-sync"},
    }
    _backup(entry_path)
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = entry_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, indent=2))
    tmp.replace(entry_path)
    return entry_path


def mirror_transcript(ref: SessionRef) -> Path:
    """Copy the Linux transcript into the app's display cache location.
    NOTE: copied as-is; whether the renderer needs cli->desktop normalization is
    spike item #2 (docs/DESIGN.md)."""
    dest = paths.mac_transcript_path(ref.uuid)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ref.transcript_path, dest)
    return dest


def remove_entry(cfg: Config, uuid: str) -> None:
    """Drop the app's knowledge of a session (used when Linux side vanished)."""
    entry_path = paths.index_entry_path(cfg.org, cfg.acct, uuid)
    _backup(entry_path)
    entry_path.unlink(missing_ok=True)
    tdir = paths.mac_transcript_path(uuid).parent
    if tdir.exists():
        shutil.rmtree(tdir, ignore_errors=True)
