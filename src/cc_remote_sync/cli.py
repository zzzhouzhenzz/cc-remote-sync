"""Command line entry: `cc-remote-sync sync|status|list [--dry-run]`.
The menu-bar app calls into the same functions — this is just a headless face."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys

from . import config, harvest, paths, ssh, sync, teardown
from .store import Store


def _setup_logging() -> None:
    paths.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(paths.LOG_PATH), logging.StreamHandler(sys.stderr)],
    )


def cmd_sync(args) -> int:
    cfg = config.load()
    store = Store(paths.STORE_PATH).load()
    try:
        summ = sync.run(cfg, store, dry_run=args.dry_run)
    except ssh.Unreachable as e:
        print(f"cannot connect to {cfg.ssh_user_host}: {e}", file=sys.stderr)
        return 2
    print(("[dry-run] " if args.dry_run else "") + "synced: " + summ.line())
    for err in summ.errors:
        print("  ! " + err, file=sys.stderr)
    return 0


def cmd_status(args) -> int:
    cfg = config.load()
    store = Store(paths.STORE_PATH).load()
    print(f"host:   {cfg.ssh_user_host}:{cfg.ssh_port} ({cfg.ssh_config.get('name')})")
    print(f"scope:  last {cfg.scope_days} days   deletions: {cfg.propagate_deletions}")
    print(f"tracked sessions: {len(store.records)}")
    try:
        ssh.check(cfg)
        print("connection: OK")
    except ssh.Unreachable as e:
        print(f"connection: UNREACHABLE ({e})")
    return 0


def cmd_list(args) -> int:
    cfg = config.load()
    try:
        ssh.check(cfg)
        ssh.pull_projects(cfg)
    except ssh.Unreachable as e:
        print(f"cannot connect: {e}", file=sys.stderr)
        return 2
    linux, _ = harvest.linux_manifest(cfg)
    for ref in sorted(linux.values(), key=lambda r: r.last_activity_ms, reverse=True):
        print(f"{ref.uuid[:8]}  {ref.schema:7}  {ref.cwd:28}  {ref.title or ''}"[:110])
    print(f"\n{len(linux)} Linux sessions in scope")
    return 0


def cmd_reset(args) -> int:
    """Revert every entry we wrote and wipe our state — back to a clean slate."""
    cfg = config.load()
    store = Store(paths.STORE_PATH).load()
    restored, removed = teardown.revert_index(cfg, store)
    shutil.rmtree(paths.STATE_DIR, ignore_errors=True)  # backups read above, safe to wipe now
    print(f"reset: {restored} real entries restored, {removed} forged entries removed; state wiped")
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(prog="cc-remote-sync")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sync", help="run a sync")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sub.add_parser("status", help="show config + connection").set_defaults(func=cmd_status)
    sub.add_parser("list", help="list Linux sessions in scope").set_defaults(func=cmd_list)
    sub.add_parser("reset", help="revert all synced entries + wipe state").set_defaults(func=cmd_reset)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
