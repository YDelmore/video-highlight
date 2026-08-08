"""Tests for the XML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_highlight.exceptions import DanmakuParseError
from video_highlight.parser import Danmaku, parse_xml


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
