# TODO — cc-remote-sync

## Spike (gating — needs the live Linux box + eyes on the Mac app)
- [ ] **#1 resume fidelity**: app-born `desktop`-schema session → does `claude --resume <uuid>`
      read it after `to_cli_records` conversion? Confirm full fidelity.
- [ ] **#2 forged entry**: inject ONE `local_<uuid>.json` → app shows it, resumes over SSH,
      and does not clobber it on relaunch / account re-sync.
- [ ] **#3 delete signal**: delete a session in the app → does it *remove* `local_<uuid>.json`
      or set `isArchived=true`? Pin the detection (code handles both).

## Features
- [x] **Session naming / two-way rename**: rename on the Mac app writes a custom-title
      record into the Linux transcript (so `claude --resume` shows it); rename in the
      terminal flows to the Mac entry. Baseline title tracked in the store; both-changed
      conflicts resolved last-writer-wins (tie → Mac). (`decide_rename` / `reconcile_titles`)

## Packaging
- [x] `py2app` build of the `.app` bundle (LSUIElement, bundle the assets + icns).
      `python setup.py py2app` (move pyproject.toml aside during build — py2app
      rejects PEP 621 `dependencies`). Output: `dist/cc-remote-sync.app`.
- [x] Launch-at-login via macOS Login Items (hidden). Installed to /Applications.

## Hardening
- [ ] Resume-fix "wrong location" case: app-born session stored under a non-cwd-slug dir on
      Linux — ensure the CLI copy lands at the cwd-slug path (currently in-place only).
- [ ] rsync scope optimization: only pull files modified within `scope_days`.
