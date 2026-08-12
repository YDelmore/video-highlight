"""Tests for the XML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_highlight.exceptions import DanmakuParseError
from video_highlight.parser import Danmaku, parse_metadata, parse_xml


def test_parse_xml_returns_dataclass_list(sample_xml_path: Path):
    """Parses a 5-bullet fixture into 5 Danmaku records."""
    result = parse_xml(sample_xml_path)
    assert len(result) == 5
    assert all(isinstance(d, Danmaku) for d in result)


def test_parse_xml_fields(sample_xml_path: Path):
    """First record has expected uid, ts_ms, and text."""
    result = parse_xml(sample_xml_path)
    first = result[0]
    assert first.uid == "uid_a"
    assert first.ts_ms == 1000000
    assert first.text == "first"


def test_parse_xml_skips_malformed_nodes(tmp_path: Path):
    """A <d> missing the timestamp attribute is skipped, not crashed on."""
    malformed = tmp_path / "broken.xml"
    malformed.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<i>"
        '<d user="x" uid="uid_x">ok</d>'
        '<d user="y" uid="uid_y" timestamp="2000000">ok_y</d>'
        "</i>"
    )
    result = parse_xml(malformed)
    assert len(result) == 1
    assert result[0].uid == "uid_y"
    assert result[0].ts_ms == 2000000


def test_parse_xml_raises_on_invalid_xml(tmp_path: Path):
    bad = tmp_path / "not-xml.txt"
    bad.write_text("this is not xml at all <><><>")
    with pytest.raises(DanmakuParseError):
        parse_xml(bad)


def test_parse_xml_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_xml(tmp_path / "no-such.xml")


# ---------------------------------------------------------------------------
# Uploaded bytes (Streamlit file_uploader)
# ---------------------------------------------------------------------------

def test_parse_xml_bytes_matches_file_path(sample_xml_path: Path):
    """Raw bytes give the same records as the on-disk path."""
    content = sample_xml_path.read_bytes()
    by_bytes = parse_xml(content, name=sample_xml_path.name)
    by_path = parse_xml(sample_xml_path)
    assert by_bytes == by_path


def test_parse_xml_bytes_raises_on_invalid_xml():
    with pytest.raises(DanmakuParseError) as excinfo:
        parse_xml(b"this is not xml at all <><><>", name="broken.xml")
    assert "broken.xml" in str(excinfo.value)


# ---------------------------------------------------------------------------
# parse_metadata
# ---------------------------------------------------------------------------

def test_parse_metadata_extracts_keys(sample_xml_path: Path):
    metadata = parse_metadata(sample_xml_path)
    assert metadata["platform"] == "TestPlatform"
    assert metadata["live_start_time"] == "1000000"
    assert metadata["user_name"] == "test_room"
    assert metadata["room_id"] == "1"


def test_parse_metadata_from_bytes(sample_xml_path: Path):
    by_bytes = parse_metadata(sample_xml_path.read_bytes(), name=sample_xml_path.name)
    by_path = parse_metadata(sample_xml_path)
    assert by_bytes == by_path


def test_parse_metadata_empty_when_no_metadata_block(tmp_path: Path):
    no_meta = tmp_path / "no-meta.xml"
    no_meta.write_text("<i><d user='u' uid='1' timestamp='1'>hi</d></i>")
    assert parse_metadata(no_meta) == {}


def test_parse_metadata_survives_malformed_body(tmp_path: Path):
    """Metadata at the head is extracted even when the body is unparseable."""
    bad = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<platform>HuYa</platform><user_name>s</user_name><room_id>1</room_id>"
        "<live_start_time>1786000000000</live_start_time></metadata>"
        '<d p="0" user="\x01bad" uid="1" timestamp="1786000001000">hi</d></i>'
    )
    path = tmp_path / "bad.xml"
    path.write_text(bad)
    metadata = parse_metadata(path)
    assert metadata["live_start_time"] == "1786000000000"


# ---------------------------------------------------------------------------
# Tolerant parse_xml (control characters / truncation)
# ---------------------------------------------------------------------------

def test_parse_xml_recovers_control_char_and_logs_repair(tmp_path: Path):
    bad = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<platform>HuYa</platform><user_name>s</user_name><room_id>1</room_id>"
        "<live_start_time>1786000000000</live_start_time></metadata>"
        '<d p="0" user="\x01bad" uid="1" timestamp="1786000001000">hi</d></i>'
    )
    path = tmp_path / "bad.xml"
    path.write_text(bad)

    repair_log: list[tuple[str, str]] = []
    records = parse_xml(path, repair_log=repair_log)

    assert len(records) == 1
    assert records[0].text == "hi"
    assert len(repair_log) == 1
    assert repair_log[0][0] == str(path)


def test_parse_xml_recovers_truncated_document(tmp_path: Path):
    truncated = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<platform>HuYa</platform><user_name>s</user_name><room_id>1</room_id>"
        "<live_start_time>1786000000000</live_start_time></metadata>"
        '<d p="0" user="u" uid="1" timestamp="1786000001000">hi</d>'
        # missing </i>
    )
    path = tmp_path / "cut.xml"
    path.write_text(truncated)

    repair_log: list[tuple[str, str]] = []
    records = parse_xml(path, repair_log=repair_log)

    assert len(records) == 1
    assert repair_log[0][1] == "文件截断，已自动补齐结束标签"


def test_parse_xml_repair_log_empty_on_clean_file(sample_xml_path: Path):
    repair_log: list[tuple[str, str]] = []
    parse_xml(sample_xml_path, repair_log=repair_log)
    assert repair_log == []


def test_parse_xml_unrecoverable_raises_and_logs_nothing(tmp_path: Path):
    unreadable = (
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        "<platform>HuYa</platform><user_name>s</user_name><room_id>1</room_id>"
        "<live_start_time>1786000000000</live_start_time></metadata>"
        '<d p="0" user="u" uid="1" timestamp="1786000001000">a < b</d></i>'
    )
    path = tmp_path / "junk.xml"
    path.write_text(unreadable)

    repair_log: list[tuple[str, str]] = []
    with pytest.raises(DanmakuParseError):
        parse_xml(path, repair_log=repair_log)
    assert repair_log == []
