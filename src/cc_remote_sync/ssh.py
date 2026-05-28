"""SSH/rsync transport. Mac pulls from Linux; nothing is ever pushed to the Mac."""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .config import Config
from . import paths


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
