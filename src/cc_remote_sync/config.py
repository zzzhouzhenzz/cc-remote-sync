"""Config: a few knobs, plus auto-discovery of the app's SSH host binding and
the org/acct path so the user configures nothing by hand."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from . import paths


@dataclass
class SshConfig:
    name: str
    sshHost: str
    sshPort: int
    id: str


@dataclass
class Config:
    ssh_config: dict          # the Linux-4090 binding, embedded into index entries
    org: str                  # claude-code-sessions/<org>/<acct>
    acct: str
    remote_home: str = "/home/user"   # overridden by bootstrap() from the SSH user
    scope_days: int = 60
    auto_sync: bool = True
    interval: str = "daily"   # daily | 6h | 1h | manual
    propagate_deletions: str = "trash"  # trash | off
    skip_live: bool = True  # skip sessions a live cc process is currently running (process-based)
    skip_active_minutes: int = 10  # deprecated: old time-based heuristic, kept for config back-compat
    ssh_user_host: str = ""   # for ssh/rsync, e.g. "user@your-linux-host"
    ssh_port: int = 22

    def save(self) -> None:
        paths.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))


def _discover_ssh_config() -> SshConfig:
    data = json.loads(paths.SSH_CONFIGS_JSON.read_text())
    configs = data.get("configs") or []
    if not configs:
        raise RuntimeError(
            f"No SSH host configured in {paths.SSH_CONFIGS_JSON}. "
            "Add your Linux host in the Claude app's SSH settings first."
        )
    return SshConfig(**configs[0])  # single user, first host is the one


def _discover_org_acct() -> tuple[str, str]:
    root = paths.SESSIONS_INDEX_ROOT
    orgs = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    if not orgs:
        raise RuntimeError(
            f"No app session index under {root}. Open the Claude desktop app and "
            "start at least one SSH session so it creates the store, then retry."
        )
    org = orgs[0]
    accts = [p for p in org.iterdir() if p.is_dir()]
    if not accts:
        raise RuntimeError(f"No account dir under {org}.")
    return org.name, accts[0].name


def load() -> Config:
    if paths.CONFIG_PATH.exists():
        d = json.loads(paths.CONFIG_PATH.read_text())
        return Config(**d)
    return bootstrap()


def bootstrap() -> Config:
    """First run: derive everything from the app's own store and persist it."""
    ssh = _discover_ssh_config()
    org, acct = _discover_org_acct()
    user_host = ssh.sshHost            # "user@your-linux-host"
    cfg = Config(
        ssh_config=asdict(ssh),
        org=org,
        acct=acct,
        ssh_user_host=user_host,
        ssh_port=ssh.sshPort,
        remote_home="/home/" + (user_host.split("@", 1)[0] if "@" in user_host else "zz"),
    )
    cfg.save()
    return cfg
