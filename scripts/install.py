#!/usr/bin/env python3
"""End-to-end install: icons -> py2app build -> /Applications -> login item -> launch.
Run from the project venv:  python scripts/install.py

Idempotent: re-running rebuilds and replaces a previous install cleanly."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "cc-remote-sync.app"
DEST = Path("/Applications") / APP_NAME
LOGIN_ITEM = "cc-remote-sync"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def main():
    # 1. icons
    run([sys.executable, str(ROOT / "scripts" / "make_icons.py")])

    # 2. build .app — py2app rejects PEP 621 deps, so hide pyproject during build
    pyproject = ROOT / "pyproject.toml"
    hidden = ROOT / "_pyproject.toml.hidden"
    run(["rm", "-rf", str(ROOT / "build"), str(ROOT / "dist")])
    pyproject.rename(hidden)
    try:
        run([sys.executable, "setup.py", "py2app"], cwd=ROOT)
    finally:
        hidden.rename(pyproject)

    built = ROOT / "dist" / APP_NAME
    if not built.exists():
        sys.exit("build failed: dist/cc-remote-sync.app missing")

    # 3. install to /Applications (quit any running copy first)
    subprocess.run(["pkill", "-f", APP_NAME])
    run(["rm", "-rf", str(DEST)])
    run(["cp", "-R", str(built), str(DEST)])

    # 4. login item (hidden), idempotent
    run(["osascript", "-e", f'''
tell application "System Events"
    if (exists login item "{LOGIN_ITEM}") then delete login item "{LOGIN_ITEM}"
    make login item at end with properties {{path:"{DEST}", hidden:true}}
end tell'''])

    # 5. launch
    run(["open", str(DEST)])
    print(f"\n✓ installed {DEST}, login item set, launched. Look for the ●⇄● menu-bar icon.")


if __name__ == "__main__":
    main()
