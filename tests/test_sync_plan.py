"""The pure decision layer. No SSH, no filesystem — just the diff logic."""
from pathlib import Path

from cc_remote_sync.models import SessionRef
from cc_remote_sync.store import Record, SideState, Store
from cc_remote_sync.sync import plan


def ref(uuid, side, *, schema="cli", h="h", last=100, archived=False,
        cwd="/home/zz/ml", app_born=False):
    return SessionRef(uuid=uuid, side=side, cwd=cwd, title="t", model="m",
                      last_activity_ms=last, turns=1,
                      transcript_path=Path(f"/tmp/{uuid}.jsonl"),
                      content_hash=h, schema=schema, archived=archived, app_born=app_born)


def store_with(*records) -> Store:
    s = Store(Path("/tmp/none.json"))
    for r in records:
        s.records[r.uuid] = r
    return s


def kinds(actions, uuid):
    return {a.kind for a in actions if a.uuid == uuid}


def test_new_linux_session_is_surfaced():
    acts = plan({"u": ref("u", "linux")}, {}, store_with(), propagate_deletions=True)
    assert kinds(acts, "u") == {"surface"}


def test_app_born_session_is_not_surfaced_but_resume_fixed():
    # app-born + desktop schema: don't surface (already in the app), push CLI copy to Linux
    acts = plan({"u": ref("u", "linux", schema="desktop", app_born=True)}, {}, store_with(),
                propagate_deletions=True)
    assert kinds(acts, "u") == {"resume_fix"}


def test_live_cli_session_is_still_surfaced():
    # the user's point: an actively-running terminal session must still get an app
    # entry (surface) so it's visible/startable — surfacing is Mac-side, never races
    acts = plan({"u": ref("u", "linux")}, {}, store_with(),
                propagate_deletions=True, live={"u"})
    assert kinds(acts, "u") == {"surface"}


def test_live_app_born_resume_fix_is_deferred():
    # writing a CLI copy to a live transcript would race -> defer until idle
    acts = plan({"u": ref("u", "linux", schema="desktop", app_born=True)}, {}, store_with(),
                propagate_deletions=True, live={"u"})
    assert kinds(acts, "u") == {"defer"}


def test_live_delete_to_linux_is_deferred():
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux")}, {}, s, propagate_deletions=True, live={"u"})
    assert kinds(acts, "u") == {"defer"}    # don't soft-delete a running session


def test_app_born_already_cli_resumable_is_left_alone():
    # app-born already in CLI schema: nothing to do (in the app + terminal-resumable)
    acts = plan({"u": ref("u", "linux", schema="cli", app_born=True)}, {}, store_with(),
                propagate_deletions=True)
    assert kinds(acts, "u") == set()


def test_app_born_hijacked_entry_is_relinquished():
    # we previously surfaced an app-born session -> hand it back to the app
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux", schema="cli", app_born=True)},
                {"u": ref("u", "mac")}, s, propagate_deletions=True)
    assert kinds(acts, "u") == {"relinquish"}


def test_deleted_on_mac_propagates_to_linux():
    s = store_with(Record(uuid="u", cwd="/home/zz/ml",
                          linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux")}, {}, s, propagate_deletions=True)
    assert kinds(acts, "u") == {"delete_linux"}


def test_deleted_on_mac_respects_propagation_off():
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux")}, {}, s, propagate_deletions=False)
    assert kinds(acts, "u") == {"noop"}


def test_vanished_on_linux_removes_mac_entry():
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({}, {"u": ref("u", "mac")}, s, propagate_deletions=True)
    assert kinds(acts, "u") == {"delete_mac"}


def test_both_unchanged_is_noop():
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux", h="h")}, {"u": ref("u", "mac", h="h")}, s,
                propagate_deletions=True)
    assert "noop" in kinds(acts, "u") and "update" not in kinds(acts, "u")


def test_both_changed_triggers_update():
    s = store_with(Record(uuid="u", linux=SideState(hash="OLD"), mac=SideState(hash="OLD")))
    acts = plan({"u": ref("u", "linux", h="NEW")}, {"u": ref("u", "mac", h="NEW")}, s,
                propagate_deletions=True)
    assert "update" in kinds(acts, "u")


def test_archived_on_mac_propagates_delete():
    s = store_with(Record(uuid="u", linux=SideState(hash="h"), mac=SideState(hash="h")))
    acts = plan({"u": ref("u", "linux")}, {"u": ref("u", "mac", archived=True)}, s,
                propagate_deletions=True)
    assert kinds(acts, "u") == {"delete_linux"}


def test_tombstone_blocks_resurrection_when_stale():
    s = store_with(Record(uuid="u", tombstone_side="mac", tombstone_ms=200))
    acts = plan({"u": ref("u", "linux", last=100)}, {}, s, propagate_deletions=True)
    assert kinds(acts, "u") == set()  # stays dead


def test_tombstone_resurrects_on_newer_activity():
    s = store_with(Record(uuid="u", tombstone_side="mac", tombstone_ms=50))
    acts = plan({"u": ref("u", "linux", last=100)}, {}, s, propagate_deletions=True)
    assert "surface" in kinds(acts, "u")
