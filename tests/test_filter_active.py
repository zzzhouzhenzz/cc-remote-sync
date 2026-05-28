"""Live-skip: a session is skipped iff a live cc process is running it (process
markers), NOT because it was recently active."""
from pathlib import Path

from cc_remote_sync.models import SessionRef
from cc_remote_sync.ssh import _parse_live
from cc_remote_sync.sync import filter_active


def ref(uuid):
    return SessionRef(uuid=uuid, side="linux", cwd="/home/zz/ml", title="t", model="m",
                      last_activity_ms=0, turns=1,
                      transcript_path=Path("/tmp/x"), content_hash="h")


def test_skips_only_sessions_with_a_live_process():
    linux = {"running": ref("running"), "idle": ref("idle")}
    mac = {"running": ref("running")}
    live = {"running": {"pid": 12660, "status": "busy", "kind": "interactive"}}
    skipped = filter_active(linux, mac, live)
    assert skipped == 1
    assert "running" not in linux and "running" not in mac   # live -> skipped
    assert "idle" in linux                                   # no process -> synced


def test_recently_active_but_no_process_is_not_skipped():
    # the user's case: used 4 min ago, now detached -> not in live set -> NOT skipped
    linux = {"e1493430": ref("e1493430")}
    assert filter_active(linux, {}, live={}) == 0
    assert "e1493430" in linux


# --- live-session probe parsing (pure) ---

MARKERS = (
    '{"pid":12660,"sessionId":"837d107f-0611-4579-9673-96d654740894","status":"busy","kind":"interactive"}\n'
    '{"pid":5358,"sessionId":"e6d1438b-d8df-42dd-ab49-e334a4aaff7c","kind":"interactive"}\n'
    '--resume e4c6802f-5919-4607-b0e9-c38d1f6760f2\n'
)


def test_parse_live_from_markers_and_resume_args():
    live = _parse_live(MARKERS)
    assert set(live) == {
        "837d107f-0611-4579-9673-96d654740894",
        "e6d1438b-d8df-42dd-ab49-e334a4aaff7c",
        "e4c6802f-5919-4607-b0e9-c38d1f6760f2",
    }
    assert live["837d107f-0611-4579-9673-96d654740894"]["status"] == "busy"
    assert live["e4c6802f-5919-4607-b0e9-c38d1f6760f2"]["via"] == "--resume"


def test_parse_live_ignores_garbage():
    assert _parse_live("not json\n\n{bad}\n") == {}
