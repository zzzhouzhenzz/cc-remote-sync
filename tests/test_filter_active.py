from pathlib import Path

from cc_remote_sync.models import SessionRef
from cc_remote_sync.sync import filter_active


def ref(uuid, last):
    return SessionRef(uuid=uuid, side="linux", cwd="/home/zz/ml", title="t", model="m",
                      last_activity_ms=last, turns=1,
                      transcript_path=Path("/tmp/x"), content_hash="h")


def test_skips_recently_active_and_keeps_quiet():
    linux = {"hot": ref("hot", 1000), "cold": ref("cold", 100)}
    mac = {"hot": ref("hot", 1000)}
    skipped = filter_active(linux, mac, cutoff_ms=500)
    assert skipped == 1
    assert "hot" not in linux and "hot" not in mac   # the live one is untouched
    assert "cold" in linux                            # the quiet one still syncs


def test_uses_max_activity_across_sides():
    # quiet on Linux but recently touched on Mac -> still considered live
    linux = {"u": ref("u", 100)}
    mac = {"u": ref("u", 1000)}
    assert filter_active(linux, mac, cutoff_ms=500) == 1
    assert not linux and not mac
