from pathlib import Path

from cc_remote_sync import paths


def test_cwd_to_slug_basic():
    assert paths.cwd_to_slug("/home/zz/ml-workspace") == "-home-zz-ml-workspace"
    assert paths.cwd_to_slug("/Users/zhouzhen24/Documents/coding/ml") == \
        "-Users-zhouzhen24-Documents-coding-ml"


def test_cwd_to_slug_collapses_specials():
    # dots and other non-alnum collapse to a single dash
    assert paths.cwd_to_slug("/home/zz/.config/app") == "-home-zz-config-app"


def test_remote_project_dir():
    assert paths.remote_project_dir("/home/zz/ml") == ".claude/projects/-home-zz-ml"


def test_mac_transcript_path():
    p = paths.mac_transcript_path("abc123")
    assert p.name == "abc123.jsonl"
    assert p.parent.name == "ssh-abc123"


def test_index_entry_path():
    p = paths.index_entry_path("ORG", "ACCT", "uuid1")
    assert p.name == "local_uuid1.json"
    assert p.parent.name == "ACCT"
