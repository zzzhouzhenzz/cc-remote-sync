"""All filesystem paths and the cwd<->slug mapping. One place, no guessing."""
from __future__ import annotations

import re
from pathlib import Path

HOME = Path.home()

# macOS Claude Code stores
CLAUDE_DIR = HOME / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
APP_SUPPORT = HOME / "Library" / "Application Support" / "Claude"
SSH_CONFIGS_JSON = APP_SUPPORT / "ssh_configs.json"
SESSIONS_INDEX_ROOT = APP_SUPPORT / "claude-code-sessions"

# Our own state
STATE_DIR = CLAUDE_DIR / "cc-remote-sync"
STORE_PATH = STATE_DIR / "state.json"
CONFIG_PATH = STATE_DIR / "config.json"
LOG_PATH = STATE_DIR / "cc-remote-sync.log"
BACKUP_DIR = STATE_DIR / "backups"

# Remote (Linux) layout, relative to the remote $HOME
REMOTE_PROJECTS = ".claude/projects"
REMOTE_TRASH = ".claude/.cc-remote-sync-trash"

# Local staging mirror of the remote projects tree (rsync target)
STAGING_DIR = STATE_DIR / "staging" / "remote-projects"


def cwd_to_slug(cwd: str) -> str:
    """cc derives a project dir name from the cwd by replacing every run of
    non-[A-Za-z0-9] characters with a single '-'. Verified against real slugs
    e.g. '/Users/zhouzhen24/Documents/coding/ml' -> '-Users-zhouzhen24-Documents-coding-ml'.
    """
    return re.sub(r"[^A-Za-z0-9]+", "-", cwd)


def remote_project_dir(cwd: str) -> str:
    """Path (relative to remote $HOME) of the CLI project dir for a given cwd."""
    return f"{REMOTE_PROJECTS}/{cwd_to_slug(cwd)}"


def mac_transcript_path(uuid: str) -> Path:
    """Where the app expects an SSH session's transcript cache to live."""
    return PROJECTS_DIR / f"ssh-{uuid}" / f"{uuid}.jsonl"


def index_entry_path(org: str, acct: str, uuid: str) -> Path:
    return SESSIONS_INDEX_ROOT / org / acct / f"local_{uuid}.json"


def ensure_dirs() -> None:
    for d in (STATE_DIR, BACKUP_DIR, STAGING_DIR):
        d.mkdir(parents=True, exist_ok=True)
