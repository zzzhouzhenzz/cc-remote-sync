"""Live-session detection. A session counts as 'actively running' iff a live cc
process holds it AND it reports an active status or a fresh heartbeat. Active
sessions are still SURFACED; only their Linux-writes are deferred (see test_sync_plan)."""
from cc_remote_sync.ssh import _parse_live
from cc_remote_sync.sync import active_live

IDLE = 300


def test_active_status_counts_even_when_heartbeat_old():
    live = {"busy": {"idle_seconds": 999, "status": "busy", "pid": "1"}}
    assert active_live(live, IDLE) == {"busy"}


def test_fresh_heartbeat_without_status_counts():
    live = {"u": {"idle_seconds": 40, "status": "-", "pid": "9"}}
    assert active_live(live, IDLE) == {"u"}


def test_stale_no_status_is_not_active():
    live = {"stale": {"idle_seconds": 5072, "status": "-", "pid": "5358"}}
    assert active_live(live, IDLE) == set()


def test_empty_live_is_empty():
    assert active_live({}, IDLE) == set()


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
