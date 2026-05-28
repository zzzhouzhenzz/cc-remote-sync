"""Mapping store: the memory that turns 'a session vanished' into 'deleted' vs
'never synced'. Plain JSON keyed by uuid — single user, no concurrency."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SideState:
    hash: str = ""
    mtime_ms: int = 0


@dataclass
class Record:
    uuid: str
    cwd: str = ""
    title: str = ""                     # last-synced title — baseline for rename detection
    linux: SideState | None = None
    mac: SideState | None = None
    last_synced_ms: int = 0
    tombstone_side: str | None = None   # "mac" or "linux" — who deleted it
    tombstone_ms: int = 0


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, Record] = {}

    def load(self) -> "Store":
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            for uuid, d in raw.get("records", {}).items():
                self.records[uuid] = Record(
                    uuid=uuid,
                    cwd=d.get("cwd", ""),
                    title=d.get("title", ""),
                    linux=SideState(**d["linux"]) if d.get("linux") else None,
                    mac=SideState(**d["mac"]) if d.get("mac") else None,
                    last_synced_ms=d.get("last_synced_ms", 0),
                    tombstone_side=d.get("tombstone_side"),
                    tombstone_ms=d.get("tombstone_ms", 0),
                )
        return self

    def save(self) -> None:
        out = {"version": 1, "records": {}}
        for uuid, r in self.records.items():
            out["records"][uuid] = {
                "cwd": r.cwd,
                "title": r.title,
                "linux": asdict(r.linux) if r.linux else None,
                "mac": asdict(r.mac) if r.mac else None,
                "last_synced_ms": r.last_synced_ms,
                "tombstone_side": r.tombstone_side,
                "tombstone_ms": r.tombstone_ms,
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=2))
        tmp.replace(self.path)

    def get(self, uuid: str) -> Record | None:
        return self.records.get(uuid)

    def upsert(self, rec: Record) -> None:
        rec.last_synced_ms = int(time.time() * 1000)
        self.records[rec.uuid] = rec

    def tombstone(self, uuid: str, side: str, cwd: str = "") -> None:
        rec = self.records.get(uuid) or Record(uuid=uuid, cwd=cwd)
        rec.tombstone_side = side
        rec.tombstone_ms = int(time.time() * 1000)
        rec.linux = None
        rec.mac = None
        self.records[uuid] = rec

    def is_tombstoned(self, uuid: str) -> bool:
        r = self.records.get(uuid)
        return bool(r and r.tombstone_side)
