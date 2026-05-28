"""Cleanly undo what a sync wrote to the Mac app store.

A backup existing is NOT enough to mean "real entry" — if we wrote an entry more
than once, its backup is our own forged version. We tell them apart by content:
entries we write carry sshConfig.source == "cc-remote-sync". So we restore the
oldest backup that is genuinely NOT ours (the true original); if there is none,
the entry is ours and we remove it. Untouched real sessions are never in the
store and are never touched."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import paths
from .config import Config
from .store import Store


def _is_forged(path: Path) -> bool:
    try:
        d = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (d.get("sshConfig") or {}).get("source") == "cc-remote-sync"


def _original_backup(uuid: str) -> Path | None:
    # oldest first; the earliest non-forged backup is the true pre-tool entry
    backups = sorted(paths.BACKUP_DIR.glob(f"local_{uuid}.json.*.bak"))
    return next((b for b in backups if not _is_forged(b)), None)


def revert_index(cfg: Config, store: Store) -> tuple[int, int]:
    """Returns (restored, removed)."""
    restored = removed = 0
    for uuid in list(store.records):
        entry = paths.index_entry_path(cfg.org, cfg.acct, uuid)
        original = _original_backup(uuid)
        if original:
            shutil.copy2(original, entry)     # put the genuine real entry back
            restored += 1
        else:
            entry.unlink(missing_ok=True)     # ours -> drop it
            tdir = paths.mac_transcript_path(uuid).parent
            if tdir.exists() and tdir.name == f"ssh-{uuid}":
                shutil.rmtree(tdir, ignore_errors=True)
            removed += 1
    return restored, removed
