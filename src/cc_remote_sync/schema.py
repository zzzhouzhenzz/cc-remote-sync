"""Transcript schema: detect, read, extract metadata, convert desktop->CLI.

Two schemas share the same message records; they differ only in leading control
records and how `claude --resume` reads them:
  - CLI ("custom-title"): written by the terminal `claude` binary.
  - desktop ("queue-operation"): written by the app / its SSH helper.

Whether `--resume` accepts a converted file is spike-gated (see docs/DESIGN.md);
the conversion here is a structural best-effort kept isolated and tested.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# control-record types that are schema-specific scaffolding, not conversation
_DESKTOP_ONLY = {"queue-operation"}
_CLI_HEADER = {"custom-title", "mode"}


def read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """Return (records, errors). Never raises on a bad line — collects the error
    so the caller can surface it (no silent swallow)."""
    records: list[dict] = []
    errors: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    errors.append(f"{path.name}:{n}: {e}")
    except OSError as e:
        errors.append(f"{path}: {e}")
    return records, errors


def detect_schema(records: list[dict]) -> str:
    for r in records:
        t = r.get("type")
        if t in _DESKTOP_ONLY:
            return "desktop"
        if t in _CLI_HEADER:
            return "cli"
    return "unknown"


def _ts_to_ms(ts: str | None) -> int:
    if not ts:
        return 0
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


@dataclass
class Meta:
    title: str | None
    model: str | None
    cwd: str | None
    turns: int
    last_activity_ms: int
    born: str | None = None    # the FIRST entrypoint seen = how the session was created


def is_app_born(meta: "Meta") -> bool:
    """True if the session was CREATED in the Claude app (first entrypoint
    'claude-desktop'). Such a session is already in the app's sidebar — the tool
    does not surface it; it only pushes a CLI-resumable copy to Linux. A session
    born in the terminal ('cli') and later opened in the app stays CLI-born."""
    return meta.born == "claude-desktop"


def extract_meta(records: list[dict]) -> Meta:
    title = model = cwd = born = None
    turns = 0
    last_ms = 0
    for r in records:
        t = r.get("type")
        if born is None and r.get("entrypoint"):
            born = r["entrypoint"]
        if t == "custom-title":
            title = r.get("customTitle") or title
        if not cwd and r.get("cwd"):
            cwd = r["cwd"]
        if t == "user" and isinstance(r.get("message"), dict):
            turns += 1
            # first real user prompt is a decent fallback title
            if title is None:
                content = r["message"].get("content")
                text = content if isinstance(content, str) else _first_text(content)
                if text:
                    title = text.strip().splitlines()[0][:80]
        if t == "assistant" and isinstance(r.get("message"), dict):
            model = r["message"].get("model") or model
        last_ms = max(last_ms, _ts_to_ms(r.get("timestamp")))
    return Meta(title, model, cwd, turns, last_ms, born)


def _first_text(content) -> str | None:
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text")
    return None


def to_cli_records(records: list[dict], title: str | None) -> list[dict]:
    """Produce a CLI-resumable record list: drop desktop-only scaffolding, keep
    the conversation, ensure a custom-title header up front."""
    body = [r for r in records if r.get("type") not in _DESKTOP_ONLY]
    has_title = any(r.get("type") == "custom-title" for r in body)
    out: list[dict] = []
    if title and not has_title:
        sid = next((r.get("sessionId") for r in body if r.get("sessionId")), None)
        out.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
    out.extend(body)
    return out


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)  # atomic


def content_hash(path: Path) -> str:
    """Per-side change detection: hash raw bytes. Only ever compared against the
    same side's previous hash, never cross-side."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()
