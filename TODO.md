# TODO — cc-remote-sync

## Spike (gating — needs the live Linux box + eyes on the Mac app)
- [ ] **#1 resume fidelity**: app-born `desktop`-schema session → does `claude --resume <uuid>`
      read it after `to_cli_records` conversion? Confirm full fidelity.
- [ ] **#2 forged entry**: inject ONE `local_<uuid>.json` → app shows it, resumes over SSH,
      and does not clobber it on relaunch / account re-sync.
- [ ] **#3 delete signal**: delete a session in the app → does it *remove* `local_<uuid>.json`
      or set `isArchived=true`? Pin the detection (code handles both).

## Features
- [ ] **Session naming**: let each session be given a custom name; surface it in the app
      sidebar and sync the title both ways. (requested 2026-05-28)

## Packaging
- [ ] `py2app` build of the `.app` bundle (LSUIElement, bundle the assets + icns).
- [ ] Launch-at-login (LaunchAgent RunAtLoad or Login Items).

## Hardening
- [ ] Resume-fix "wrong location" case: app-born session stored under a non-cwd-slug dir on
      Linux — ensure the CLI copy lands at the cwd-slug path (currently in-place only).
- [ ] rsync scope optimization: only pull files modified within `scope_days`.
