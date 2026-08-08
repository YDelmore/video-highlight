"""Parse Huya-style danmaku XML into structured Danmaku records."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
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


def parse_xml(path: str | Path) -> list[Danmaku]:
    """Parse a danmaku XML file into a list of Danmaku records.

    Skips <d> nodes that lack `uid` or `timestamp` attributes (logging via
    caller observability later if needed). Raises DanmakuParseError if the
    file cannot be parsed at all.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"danmaku file not found: {path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise DanmakuParseError(str(path), str(exc)) from exc

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
        raise DanmakuParseError(
            str(path), f"all {skipped} <d> nodes were malformed"
        )

    return records
