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


IDLE = 300


def test_active_status_is_skipped_even_when_heartbeat_is_old():
    # 837d107f: busy interactive session whose marker last updated 303s ago -> SKIP
    linux = {"busy": ref("busy"), "stale": ref("stale"), "idle": ref("idle")}
    mac = {"busy": ref("busy")}
    live = {
        "busy":  {"idle_seconds": 303, "status": "busy", "pid": "12660"},   # active status
        "stale": {"idle_seconds": 5072, "status": "-", "pid": "5358"},      # no status, idle 84m
    }
    skipped = filter_active(linux, mac, live, IDLE)
    assert skipped == 1
    assert "busy" not in linux and "busy" not in mac   # active status -> skipped
    assert "stale" in linux                            # lingering -> synced
    assert "idle" in linux                             # no process -> synced


def test_no_status_but_fresh_heartbeat_is_skipped():
    # a status-less marker (old ccd-cli) that DID just heartbeat -> still active -> skip
    linux = {"u": ref("u")}
    filter_active(linux, {}, {"u": {"idle_seconds": 40, "status": "-", "pid": "9"}}, IDLE)
    assert "u" not in linux


def test_no_status_and_stale_heartbeat_is_synced():
    linux = {"u": ref("u")}
    filter_active(linux, {}, {"u": {"idle_seconds": 5072, "status": "-", "pid": "9"}}, IDLE)
    assert "u" in linux  # alive but no status + idle 84min -> not actively running -> synced


def test_no_process_is_never_skipped():
    # the user's e1493430 case: used 4 min ago, detached, no process -> NOT skipped
    linux = {"e1493430": ref("e1493430")}
    assert filter_active(linux, {}, live={}, max_idle_seconds=IDLE) == 0
    assert "e1493430" in linux


# --- live-session probe parsing (pure): "<uuid> <idle> <status> <kind> <pid>" ---

PROBE = (
    "837d107f-0611-4579-9673-96d654740894 83 busy interactive 12660\n"
    "e6d1438b-d8df-42dd-ab49-e334a4aaff7c 5072 - interactive 5358\n"
)


def test_parse_live_probe_lines():
    live = _parse_live(PROBE)
    assert set(live) == {
        "837d107f-0611-4579-9673-96d654740894",
        "e6d1438b-d8df-42dd-ab49-e334a4aaff7c",
    }
    assert live["837d107f-0611-4579-9673-96d654740894"] == {
        "idle_seconds": 83, "status": "busy", "kind": "interactive", "pid": "12660"}
    assert live["e6d1438b-d8df-42dd-ab49-e334a4aaff7c"]["idle_seconds"] == 5072


def test_parse_live_ignores_garbage():
    assert _parse_live("not a uuid line\n\nfoo bar\n") == {}
