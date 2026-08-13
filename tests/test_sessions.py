"""Tests for chunked-recording session discovery and aggregation.

Session grouping is based on **file times**, not ``live_start_time``: chunks
are sorted by creation time, and adjacent chunks belong to the same stream
when the previous chunk's modified time to the next chunk's creation time gap
is within an hour. Tests control the gap via ``os.utime`` (mtime); ctime is
the write time of freshly created files.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from video_highlight.sessions import (
    DanmakuSession,
    _format_session_label,
    _number_labels,
    discover_sessions,
    load_records,
)

LIVE = 1_786_000_000_000  # a wall-clock epoch (ms); unused for grouping now

HOUR = 3600


def _write(tmp: Path, name: str, content: str) -> Path:
    target = tmp / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _now_seconds() -> float:
    """Wall-clock seconds used to backdate a previous chunk's mtime."""
    return time.time()


def _backdate_mtime(path: Path, seconds_ago: float) -> None:
    mtime = _now_seconds() - seconds_ago
    os.utime(path, (mtime, mtime))


# ---------------------------------------------------------------------------
# Discovery / clustering by file times
# ---------------------------------------------------------------------------

def test_discover_groups_close_chunks_into_one_session(
    tmp_path: Path, chunk_xml
) -> None:
    _write(tmp_path, "p/s/chunk1.xml", chunk_xml(LIVE, nodes=[("a", LIVE + 1000, "x")]))
    time.sleep(0.02)  # guarantee chunk2 is created after chunk1
    chunk2 = _write(
        tmp_path, "p/s/chunk2.xml", chunk_xml(LIVE, nodes=[("b", LIVE + 2000, "y")])
    )

    sessions, unclassified = discover_sessions(tmp_path)

    assert unclassified == []
    assert len(sessions) == 1
    session = sessions[0]
    assert len(session.chunks) == 2
    assert session.chunks[-1] == chunk2  # creation-time order preserved
    assert session.user_name == "主播"
    assert session.platform == "HuYa"


def test_discover_half_hour_gap_stays_one_session(tmp_path: Path, chunk_xml) -> None:
    # A recording that "ended" 30 min before the next one started still merges.
    first = _write(tmp_path, "a.xml", chunk_xml(LIVE))
    time.sleep(0.02)
    _write(tmp_path, "b.xml", chunk_xml(LIVE))
    _backdate_mtime(first, seconds_ago=30 * 60)

    sessions, _ = discover_sessions(tmp_path)

    assert len(sessions) == 1
    assert len(sessions[0].chunks) == 2


def test_discover_splits_when_gap_over_an_hour(tmp_path: Path, chunk_xml) -> None:
    first = _write(tmp_path, "a.xml", chunk_xml(LIVE))
    time.sleep(0.02)
    _write(tmp_path, "b.xml", chunk_xml(LIVE))
    _backdate_mtime(first, seconds_ago=2 * HOUR)

    sessions, _ = discover_sessions(tmp_path)

    assert [len(s.chunks) for s in sessions] == [1, 1]


def test_discover_orders_chunks_by_creation_time(tmp_path: Path, chunk_xml) -> None:
    names = []
    for name in ("a.xml", "b.xml", "c.xml"):
        _write(tmp_path, name, chunk_xml(LIVE))
        time.sleep(0.02)
        names.append(name)

    sessions, _ = discover_sessions(tmp_path)

    assert len(sessions) == 1
    assert [p.name for p in sessions[0].chunks] == names


def test_discover_ignores_non_xml(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "chunk.xml", chunk_xml(LIVE))
    _write(tmp_path, "notes.txt", "not danmaku")

    sessions, _ = discover_sessions(tmp_path)

    assert len(sessions) == 1
    assert len(sessions[0].chunks) == 1


def test_discover_keeps_streamers_separate(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "p/主播A/a.xml", chunk_xml(LIVE, user="主播A"))
    time.sleep(0.02)
    _write(tmp_path, "p/主播B/b.xml", chunk_xml(LIVE, user="主播B"))

    sessions, _ = discover_sessions(tmp_path)

    # same platform + close in time, but different streamers -> own sessions
    assert {s.user_name for s in sessions} == {"主播A", "主播B"}


def test_discover_unclassified_without_platform_or_user(tmp_path: Path) -> None:
    no_meta = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<room_id>1</room_id></metadata></i>"
    )
    _write(tmp_path, "no-meta.xml", no_meta)

    sessions, unclassified = discover_sessions(tmp_path)

    assert sessions == []
    assert [p.name for p in unclassified] == ["no-meta.xml"]


# ---------------------------------------------------------------------------
# Labels: 年月日 + 序号（同主播按时间连续编号，跨天重置）
# ---------------------------------------------------------------------------

def test_discover_labels_sessions_chronologically(tmp_path: Path, chunk_xml) -> None:
    first = _write(tmp_path, "a.xml", chunk_xml(LIVE))
    time.sleep(0.02)
    _write(tmp_path, "b.xml", chunk_xml(LIVE))
    _backdate_mtime(first, seconds_ago=2 * HOUR)  # -> two sessions, same day

    sessions, _ = discover_sessions(tmp_path)

    today = f"{datetime.now():%Y-%m-%d}"
    assert [s.label for s in sessions] == [
        f"{today} 第1场 · 测试直播",
        f"{today} 第2场 · 测试直播",
    ]


def test_format_session_label_date() -> None:
    base = int(datetime(2024, 1, 2, 3, 4).timestamp() * 1000)
    assert _format_session_label(base, 3) == "2024-01-02 第3场"


def test_number_labels_resets_per_day() -> None:
    def ms(y: int, m: int, d: int, hh: int, mm: int) -> int:
        return int(datetime(y, m, d, hh, mm).timestamp() * 1000)

    # Two sessions on 01-02, then one on 01-03: the ordinal restarts at 1.
    starts = [ms(2024, 1, 2, 10, 0), ms(2024, 1, 2, 14, 0), ms(2024, 1, 3, 9, 0)]

    assert _number_labels(starts) == [
        "2024-01-02 第1场",
        "2024-01-02 第2场",
        "2024-01-03 第1场",
    ]


def test_discover_label_uses_first_chunk_title(tmp_path: Path, chunk_xml) -> None:
    _write(tmp_path, "a.xml", chunk_xml(LIVE, title="开场标题"))
    time.sleep(0.02)
    _write(tmp_path, "b.xml", chunk_xml(LIVE, title="开场标题"))  # same title

    sessions, _ = discover_sessions(tmp_path)

    assert len(sessions) == 1  # adjacent chunks, same title, same session
    assert sessions[0].title == "开场标题"
    assert sessions[0].label == f"{datetime.now():%Y-%m-%d} 第1场 · 开场标题"


def test_discover_splits_when_title_changes(tmp_path: Path, chunk_xml) -> None:
    # same file-time gap as before, but the room title differs -> new stream
    _write(tmp_path, "a.xml", chunk_xml(LIVE, title="标题一"))
    time.sleep(0.02)
    _write(tmp_path, "b.xml", chunk_xml(LIVE, title="标题二"))

    sessions, _ = discover_sessions(tmp_path)

    assert [s.title for s in sessions] == ["标题一", "标题二"]
    assert [len(s.chunks) for s in sessions] == [1, 1]
    today = f"{datetime.now():%Y-%m-%d}"
    assert [s.label for s in sessions] == [
        f"{today} 第1场 · 标题一",
        f"{today} 第2场 · 标题二",
    ]


def test_discover_label_omits_title_when_missing(tmp_path: Path) -> None:
    no_title = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        f"<platform>HuYa</platform><user_name>主播</user_name><room_id>42</room_id>"
        f"<live_start_time>{LIVE}</live_start_time></metadata></i>"
    )
    _write(tmp_path, "a.xml", no_title)

    sessions, _ = discover_sessions(tmp_path)

    assert sessions[0].title == ""
    assert sessions[0].label == f"{datetime.now():%Y-%m-%d} 第1场"


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
    time.sleep(0.02)
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
        f"<room_title>测试直播</room_title>"
        f"<live_start_time>{LIVE}</live_start_time></metadata>"
        f'<d p="0,1,25,16777215,{LIVE + 1000},0,1,0,0" user="\x01bad"'
        f' uid="1" timestamp="{LIVE + 1000}">hi</d></i>'
    )
    _write(tmp_path, "bad.xml", bad)
    time.sleep(0.02)
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
        f"<room_title>测试直播</room_title>"
        f"<live_start_time>{LIVE}</live_start_time></metadata>"
        f'<d p="0" user="u" uid="1" timestamp="{LIVE + 1000}">a < b</d></i>'
    )
    _write(tmp_path, "junk.xml", unreadable)
    time.sleep(0.02)
    _write(
        tmp_path, "good.xml", chunk_xml(LIVE, nodes=[("uid_b", LIVE + 2000, "ok")])
    )

    sessions, _ = discover_sessions(tmp_path)
    records, notes = load_records(sessions[0])

    assert len(records) == 1  # good chunk unaffected
    assert len(notes.skipped) == 1
    assert "junk.xml" in notes.skipped[0][0]
