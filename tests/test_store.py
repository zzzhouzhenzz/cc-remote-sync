from cc_remote_sync.store import Record, SideState, Store


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = Store(path)
    s.upsert(Record(uuid="u1", cwd="/home/zz/ml",
                    linux=SideState(hash="h1", mtime_ms=10),
                    mac=SideState(hash="h1", mtime_ms=10)))
    s.save()

    s2 = Store(path).load()
    r = s2.get("u1")
    assert r is not None
    assert r.cwd == "/home/zz/ml"
    assert r.linux.hash == "h1"
    assert r.last_synced_ms > 0


def test_tombstone(tmp_path):
    s = Store(tmp_path / "state.json")
    s.upsert(Record(uuid="u1", linux=SideState(hash="h")))
    s.tombstone("u1", "mac", "/home/zz/ml")
    assert s.is_tombstoned("u1")
    r = s.get("u1")
    assert r.tombstone_side == "mac"
    assert r.linux is None and r.mac is None
    assert r.tombstone_ms > 0


def test_missing_file_loads_empty(tmp_path):
    s = Store(tmp_path / "nope.json").load()
    assert s.records == {}
