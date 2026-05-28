"""The orchestrator. Diffs the Linux and Mac manifests against the mapping store
and applies the minimal set of changes. Pure decisions are in `plan()` so they
can be unit-tested without touching SSH or the filesystem."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import harvest, index_writer, paths, schema, ssh
from .config import Config
from .models import SessionRef
from .store import Record, SideState, Store

log = logging.getLogger("cc-remote-sync")


@dataclass
class Summary:
    created: int = 0      # surfaced on Mac (down arrow)
    updated: int = 0      # Mac entry refreshed
    pushed: int = 0       # resume-fix copies sent to Linux (up arrow)
    deleted: int = 0      # deletions propagated
    unchanged: int = 0    # equals
    skipped: int = 0      # LIVE sessions skipped (active within the window)
    no_source: int = 0    # Mac entries with no Linux session in scope (orphans) — not live
    renamed: int = 0      # titles reconciled either direction
    errors: list[str] = field(default_factory=list)

    def line(self) -> str:
        s = f"{self.created}↓ {self.pushed}↑ {self.unchanged}="
        if self.renamed:
            s += f" {self.renamed}✎"
        if self.skipped:
            s += f" {self.skipped}⏭"      # live
        if self.no_source:
            s += f" {self.no_source}⊘"    # mac-only, no Linux source
        if self.deleted:
            s += f" {self.deleted}✗"
        if self.errors:
            s += f" {len(self.errors)}!"
        return s


# ---- pure decision layer -------------------------------------------------

@dataclass
class Action:
    kind: str          # surface | update | delete_linux | delete_mac | resume_fix | noop
    uuid: str
    ref: SessionRef | None = None
    reason: str = ""


def filter_active(
    linux: dict[str, SessionRef],
    mac: dict[str, SessionRef],
    cutoff_ms: int,
) -> int:
    """Drop sessions active after cutoff (likely open in the app right now) so a
    sync never races the session you're using. Mutates both dicts; returns count."""
    skipped = 0
    for uuid in sorted(set(linux) | set(mac)):
        # use transcript activity only — file mtime is bumped by our own writes
        la = linux[uuid].activity_ms if uuid in linux else 0
        ma = mac[uuid].activity_ms if uuid in mac else 0
        last = max(la, ma)
        if last > cutoff_ms:
            side = "linux-transcript" if la >= ma else "mac-index"
            log.info("skip %s active_ms=%d via=%s (cutoff_ms=%d, %.1f min inside window)",
                     uuid[:8], last, side, cutoff_ms, (last - cutoff_ms) / 60000)
            linux.pop(uuid, None)
            mac.pop(uuid, None)
            skipped += 1
    return skipped


def decide_rename(linux_title, mac_title, stored_title, linux_activity, mac_activity):
    """Which side gets the new title. Returns (target, title):
    target == 'mac'   -> Linux changed, push title to the Mac entry
    target == 'linux' -> Mac changed, push title into the Linux transcript
    target == 'none'  -> already in sync. Both-changed -> last-writer-wins, tie -> Mac."""
    lt = linux_title or ""
    mt = mac_title or ""
    st = stored_title or ""
    if lt == mt:
        return ("none", lt)
    l_changed = lt != st
    m_changed = mt != st
    if m_changed and not l_changed:
        return ("linux", mt)
    if l_changed and not m_changed:
        return ("mac", lt)
    # both diverged from baseline (or no baseline) -> newest activity wins, tie -> Mac
    return ("mac", lt) if linux_activity > mac_activity else ("linux", mt)


def reconcile_titles(cfg: Config, linux, mac, store: Store, summ: "Summary",
                     dry_run: bool) -> None:
    """Two-way rename. Runs before content sync so write_entry uses the resolved
    title (and never clobbers a Mac rename with a stale Linux title)."""
    for uuid in set(linux) & set(mac):
        if store.is_tombstoned(uuid):
            continue
        L, M = linux[uuid], mac[uuid]
        S = store.get(uuid)
        target, title = decide_rename(L.title, M.title, S.title if S else "",
                                      L.activity_ms, M.activity_ms)
        L.title = M.title = title          # resolve on both refs for downstream writes
        if target == "none":
            continue
        log.info("rename %s -> %s (%r)", uuid[:8], target, title)
        if not dry_run:
            if target == "mac":
                index_writer.write_entry(cfg, L)         # Linux won: refresh Mac title
            else:
                _push_rename_to_linux(cfg, L, title)     # Mac won: write Linux transcript
            rec = store.get(uuid) or Record(uuid=uuid, cwd=L.cwd)
            rec.title = title
            store.records[uuid] = rec
        summ.renamed += 1


def _push_rename_to_linux(cfg: Config, ref: SessionRef, title: str) -> None:
    """Append a custom-title record to the Linux transcript (cc uses the last one)
    and push it back in place, so `claude --resume` shows the new name."""
    records, _ = schema.read_jsonl(ref.transcript_path)
    records.append({"type": "custom-title", "customTitle": title, "sessionId": ref.uuid})
    tmp = paths.STAGING_DIR.parent / f"_rename_{ref.uuid}.jsonl"
    schema.write_jsonl(tmp, records)
    remote_rel = f"{paths.REMOTE_PROJECTS}/{ref.slug}/{ref.uuid}.jsonl"
    ssh.push_file(cfg, tmp, remote_rel)
    shutil.copy2(tmp, ref.transcript_path)   # keep staging consistent
    tmp.unlink(missing_ok=True)


def plan(
    linux: dict[str, SessionRef],
    mac: dict[str, SessionRef],
    store: Store,
    *,
    propagate_deletions: bool,
) -> list[Action]:
    actions: list[Action] = []
    uuids = set(linux) | set(mac) | set(store.records)

    for uuid in uuids:
        L = linux.get(uuid)
        M = mac.get(uuid)
        S = store.get(uuid)

        # tombstone handling: stay dead unless genuinely resumed (newer activity)
        if S and S.tombstone_side:
            active = L or M
            if not (active and active.last_activity_ms > S.tombstone_ms):
                continue
            # else: resurrected -> fall through as if new

        synced_before = bool(S and (S.linux or S.mac) and not (S and S.tombstone_side))

        if L and not M:
            if synced_before and S and S.mac:
                # was on Mac, user removed it there -> delete on Linux
                if propagate_deletions:
                    actions.append(Action("delete_linux", uuid, L, "removed in Mac app"))
                else:
                    actions.append(Action("noop", uuid, L, "mac-deleted, propagation off"))
            else:
                actions.append(Action("surface", uuid, L, "new on Linux"))
                if L.schema == "desktop":
                    actions.append(Action("resume_fix", uuid, L, "desktop schema on Linux"))
            continue

        if M and not L:
            if synced_before and S and S.linux:
                actions.append(Action("delete_mac", uuid, M, "vanished on Linux"))
            else:
                actions.append(Action("noop", uuid, M, "mac-only, no Linux content"))
            continue

        if L and M:
            if M.archived:
                if propagate_deletions:
                    actions.append(Action("delete_linux", uuid, L, "archived in Mac app"))
                continue
            changed = not (S and S.linux and S.linux.hash == L.content_hash)
            if changed:
                actions.append(Action("update", uuid, L, "Linux content changed"))
            else:
                actions.append(Action("noop", uuid, L, "unchanged"))
            if L.schema == "desktop":
                actions.append(Action("resume_fix", uuid, L, "desktop schema on Linux"))
            continue

    return actions


# ---- effectful apply layer ----------------------------------------------

def run(cfg: Config, store: Store, *, dry_run: bool = False) -> Summary:
    """Full sync. Raises ssh.Unreachable if the box can't be reached (the app
    turns that into the Cannot-connect state + Retry; never auto-retries)."""
    summ = Summary()
    ssh.check(cfg)                 # may raise Unreachable
    ssh.pull_projects(cfg)         # may raise Unreachable

    linux, e1 = harvest.linux_manifest(cfg)
    mac, e2 = harvest.mac_manifest(cfg)
    summ.errors += e1 + e2

    if cfg.skip_active_minutes:
        cutoff = int((time.time() - cfg.skip_active_minutes * 60) * 1000)
        summ.skipped += filter_active(linux, mac, cutoff)

    try:
        reconcile_titles(cfg, linux, mac, store, summ, dry_run)
    except ssh.Unreachable:
        raise
    except Exception as e:
        summ.errors.append(f"rename: {e}")
        log.exception("title reconciliation failed")

    actions = plan(linux, mac, store, propagate_deletions=cfg.propagate_deletions != "off")

    for a in actions:
        try:
            _apply(cfg, store, a, summ, dry_run)
        except ssh.Unreachable:
            raise
        except Exception as e:  # never let one bad session abort the run
            summ.errors.append(f"{a.kind} {a.uuid[:8]}: {e}")
            log.exception("action failed: %s %s", a.kind, a.uuid)

    if not dry_run:
        store.save()
    return summ


def _remember(store: Store, ref: SessionRef, *, mac_hash: str | None = None) -> None:
    rec = store.get(ref.uuid) or Record(uuid=ref.uuid, cwd=ref.cwd)
    rec.cwd = ref.cwd or rec.cwd
    rec.tombstone_side = None
    rec.linux = SideState(hash=ref.content_hash, mtime_ms=ref.last_activity_ms)
    rec.mac = SideState(hash=mac_hash or ref.content_hash, mtime_ms=ref.last_activity_ms)
    store.upsert(rec)


def _apply(cfg: Config, store: Store, a: Action, summ: Summary, dry_run: bool) -> None:
    if a.kind == "noop":
        if a.reason == "unchanged":
            summ.unchanged += 1
        else:
            summ.no_source += 1   # mac-only / not-actioned — NOT a live skip
        return

    if a.kind in ("surface", "update"):
        log.info("%s %s (%s)", a.kind, a.uuid, a.reason)
        if not dry_run:
            index_writer.write_entry(cfg, a.ref)
            index_writer.mirror_transcript(a.ref)
            _remember(store, a.ref)
        summ.created += a.kind == "surface"
        summ.updated += a.kind == "update"
        return

    if a.kind == "resume_fix":
        log.info("resume_fix %s (%s)", a.uuid, a.reason)
        if not dry_run:
            _resume_fix(cfg, a.ref)
        summ.pushed += 1
        return

    if a.kind == "delete_linux":
        log.info("delete_linux %s (%s)", a.uuid, a.reason)
        if not dry_run:
            rel = f"{paths.remote_project_dir(a.ref.cwd)}/{a.uuid}.jsonl"
            ssh.soft_delete_remote(cfg, rel, a.uuid)
            store.tombstone(a.uuid, "mac", a.ref.cwd)
        summ.deleted += 1
        return

    if a.kind == "delete_mac":
        log.info("delete_mac %s (%s)", a.uuid, a.reason)
        if not dry_run:
            index_writer.remove_entry(cfg, a.uuid)
            store.tombstone(a.uuid, "linux", a.ref.cwd)
        summ.deleted += 1
        return


def _resume_fix(cfg: Config, ref: SessionRef) -> None:
    """Ensure a CLI-resumable copy exists at the cwd-slug path on Linux so
    `claude --resume <uuid>` works in the terminal. Spike-gated fidelity."""
    if not ref.cwd:
        return
    records, _ = schema.read_jsonl(ref.transcript_path)
    cli = schema.to_cli_records(records, ref.title)
    local = paths.STAGING_DIR.parent / f"_resume_fix_{ref.uuid}.jsonl"
    schema.write_jsonl(local, cli)
    remote_rel = f"{paths.remote_project_dir(ref.cwd)}/{ref.uuid}.jsonl"
    ssh.push_file(cfg, local, remote_rel)
    local.unlink(missing_ok=True)
