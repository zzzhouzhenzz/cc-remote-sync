from cc_remote_sync import schema


CLI_RECORDS = [
    {"type": "custom-title", "customTitle": "My Session", "sessionId": "s1"},
    {"type": "mode", "mode": "default", "sessionId": "s1"},
    {"type": "user", "cwd": "/home/zz/ml", "timestamp": "2026-05-01T10:00:00Z",
     "entrypoint": "cli", "message": {"content": "hello there"}},
    {"type": "assistant", "timestamp": "2026-05-01T10:00:05Z",
     "message": {"model": "claude-opus-4-8", "content": [{"type": "text", "text": "hi"}]}},
]

DESKTOP_RECORDS = [
    {"type": "queue-operation", "operation": "enqueue", "content": "do x", "sessionId": "s2"},
    {"type": "queue-operation", "operation": "dequeue", "sessionId": "s2"},
    {"type": "user", "cwd": "/home/zz/ml", "timestamp": "2026-05-02T09:00:00Z",
     "entrypoint": "claude-desktop", "message": {"content": "first prompt here"}},
    {"type": "assistant", "timestamp": "2026-05-02T09:01:00Z",
     "message": {"model": "claude-opus-4-7", "content": [{"type": "text", "text": "ok"}]}},
]


def test_detect_schema():
    assert schema.detect_schema(CLI_RECORDS) == "cli"
    assert schema.detect_schema(DESKTOP_RECORDS) == "desktop"
    assert schema.detect_schema([{"type": "user"}]) == "unknown"


def test_extract_meta_cli():
    m = schema.extract_meta(CLI_RECORDS)
    assert m.title == "My Session"
    assert m.model == "claude-opus-4-8"
    assert m.cwd == "/home/zz/ml"
    assert m.turns == 1
    assert m.last_activity_ms > 0


def test_extract_meta_title_fallback_from_first_prompt():
    m = schema.extract_meta(DESKTOP_RECORDS)
    # no custom-title -> falls back to first user prompt
    assert m.title == "first prompt here"
    assert m.model == "claude-opus-4-7"


def test_born_and_app_born():
    assert schema.extract_meta(CLI_RECORDS).born == "cli"
    assert schema.extract_meta(DESKTOP_RECORDS).born == "claude-desktop"
    assert not schema.is_app_born(schema.extract_meta(CLI_RECORDS))
    assert schema.is_app_born(schema.extract_meta(DESKTOP_RECORDS))


def test_born_is_first_entrypoint_not_the_set():
    # born in terminal, later opened in the app -> still CLI-born (first entrypoint wins)
    recs = [
        {"type": "user", "entrypoint": "cli", "timestamp": "2026-05-01T10:00:00Z",
         "message": {"content": "x"}},
        {"type": "user", "entrypoint": "claude-desktop", "timestamp": "2026-05-02T10:00:00Z",
         "message": {"content": "y"}},
    ]
    m = schema.extract_meta(recs)
    assert m.born == "cli"
    assert not schema.is_app_born(m)


def test_to_cli_records_strips_queue_ops_and_adds_title():
    out = schema.to_cli_records(DESKTOP_RECORDS, "Recovered Title")
    assert not any(r.get("type") == "queue-operation" for r in out)
    assert out[0]["type"] == "custom-title"
    assert out[0]["customTitle"] == "Recovered Title"
    # conversation records preserved
    assert sum(1 for r in out if r.get("type") == "user") == 1


def test_to_cli_records_keeps_existing_title():
    out = schema.to_cli_records(CLI_RECORDS, "ignored")
    titles = [r for r in out if r.get("type") == "custom-title"]
    assert len(titles) == 1  # didn't double up


def test_roundtrip_write_read(tmp_path):
    p = tmp_path / "x.jsonl"
    schema.write_jsonl(p, CLI_RECORDS)
    recs, errs = schema.read_jsonl(p)
    assert errs == []
    assert len(recs) == len(CLI_RECORDS)


def test_read_jsonl_collects_errors(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"type":"user"}\nNOT JSON\n{"type":"assistant"}\n')
    recs, errs = schema.read_jsonl(p)
    assert len(recs) == 2
    assert len(errs) == 1 and "bad.jsonl:2" in errs[0]


def test_content_hash_stable_and_differs(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    schema.write_jsonl(a, CLI_RECORDS)
    schema.write_jsonl(b, CLI_RECORDS)
    assert schema.content_hash(a) == schema.content_hash(b)
    schema.write_jsonl(b, DESKTOP_RECORDS)
    assert schema.content_hash(a) != schema.content_hash(b)
    assert schema.content_hash(tmp_path / "missing.jsonl") == ""
