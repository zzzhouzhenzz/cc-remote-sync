from cc_remote_sync.sync import Action, Summary, _apply


def test_line_basic():
    assert Summary(created=3, pushed=1, unchanged=12).line() == "3↓ 1↑ 12="


def test_line_surfaces_deferred():
    s = Summary(created=2, pushed=0, unchanged=5, deferred=2)
    assert "2⏸" in s.line()


def test_line_distinguishes_deferred_from_orphans():
    s = Summary(deferred=1, no_source=3)
    line = s.line()
    assert "1⏸" in line          # live: Linux-write deferred
    assert "3⊘" in line          # mac-only orphans, shown separately
    assert "live" not in line    # neither is labeled "live" in the compact line


def test_apply_noop_categorization():
    """Orphan/no-op noops must NOT count as deferred (live) — the 3-skipped bug."""
    summ = Summary()
    _apply(None, None, Action("noop", "u1", None, "unchanged"), summ, True)
    _apply(None, None, Action("noop", "u2", None, "mac-only, no Linux content"), summ, True)
    _apply(None, None, Action("noop", "u3", None, "mac-deleted, propagation off"), summ, True)
    assert summ.unchanged == 1
    assert summ.no_source == 2
    assert summ.deferred == 0     # only live Linux-write deferrals count as deferred


def test_line_shows_deletes_and_errors():
    s = Summary(created=0, pushed=0, unchanged=1, deleted=1, errors=["boom"])
    line = s.line()
    assert "1✗" in line and "1!" in line
