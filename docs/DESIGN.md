# cc-remote-sync — Design

**Date:** 2026-05-28
**Status:** approved, implementing

## Problem

The Claude Code (cc) desktop app on macOS shows a session sidebar, but it only sees
sessions it tracks in its own store. Sessions started in a **plain terminal over SSH**
on the Linux box (the heavy-lifting machine) never appear. The owner switches surfaces
day to day — Mac app some days, Linux terminal others — and wants one unified, resumable
view, without using Remote Control (its live bridge has a TTL that does not survive
multi-day interruptions).

## Key mechanism (why this is possible)

The Mac app does **not** list sessions by scanning `~/.claude/projects/`. That directory
only holds transcript caches. The real index is the Electron store:

- `~/Library/Application Support/Claude/claude-code-sessions/<org>/<acct>/local_<uuid>.json`
  — one entry per session, carrying `cliSessionId`, `cwd`, `title`, `model`,
  `completedTurns`, `isArchived`, and an **`sshConfig` binding** (the resume target).
- `~/Library/Application Support/Claude/ssh_configs.json` — SSH hosts. The owner already
  has `Linux-4090 → zz@zz-machine.ddns.net:63330`.
- `~/.claude/projects/ssh-<uuid>/<uuid>.jsonl` — transcript cache (desktop
  `queue-operation` schema) for display.

So surfacing a terminal session = **forge a `local_<uuid>.json` index entry** with the
`Linux-4090` `sshConfig`, plus drop a transcript. The app already knows how to resume an
SSH-bound entry.

## Topology

- Runs **on the Mac**. Mac can SSH to Linux; Linux cannot reach the Mac. So the Mac
  **pulls** over SSH (`rsync`). One direction of transport only.
- A macOS **menu-bar app** (LSUIElement, no Dock icon) owns the process and the timer.

## Content-flow model (the important simplification)

cc **always executes on Linux** — whether started from the terminal directly or by the
app's SSH feature (which pushes a helper binary and runs cc on Linux). Therefore:

- **Transcript content is always sourced from Linux.** We never invent content on the Mac.
- **Linux → Mac:** for every Linux session bound to Linux-4090, ensure a Mac index entry
  exists + transcript mirrored. (surfaces terminal sessions in the app)
- **Mac → Linux:** two things only —
  1. **Resume-fix:** ensure every app-born session has a CLI-resumable (`custom-title`
     schema) copy at `~/.claude/projects/<cwd-slug>/<uuid>.jsonl` on Linux, so
     `claude --resume <uuid>` works in the terminal.
  2. **Deletions/archives:** if a session is deleted/archived in the Mac app, propagate a
     **soft delete** (move transcript to `~/.claude/.cc-remote-sync-trash/` on Linux).
- **Scope:** only sessions anchored to the Linux-4090 host. Local-Mac sessions
  (`cwd` under `/Users/...`) are out of scope.

## Components (isolated, unit-testable)

| Module | Responsibility |
|---|---|
| `paths.py` | macOS app-store paths, `cwd ↔ project-slug`, trash dir |
| `config.py` | load/save config; auto-discover `sshConfig`, `org/acct` from the app store |
| `schema.py` | detect (`custom-title` vs `queue-operation`) + convert transcripts; extract title/model/turns/last-activity |
| `store.py` | mapping store (JSON) keyed by `uuid`; per-side hash/mtime; tombstones |
| `ssh.py` | connectivity check, `rsync` pull, remote command/apply |
| `harvest.py` | build Linux + Mac session manifests |
| `index_writer.py` | create/update/remove `local_<uuid>.json` app index entries |
| `sync.py` | orchestrator: diff manifests vs store, apply, deletions, last-writer-wins |
| `cli.py` | `cc-remote-sync sync|status|list [--dry-run]` |
| `app.py` | rumps menu-bar app: 3 states, Retry, completion summary, notifications |

## Data structures

```
SessionRef:  uuid, side, cwd, slug, title, model, last_activity_ms,
             turns, archived, transcript_path, content_hash
StoreRecord: uuid, linux{slug,cwd,mtime,hash}|None, mac{index_path,mtime,hash}|None,
             last_synced_at, tombstone{side,at}|None
```

`cliSessionId` (uuid) is the stable cross-side key.

## Sync algorithm

Union of {Linux sessions, Mac index entries (Linux-4090), store keys}. Per uuid:

- on **Linux only**, not in store → new terminal session → create Mac index + mirror.
- on **Linux only**, in store, Mac entry gone → deleted on Mac → soft-delete on Linux
  (if `propagate_deletions != off`), tombstone.
- on **both** → ensure Mac entry current (content Linux→Mac) + resume-fix on Linux.
- Mac entry `isArchived=true` (or removed) while Linux session present → propagate
  delete/archive to Linux (trash), tombstone.
- in store, **Linux session vanished** → remove Mac index + transcript, tombstone.
- tombstoned but reappears with newer activity than tombstone → resurrect.

Single user, never both surfaces at once → conflicts rare. Tie-break by
`last_activity_ms` (last-writer-wins). The overwritten side is always **logged** and
backed up — no silent drops.

## Menu-bar UX

Three states; icon is a monochrome **template** image (`●⇄●`, two nodes + double arrow):

| State | Icon | Status line | Actions |
|---|---|---|---|
| Idle/OK | normal | `✓ Synced 2:14pm · 3↓ 1↑ 12=` | Sync now |
| Syncing (WIP) | dimmed | `Syncing…` | (disabled) |
| Cannot connect | `!` badge | `⚠ Can't reach Linux-4090` | **Retry** |

- **No automatic *immediate* retry** after a failure → show **Retry**, user clicks.
  The scheduled daily tick still attempts normally (timer may "hammer" — owner approved).
- **Completion summary** in the status line **and** a one-shot macOS notification.
  Legend: `↓` new-on-Mac · `↑` pushed-to-Linux · `=` unchanged · `skipped/errors`.
- Menu: status → Sync now / Retry → Auto-sync toggle + Interval (Daily ✓) →
  Open log… / Reveal mapping store… → Quit.

## Safety

- Linux deletes are **soft** (trash dir), never `rm`. Toggle: `To trash` (default) / `Off`.
- Back up any Mac index file before overwriting. Tool code is in git.
- No silent except — all errors logged/surfaced.

## Spike (must verify against the live Linux box — gating)

1. App-born session: does it land on Linux disk, in which schema, and does
   `claude --resume <uuid>` read it as-is? If not, does `queue-operation → custom-title`
   conversion make it resumable **with full fidelity**? *(gates the two-way promise)*
2. Inject one forged `local_<uuid>.json` → does the app show + resume it, and not clobber
   it on relaunch / account re-sync?
3. Delete a session in the app → does it **remove** `local_<uuid>.json` or set
   `isArchived=true`? (pins the delete-detection signal)

## Build / packaging

- Python + `rumps`, packaged to `.app` via `py2app`. `LSUIElement=1` (menu-bar only).
- Launch-at-login via a `LaunchAgent` (RunAtLoad) or Login Items.
- Icon: `assets/icon.svg` → menu-bar template PNGs (`rsvg-convert`) + `AppIcon.icns`
  (`iconutil`).

## Deferred / TODO

- **Session naming**: let the user name each session (custom title), surfaced in the app
  sidebar and synced both ways. (requested 2026-05-28)
