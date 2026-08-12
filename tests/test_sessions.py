"""Tests for chunked-recording session discovery and aggregation."""

from __future__ import annotations

from pathlib import Path

from video_highlight.parser import Danmaku
from video_highlight.sessions import DanmakuSession, discover_sessions, load_records

LIVE = 1_786_000_000_000  # a shared wall-clock live start (ms)


def _write(tmp: Path, name: str, content: str) -> Path:
    target = tmp / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Discovery / grouping
# ---------------------------------------------------------------------------

def test_discover_groups_same_live_into_one_session(
    tmp_path: Path, chunk_xml
) -> None:
    _write(tmp_path, "p/s/chunk1.xml", chunk_xml(LIVE, nodes=[("a", LIVE + 1000, "x")]))
    _write(tmp_path, "p/s/chunk2.xml", chunk_xml(LIVE, nodes=[("b", LIVE + 2000, "y")]))

    sessions, unclassified = discover_sessions(tmp_path)

    assert unclassified == []
    assert len(sessions) == 1
    session = sessions[0]
    assert session.live_start_ms == LIVE
    assert len(session.chunks) == 2


def test_discover_splits_different_live_sorted(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "a.xml", chunk_xml(2000))
    _write(tmp_path, "b.xml", chunk_xml(1000))
    _write(tmp_path, "c.xml", chunk_xml(3000))

    sessions, _ = discover_sessions(tmp_path)

    assert [s.live_start_ms for s in sessions] == [1000, 2000, 3000]


def test_discover_ignores_non_xml(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "chunk.xml", chunk_xml(LIVE))
    _write(tmp_path, "notes.txt", "not danmaku")

    sessions, _ = discover_sessions(tmp_path)

    assert len(sessions) == 1
    assert len(sessions[0].chunks) == 1


def test_discover_returns_unclassified_without_live_time(tmp_path: Path) -> None:
    missing_live = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<platform>HuYa</platform><user_name>s</user_name>"
        "<room_id>1</room_id></metadata></i>"
    )
    _write(tmp_path, "no-live.xml", missing_live)

    sessions, unclassified = discover_sessions(tmp_path)

    assert sessions == []
    assert [p.name for p in unclassified] == ["no-live.xml"]


def test_discover_title_falls_back_to_user(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "chunk.xml", chunk_xml(LIVE, title=""))

    sessions, _ = discover_sessions(tmp_path)

    assert sessions[0].title == "主播"


# ---------------------------------------------------------------------------
# Aggregation (load_records)
# ---------------------------------------------------------------------------

def test_load_records_concatenates_sorted_and_dedups(
    tmp_path: Path, chunk_xml
) -> None:
    # chunk A: a, b ; chunk B: b (exact duplicate), c -> 3 unique records
    _write(
        tmp_path,
        "a.xml",
        chunk_xml(
            LIVE, nodes=[("uid_a", LIVE + 1000, "aaa"), ("uid_b", LIVE + 2000, "bbb")]
        ),
    )
    _write(
        tmp_path,
        "b.xml",
        chunk_xml(
            LIVE, nodes=[("uid_b", LIVE + 2000, "bbb"), ("uid_c", LIVE + 3000, "ccc")]
        ),
    )

    sessions, _ = discover_sessions(tmp_path)
    records, notes = load_records(sessions[0])

    assert [r.ts_ms for r in records] == [LIVE + 1000, LIVE + 2000, LIVE + 3000]
    assert not notes.has_problems


def test_load_records_recovers_control_char_chunk(tmp_path: Path, chunk_xml) -> None:
    bad = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        f"<platform>HuYa</platform><user_name>主播</user_name><room_id>42</room_id>"
        f"<live_start_time>{LIVE}</live_start_time></metadata>"
        f'<d p="0,1,25,16777215,{LIVE + 1000},0,1,0,0" user="\x01bad"'
        f' uid="1" timestamp="{LIVE + 1000}">hi</d></i>'
    )
    _write(tmp_path, "bad.xml", bad)
    _write(
        tmp_path, "good.xml", chunk_xml(LIVE, nodes=[("uid_b", LIVE + 2000, "ok")])
    )

    sessions, _ = discover_sessions(tmp_path)
    records, notes = load_records(sessions[0])

    assert len(records) == 2  # control-char chunk's danmaku was salvaged
    assert any(r.text == "hi" for r in records)
    assert len(notes.recovered) == 1
    assert "bad.xml" in notes.recovered[0][0]


def test_load_records_recovers_truncated_chunk(tmp_path: Path, chunk_xml) -> None:
    full = chunk_xml(LIVE, nodes=[("uid_a", LIVE + 1000, "hi")])
    _write(tmp_path, "cut.xml", full[: -len("</i>")])  # drop the root close

    sessions, _ = discover_sessions(tmp_path)
    records, notes = load_records(sessions[0])

    assert len(records) == 1
    assert notes.recovered[0][1] == "文件截断，已自动补齐结束标签"


def test_load_records_skips_unparseable_chunk(tmp_path: Path, chunk_xml) -> None:
    # Has valid metadata (so it groups) but an unescaped `<` in danmaku text
    # that survives neither control-char scrubbing nor root-close repair.
    unreadable = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        f"<platform>HuYa</platform><user_name>主播</user_name><room_id>42</room_id>"
        f"<live_start_time>{LIVE}</live_start_time></metadata>"
        f'<d p="0" user="u" uid="1" timestamp="{LIVE + 1000}">a < b</d></i>'
    )
    _write(tmp_path, "junk.xml", unreadable)
    _write(
        tmp_path, "good.xml", chunk_xml(LIVE, nodes=[("uid_b", LIVE + 2000, "ok")])
    )

    sessions, _ = discover_sessions(tmp_path)
    records, notes = load_records(sessions[0])

    assert len(records) == 1  # good chunk unaffected
    assert len(notes.skipped) == 1
    assert "junk.xml" in notes.skipped[0][0]
