"""Parse Huya-style danmaku XML into structured Danmaku records."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from video_highlight.exceptions import DanmakuParseError

# XML forbids these control characters even inside attribute values, but
# real-world recorder files occasionally contain a raw one (e.g. \x01 in a
# username). Stripping them is lossless: none are displayable.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Enough of the file to always cover the <metadata> block, which sits near the
# top of every recorder file.
_METADATA_HEAD_BYTES = 64 * 1024


@dataclass(frozen=True)
class Danmaku:
    """A single bullet comment.

    `uid` is stored as a string to avoid 64-bit integer overflow on very
    long-running streams and to make hashable keys cheap.
    """

    uid: str
    ts_ms: int
    text: str


def _recover_root(raw: bytes) -> tuple[ET.Element | None, str | None]:
    """Tolerant parse of recorder XML bytes.

    Returns ``(root, None)`` when the file parses cleanly, or ``(root, reason)``
    when it had to be repaired first, or ``(None, None)`` when it cannot be
    parsed at all. Repairs, in order:

    1. strip XML-forbidden control characters (invalid-token failures);
    2. close a truncated document by appending ``</root>`` (and, if needed,
       a trailing ``</d>``) — the root tag name comes from the first element.
    """
    text = raw.decode("utf-8", errors="replace")
    try:
        return ET.fromstring(text), None
    except ET.ParseError:
        pass

    scrubbed = _CTRL_RE.sub("", text)
    try:
        return ET.fromstring(scrubbed), "含控制字符损坏，已清除后解析"
    except ET.ParseError:
        pass

    m = re.search(r"<(?!\?)([A-Za-z_][\w.-]*)[\s>]", scrubbed)
    if m is not None:
        for suffix in (f"</{m.group(1)}>", f"</d></{m.group(1)}>"):
            try:
                return ET.fromstring(scrubbed + suffix), "文件截断，已自动补齐结束标签"
            except ET.ParseError:
                continue
    return None, None


def parse_metadata(
    source: str | Path | bytes,
    *,
    name: str | None = None,
) -> dict[str, str]:
    """Extract the ``<metadata>`` block as a dict, robust to body corruption.

    Metadata sits at the head of every recorder file, so only the first
    ``_METADATA_HEAD_BYTES`` are read. Control characters are stripped before
    extraction so a malformed body never prevents session grouping. Returns
    ``{}`` when no usable metadata block is found. Keys observed in the wild:
    ``platform``, ``user_name``, ``room_id``, ``room_title``,
    ``live_start_time``, ``video_start_time``.
    """
    if isinstance(source, bytes):
        raw = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"danmaku file not found: {path}")
        with path.open("rb") as fh:
            raw = fh.read(_METADATA_HEAD_BYTES)

    text = _CTRL_RE.sub("", raw.decode("utf-8", errors="replace"))
    m = re.search(r"<metadata>.*?</metadata>", text, re.DOTALL)
    if m is None:
        return {}
    try:
        meta = ET.fromstring(m.group(0))
    except ET.ParseError:
        return {}
    return {ch.tag: ch.text for ch in meta}


def parse_xml(
    source: str | Path | bytes,
    *,
    name: str | None = None,
    repair_log: list[tuple[str, str]] | None = None,
) -> list[Danmaku]:
    """Parse a danmaku XML from a file path or raw bytes into Danmaku records.

    ``bytes`` input is for uploaded files (Streamlit file_uploader); ``name``
    is shown in error messages when the content came from bytes rather than a
    path. Malformed-but-recoverable files (control characters, truncation) are
    repaired transparently; ``repair_log`` collects ``(display, reason)`` for
    each repaired file so callers can surface it. Files that cannot be parsed
    at all raise :class:`DanmakuParseError`. Skips <d> nodes that lack `uid` or
    `timestamp` attributes.
    """
    if isinstance(source, bytes):
        raw, display = source, name or "<uploaded>"
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"danmaku file not found: {path}")
        raw, display = path.read_bytes(), str(path)

    root, reason = _recover_root(raw)
    if root is None:
        raise DanmakuParseError(display, "无法解析的弹幕 XML")
    if reason is not None and repair_log is not None:
        repair_log.append((display, reason))
    return _extract_records(root, display)


def _extract_records(root: ET.Element, display: str) -> list[Danmaku]:
    """Walk the parsed tree for <d> nodes (shared by path and bytes input)."""
    records: list[Danmaku] = []
    skipped = 0
    for node in root.iter("d"):
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
