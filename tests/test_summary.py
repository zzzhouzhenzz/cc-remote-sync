from cc_remote_sync.sync import Summary


def test_line_basic():
    assert Summary(created=3, pushed=1, unchanged=12).line() == "3↓ 1↑ 12="


def test_line_surfaces_skipped():
    s = Summary(created=2, pushed=0, unchanged=5, skipped=2)
    assert "2⏭" in s.line()


def test_line_shows_deletes_and_errors():
    s = Summary(created=0, pushed=0, unchanged=1, deleted=1, errors=["boom"])
    line = s.line()
    assert "1✗" in line and "1!" in line
