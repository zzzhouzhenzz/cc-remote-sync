import json

from cc_remote_sync import paths, teardown
from cc_remote_sync.config import Config
from cc_remote_sync.store import Record, Store


def _cfg():
    return Config(ssh_config={"id": "x"}, org="O", acct="A")


def test_forged_entries_removed_real_entries_restored(tmp_path, monkeypatch):
    idx = tmp_path / "index"
    proj = tmp_path / "projects"
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(paths, "SESSIONS_INDEX_ROOT", idx)
    monkeypatch.setattr(paths, "PROJECTS_DIR", proj)
    monkeypatch.setattr(paths, "BACKUP_DIR", bdir)

    cfg = _cfg()
    entry_dir = idx / "O" / "A"
    entry_dir.mkdir(parents=True)

    # forged entry: no backup -> should be removed, with its transcript dir
    forged = paths.index_entry_path("O", "A", "forged")
    forged.write_text(json.dumps({"cliSessionId": "forged"}))
    tdir = paths.mac_transcript_path("forged").parent
    tdir.mkdir(parents=True)
    (tdir / "forged.jsonl").write_text("x")

    # real entry: backup is a genuine (non-tool) entry -> restored
    real = paths.index_entry_path("O", "A", "real")
    real.write_text(json.dumps({"title": "OVERWRITTEN", "sshConfig": {"source": "cc-remote-sync"}}))
    (bdir / "local_real.json.1000.bak").write_text(
        json.dumps({"title": "ORIGINAL", "sshConfig": {"source": "desktop"}}))

    # re-forged entry: its only backup is OUR own forged v1 -> must be removed, not restored
    twice = paths.index_entry_path("O", "A", "twice")
    twice.write_text(json.dumps({"sshConfig": {"source": "cc-remote-sync"}}))
    (bdir / "local_twice.json.500.bak").write_text(
        json.dumps({"sshConfig": {"source": "cc-remote-sync"}}))

    store = Store(tmp_path / "s.json")
    for u in ("forged", "real", "twice"):
        store.records[u] = Record(uuid=u)

    restored, removed = teardown.revert_index(cfg, store)

    assert (restored, removed) == (1, 2)
    assert not forged.exists()
    assert not tdir.exists()
    assert not twice.exists()                                   # forged-twice fully removed
    assert json.loads(real.read_text())["title"] == "ORIGINAL"  # real restored


def test_restores_genuine_original_ignoring_our_forged_backup(tmp_path, monkeypatch):
    idx = tmp_path / "index"
    bdir = tmp_path / "backups"
    bdir.mkdir()
    monkeypatch.setattr(paths, "SESSIONS_INDEX_ROOT", idx)
    monkeypatch.setattr(paths, "BACKUP_DIR", bdir)
    (idx / "O" / "A").mkdir(parents=True)

    entry = paths.index_entry_path("O", "A", "u")
    entry.write_text(json.dumps({"v": "current"}))
    # oldest backup is the genuine original; a later backup is our forged version
    (bdir / "local_u.json.100.bak").write_text(
        json.dumps({"v": "REAL", "sshConfig": {"source": "desktop"}}))
    (bdir / "local_u.json.900.bak").write_text(
        json.dumps({"v": "ours", "sshConfig": {"source": "cc-remote-sync"}}))

    store = Store(tmp_path / "s.json")
    store.records["u"] = Record(uuid="u")
    teardown.revert_index(_cfg(), store)
    assert json.loads(entry.read_text())["v"] == "REAL"
