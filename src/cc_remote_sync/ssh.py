"""SSH/rsync transport. Mac pulls from Linux; nothing is ever pushed to the Mac."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

from .config import Config
from . import paths

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class Unreachable(Exception):
    """Raised when the Linux box can't be reached. The app turns this into the
    'Cannot connect' state + Retry button — never an auto-retry loop."""


def _ssh_base(cfg: Config) -> list[str]:
    return [
        "ssh", "-p", str(cfg.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        cfg.ssh_user_host,
    ]


def check(cfg: Config) -> None:
    """Fast reachability probe. Raises Unreachable on failure."""
    try:
        r = subprocess.run(
            _ssh_base(cfg) + ["true"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise Unreachable(str(e)) from e
    if r.returncode != 0:
        raise Unreachable(r.stderr.strip() or f"ssh exit {r.returncode}")


def pull_projects(cfg: Config) -> None:
    """rsync the remote transcripts (*.jsonl only) into the local staging mirror."""
    paths.STAGING_DIR.mkdir(parents=True, exist_ok=True)
    remote = f"{cfg.ssh_user_host}:{paths.REMOTE_PROJECTS}/"
    rsh = f"ssh -p {cfg.ssh_port} -o BatchMode=yes -o ConnectTimeout=8"
    cmd = [
        "rsync", "-rtz", "--delete", "-e", rsh,
        "--include=*/", "--include=*.jsonl", "--exclude=*",
        remote, str(paths.STAGING_DIR) + "/",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise Unreachable(f"rsync pull failed: {r.stderr.strip()}")


def run_remote(cfg: Config, command: str) -> tuple[int, str, str]:
    r = subprocess.run(
        _ssh_base(cfg) + [command],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode, r.stdout, r.stderr


def push_file(cfg: Config, local: Path, remote_rel: str) -> None:
    """Copy one file to the remote (relative to remote $HOME). Used for the
    CLI-resumable copies that make `claude --resume` work in the terminal."""
    rsh = f"ssh -p {cfg.ssh_port} -o BatchMode=yes -o ConnectTimeout=8"
    # ensure the remote dir exists
    remote_dir = str(Path(remote_rel).parent)
    run_remote(cfg, f"mkdir -p {shlex.quote(remote_dir)}")
    dest = f"{cfg.ssh_user_host}:{shlex.quote(remote_rel)}"
    r = subprocess.run(
        ["rsync", "-tz", "-e", rsh, str(local), dest],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        raise Unreachable(f"rsync push failed: {r.stderr.strip()}")


# Remote probe: for each session marker whose PID is ALIVE, emit
# "<sessionId> <seconds_since_last_heartbeat> <status> <kind> <pid>".
# Heartbeat = max(marker.updatedAt, marker file mtime) — works whether or not the
# cc version writes updatedAt. Staleness is computed on Linux to avoid clock skew.
_LIVE_PROBE = (
    "import json,glob,os,time\n"
    "now=time.time()\n"
    'for f in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):\n'
    " b=os.path.basename(f)[:-5]\n"
    " if not b.isdigit(): continue\n"
    " try: os.kill(int(b),0)\n"
    " except OSError: continue\n"
    " try: d=json.load(open(f))\n"
    " except Exception: continue\n"
    ' sid=d.get("sessionId")\n'
    " if not sid: continue\n"
    ' upd=(d.get("updatedAt") or 0)/1000.0\n'
    " hb=max(upd, os.path.getmtime(f))\n"
    ' print(sid, int(now-hb), d.get("status") or "-", d.get("kind") or "-", b)\n'
)


def _parse_live(output: str) -> dict[str, dict]:
    """Parse probe lines '<uuid> <idle_seconds> <status> <kind> <pid>'. Pure, tested."""
    live: dict[str, dict] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or not re.fullmatch(_UUID, parts[0]):
            continue
        try:
            idle = int(parts[1])
        except ValueError:
            continue
        live[parts[0]] = {
            "idle_seconds": idle,
            "status": parts[2] if len(parts) > 2 else "-",
            "kind": parts[3] if len(parts) > 3 else "-",
            "pid": parts[4] if len(parts) > 4 else None,
        }
    return live


def live_sessions(cfg: Config) -> dict[str, dict]:
    """Sessions a live, HEARTBEATING cc process is running on Linux, with how long
    since each last heartbeat. A process that is alive but not heartbeating (a stale,
    lingering ccd-cli) reports a large idle_seconds and is treated as not-running by
    the caller. Source: ~/.claude/sessions/<PID>.json markers + PID liveness."""
    rc, out, err = run_remote(cfg, f"python3 -c '{_LIVE_PROBE}'")
    if rc != 0:
        raise Unreachable(f"live-session probe failed: {err.strip()}")
    return _parse_live(out)


def soft_delete_remote(cfg: Config, remote_rel: str, uuid: str) -> None:
    """Move a remote transcript to the trash dir. Never rm — recoverable."""
    trash = f"{paths.REMOTE_TRASH}"
    cmd = (
        f"mkdir -p {shlex.quote(trash)} && "
        f"if [ -f {shlex.quote(remote_rel)} ]; then "
        f"mv -f {shlex.quote(remote_rel)} {shlex.quote(trash + '/' + uuid + '.jsonl')}; fi"
    )
    rc, _, err = run_remote(cfg, cmd)
    if rc != 0:
        raise Unreachable(f"remote soft-delete failed: {err.strip()}")
