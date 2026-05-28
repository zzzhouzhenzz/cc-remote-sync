"""The orchestrator. Diffs the Linux and Mac manifests against the mapping store
and applies the minimal set of changes. Pure decisions are in `plan()` so they
can be unit-tested without touching SSH or the filesystem."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import harvest, index_writer, paths, schema, ssh, teardown
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
    deferred: int = 0     # Linux-write deferred because the session is live (surfaced anyway)
    no_source: int = 0    # Mac entries with no Linux session in scope (orphans) — not live
    renamed: int = 0      # titles reconciled either direction
    relinquished: int = 0  # app-born entries handed back to the app (un-hijacked)
    errors: list[str] = field(default_factory=list)

    def line(self) -> str:
        s = f"{self.created}↓ {self.pushed}↑ {self.unchanged}="
        if self.renamed:
            s += f" {self.renamed}✎"
        if self.relinquished:
            s += f" {self.relinquished}⤺"
        if self.deferred:
            s += f" {self.deferred}⏸"      # live: Linux-write deferred
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


def active_live(live: dict[str, dict], max_idle_seconds: int) -> set[str]:
    """Sessions a cc process is ACTIVELY running: marker reports a live status
    (busy/waiting/...) OR it heartbeated within max_idle_seconds. A process that is
    alive but reports no status and hasn't heartbeated (a stale/lingering ccd-cli) is
    NOT considered active. We still SURFACE active sessions (creating the app entry is
    safe — it only reads Linux and writes Mac-side); we only DEFER operations that
    write to the live transcript on Linux (resume-fix, rename push, delete)."""
    out: set[str] = set()
    for uuid, info in live.items():
        has_status = info.get("status") not in ("-", "", None)
        if has_status or info.get("idle_seconds", 1 << 30) <= max_idle_seconds:
            out.add(uuid)
    return out


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
                     dry_run: bool, live: set[str] = frozenset()) -> None:
    """Two-way rename. Runs before content sync so write_entry uses the resolved
    title (and never clobbers a Mac rename with a stale Linux title). A rename that
    must WRITE the Linux transcript (Mac won) is deferred while the session is live."""
    for uuid in set(linux) & set(mac):
        if store.is_tombstoned(uuid):
            continue
        L, M = linux[uuid], mac[uuid]
        S = store.get(uuid)
        target, title = decide_rename(L.title, M.title, S.title if S else "",
                                      L.activity_ms, M.activity_ms)
        if target == "linux" and uuid in live:
            log.info("defer rename %s -> linux (live)", uuid[:8])
            summ.deferred += 1
            continue                          # don't write a live transcript; retry when idle
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
    live: set[str] = frozenset(),
) -> list[Action]:
    """`live` = sessions an active cc process is running. We still surface them
    (Mac-side, safe) but DEFER any Linux-write op (resume-fix, delete) for them."""
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

        # APP-BORN: already in the app's sidebar. Never surface. Push a CLI-resumable
        # copy to Linux (so `claude --resume` works), and hand back any entry we may
        # have hijacked in an earlier version.
        if L and L.app_born:
            if L.schema == "desktop":
                if uuid in live:
                    actions.append(Action("defer", uuid, L, "live: defer resume-fix"))
                else:
                    actions.append(Action("resume_fix", uuid, L, "app-born: make terminal-resumable"))
            if M:
                actions.append(Action("relinquish", uuid, L, "app-born: hand back to the app"))
            continue

        synced_before = bool(S and (S.linux or S.mac) and not (S and S.tombstone_side))

        # CLI-BORN: surface in the app; two-way thereafter.
        if L and not M:
            if synced_before and S and S.mac:
                # was on Mac, user removed it there -> delete on Linux
                if not propagate_deletions:
                    actions.append(Action("noop", uuid, L, "mac-deleted, propagation off"))
                elif uuid in live:
                    actions.append(Action("defer", uuid, L, "live: defer delete-to-Linux"))
                else:
                    actions.append(Action("delete_linux", uuid, L, "removed in Mac app"))
            else:
                actions.append(Action("surface", uuid, L, "new CLI session"))  # safe while live
            continue

        if M and not L:
            if synced_before and S and S.linux:
                actions.append(Action("delete_mac", uuid, M, "vanished on Linux"))
            else:
                actions.append(Action("noop", uuid, M, "mac-only, no Linux content"))
            continue

        if L and M:
            if M.archived:
                if propagate_deletions and uuid in live:
                    actions.append(Action("defer", uuid, L, "live: defer archive-delete"))
                elif propagate_deletions:
                    actions.append(Action("delete_linux", uuid, L, "archived in Mac app"))
                continue
            changed = not (S and S.linux and S.linux.hash == L.content_hash)
            actions.append(Action("update", uuid, L, "Linux content changed") if changed
                           else Action("noop", uuid, L, "unchanged"))
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

    live_set: set[str] = set()
    if cfg.skip_live:
        # sessions an active cc process is running — still surfaced, but Linux-writes deferred
        live_set = active_live(ssh.live_sessions(cfg), cfg.live_idle_seconds)

    try:
        reconcile_titles(cfg, linux, mac, store, summ, dry_run, live_set)
    except ssh.Unreachable:
        raise
    except Exception as e:
        summ.errors.append(f"rename: {e}")
        log.exception("title reconciliation failed")

    actions = plan(linux, mac, store,
                   propagate_deletions=cfg.propagate_deletions != "off", live=live_set)

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

    if a.kind == "defer":
        log.info("defer %s (%s)", a.uuid, a.reason)
        summ.deferred += 1
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

    if a.kind == "relinquish":
        # app-born session we'd hijacked: restore the genuine entry if we backed one
        # up, else just remove ours and let the app re-assert its native entry.
        log.info("relinquish %s (%s)", a.uuid, a.reason)
        if not dry_run:
            original = teardown._original_backup(a.uuid)
            if original:
                import shutil as _sh
                _sh.copy2(original, paths.index_entry_path(cfg.org, cfg.acct, a.uuid))
            else:
                index_writer.remove_entry(cfg, a.uuid)
            store.records.pop(a.uuid, None)
        summ.relinquished += 1
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
