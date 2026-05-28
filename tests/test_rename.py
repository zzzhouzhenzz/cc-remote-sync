from cc_remote_sync.sync import decide_rename


def test_in_sync_no_action():
    assert decide_rename("same", "same", "same", 1, 1) == ("none", "same")


def test_linux_renamed_pushes_to_mac():
    # linux differs from baseline, mac still matches baseline
    assert decide_rename("new-lx", "old", "old", 5, 1) == ("mac", "new-lx")


def test_mac_renamed_pushes_to_linux():
    assert decide_rename("old", "new-mac", "old", 1, 5) == ("linux", "new-mac")


def test_both_changed_linux_newer_wins():
    assert decide_rename("LX", "MAC", "old", 9, 2) == ("mac", "LX")


def test_both_changed_mac_newer_wins():
    assert decide_rename("LX", "MAC", "old", 2, 9) == ("linux", "MAC")


def test_tie_favors_mac_title():
    # equal activity -> Mac's title wins (target 'linux' = push mac title to linux)
    assert decide_rename("LX", "MAC", "old", 5, 5) == ("linux", "MAC")


def test_no_baseline_equal_titles_is_noop():
    assert decide_rename("t", "t", "", 0, 0) == ("none", "t")


def test_handles_none_titles():
    assert decide_rename(None, None, None, 0, 0) == ("none", "")
