"""Build the two session manifests: Linux (from the rsync staging mirror) and
Mac (from the app's index entries)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import paths, schema
from .config import Config
from .models import SessionRef


def linux_manifest(cfg: Config) -> tuple[dict[str, SessionRef], list[str]]:
    """Sessions present on the Linux box, within the scope window."""
    out: dict[str, SessionRef] = {}
    errors: list[str] = []
    cutoff_ms = (int(time.time()) - cfg.scope_days * 86400) * 1000 if cfg.scope_days else 0

    if not paths.STAGING_DIR.exists():
        return out, errors
    for jsonl in paths.STAGING_DIR.glob("*/*.jsonl"):
        slug = jsonl.parent.name
        uuid = jsonl.stem
        records, errs = schema.read_jsonl(jsonl)
        errors.extend(errs)
        if not records:
            continue
        meta = schema.extract_meta(records)
        last = meta.last_activity_ms or int(jsonl.stat().st_mtime * 1000)
        if cutoff_ms and last < cutoff_ms:
            continue
        prev = out.get(uuid)
        if prev and prev.last_activity_ms >= last:
            continue  # same session in two dirs -> keep the newer copy
        out[uuid] = SessionRef(
            uuid=uuid,
            side="linux",
            cwd=meta.cwd or "",
            title=meta.title,
            model=meta.model,
            last_activity_ms=last,
            activity_ms=meta.last_activity_ms,   # transcript-only; NOT file mtime
            turns=meta.turns,
            transcript_path=jsonl,
            content_hash=schema.content_hash(jsonl),
            schema=schema.detect_schema(records),
            slug=slug,
        )
    return out, errors


def mac_manifest(cfg: Config) -> tuple[dict[str, SessionRef], list[str]]:
    """Sessions the app currently knows about, bound to our Linux host."""
    out: dict[str, SessionRef] = {}
    errors: list[str] = []
    idx_dir = paths.SESSIONS_INDEX_ROOT / cfg.org / cfg.acct
    if not idx_dir.exists():
        return out, errors
    want_host_id = cfg.ssh_config.get("id")
    for entry in idx_dir.glob("local_*.json"):
        try:
            d = json.loads(entry.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"{entry.name}: {e}")
            continue
        ssh = d.get("sshConfig") or {}
        if ssh.get("id") != want_host_id:
            continue  # not bound to our Linux host -> out of scope
        uuid = d.get("cliSessionId")
        if not uuid:
            continue
        tpath = paths.mac_transcript_path(uuid)
        out[uuid] = SessionRef(
            uuid=uuid,
            side="mac",
            cwd=d.get("cwd", ""),
            title=d.get("title"),
            model=d.get("model"),
            last_activity_ms=d.get("lastActivityAt", 0),
            activity_ms=d.get("lastActivityAt", 0),
            turns=d.get("completedTurns", 0),
            transcript_path=tpath,
            content_hash=schema.content_hash(tpath) if tpath.exists() else "",
            archived=bool(d.get("isArchived")),
        )
    return out, errors
