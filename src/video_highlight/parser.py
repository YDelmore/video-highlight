"""Parse Huya-style danmaku XML into structured Danmaku records."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from video_highlight.exceptions import DanmakuParseError


@dataclass(frozen=True)
class Danmaku:
    """A single bullet comment.

    `uid` is stored as a string to avoid 64-bit integer overflow on very
    long-running streams and to make hashable keys cheap.
    """

    uid: str
    ts_ms: int
    text: str


def parse_xml(
    source: str | Path | bytes,
    *,
    name: str | None = None,
) -> list[Danmaku]:
    """Parse a danmaku XML from a file path or raw bytes into Danmaku records.

    ``bytes`` input is for uploaded files (Streamlit file_uploader); ``name``
    is shown in error messages when the content came from bytes rather than a
    path. Skips <d> nodes that lack `uid` or `timestamp` attributes (logging
    via caller observability later if needed). Raises DanmakuParseError if the
    input cannot be parsed at all.
    """
    if isinstance(source, bytes):
        display = name or "<uploaded>"
        try:
            tree = ET.parse(BytesIO(source))
        except ET.ParseError as exc:
            raise DanmakuParseError(str(display), str(exc)) from exc
        return _extract_records(tree, str(display))

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"danmaku file not found: {path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise DanmakuParseError(str(path), str(exc)) from exc
    return _extract_records(tree, str(path))


def _extract_records(tree: ET.ElementTree, display: str) -> list[Danmaku]:
    """Walk the parsed tree for <d> nodes (shared by path and bytes input)."""
    records: list[Danmaku] = []
    skipped = 0
    for node in tree.iter("d"):
        uid_raw = node.get("uid")
        ts_raw = node.get("timestamp")
        if uid_raw is None or ts_raw is None:
            skipped += 1
            continue
        try:
            ts_ms = int(ts_raw)
        except ValueError:
            skipped += 1
            continue
        # ElementTree may give None if the node has no text body
        text = node.text or ""
        records.append(Danmaku(uid=uid_raw, ts_ms=ts_ms, text=text))

    if not records and skipped > 0:
        # All nodes were malformed; treat as parse failure
        raise DanmakuParseError(display, f"all {skipped} <d> nodes were malformed")

    return records
