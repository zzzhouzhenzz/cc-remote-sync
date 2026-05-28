#!/usr/bin/env python3
"""Full teardown: quit app, remove login item + /Applications copy, drop build
artifacts, then revert every synced entry and wipe state.

Run from the project venv:  python scripts/uninstall.py
Use --keep-sessions to leave the app sidebar entries in place (only remove the app)."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "cc-remote-sync.app"
DEST = Path("/Applications") / APP_NAME
LOGIN_ITEM = "cc-remote-sync"


def run(cmd, check=True):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=check)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-sessions", action="store_true",
                    help="don't revert synced app entries; just remove the app")
    args = ap.parse_args()

    # 1. quit running copies (dist + installed)
    subprocess.run(["pkill", "-f", APP_NAME])

    # 2. remove login item
    run(["osascript", "-e",
         f'tell application "System Events" to if (exists login item "{LOGIN_ITEM}") '
         f'then delete login item "{LOGIN_ITEM}"'], check=False)

    # 3. remove installed app + build artifacts
    run(["rm", "-rf", str(DEST), str(ROOT / "build"), str(ROOT / "dist")])

    # 4. revert app entries + wipe state (unless asked to keep)
    if not args.keep_sessions:
        from cc_remote_sync import cli
        cli.cmd_reset(argparse.Namespace())

    print("\n✓ uninstalled.")


if __name__ == "__main__":
    main()
