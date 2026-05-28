# cc-remote-sync

Make Linux terminal Claude Code sessions show up — and resume — in the macOS app,
two ways, on a timer. A menu-bar app that runs on the Mac and pulls from Linux over SSH.

## Why

The Claude Code desktop app only lists sessions in its own store. Sessions you start in
a plain terminal over SSH on the Linux box never appear. This bridges them: it forges the
app's index entries (`local_<uuid>.json`, bound to your `Linux-4090` SSH host) so terminal
sessions appear in the sidebar and resume over SSH, and it keeps a CLI-resumable copy on
Linux so `claude --resume` works in the terminal too.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design and the data model.

## How it works

- Runs **on the Mac** (Mac can SSH to Linux; not the reverse). Pulls transcripts with `rsync`.
- The mapping store (`~/.claude/cc-remote-sync/state.json`) remembers what was synced, so a
  vanished session reads as a *delete*, not a *new* one. Deletions propagate as **soft**
  deletes (Linux trash dir), never `rm`.
- Auto-discovers your SSH host + the app's org/account paths from the app's own store — no
  manual config.

## Use

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python scripts/make_icons.py          # build the menu-bar + app icons

cc-remote-sync status                  # config + connection
cc-remote-sync list                    # Linux sessions in scope
cc-remote-sync sync --dry-run          # show what would change, mutate nothing
cc-remote-sync sync                    # do it

python -m cc_remote_sync.app           # run the menu-bar app (dev)
```

## Install / uninstall (menu-bar app, launches at login)

```bash
pip install py2app
python scripts/install.py      # icons -> .app -> /Applications -> login item -> launch
python scripts/uninstall.py    # quit, remove app + login item, revert synced entries, wipe state
```

`install.py` is idempotent (re-run to upgrade). The app runs one sync ~0.4s after
launch, so a fresh install populates the sidebar immediately rather than waiting for
the daily timer. `uninstall.py` restores genuine app sessions and removes only the
entries this tool created (`--keep-sessions` leaves the sidebar untouched).

## Menu-bar app

Three states: **OK** / **Syncing** / **Cannot connect**. A failed sync shows a **Retry**
button (no automatic immediate retry); the scheduled tick still runs. Completion shows a
summary in the menu and a notification. Legend: `↓` surfaced on Mac · `↑` pushed to Linux ·
`=` unchanged · `✎` renamed · `⤺` app-born entry handed back to the app · `⏸` a Linux-side
write was deferred because the session is live · `⊘` Mac entry with no Linux session in
scope (orphan).

**Live sessions are still surfaced.** An actively-running session always gets its app entry
(creating it only reads Linux + writes Mac-side, so it never races), so it stays visible and
startable in the app. We defer only the operations that *write the live transcript on Linux*
— resume-fix, rename push, delete propagation (`⏸`) — until the session is idle. "Live" is
process-based: a session counts as active only while a cc process holds it
(`~/.claude/sessions/<PID>.json` markers) and reports a live status or fresh heartbeat, never
merely because it was recently active. Deferred writes retry automatically on the next sync.

## Tests

```bash
python -m pytest -q
```

## Status

Engine + menu-bar app + icons built and unit-tested; full pipeline validated against the
live box via `--dry-run`. The live mutation path (forging entries, resume-fix) is gated on
the spike in `docs/DESIGN.md` — verify one session in the app before enabling auto-sync.
