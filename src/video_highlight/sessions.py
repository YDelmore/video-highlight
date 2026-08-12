"""Chunked-recording session discovery and aggregation.

Recorder software splits one live stream into many XML chunks (one per
file, e.g. under ``E:/huya/<platform>/<streamer>/``). All chunks of the same
stream share the same ``live_start_time`` in their ``<metadata>``, so a
session is the group of chunks with a common
``(platform, user_name, room_id, live_start_time)`` key.

Aggregation is **not** file merging: each chunk's ``<d timestamp=...>`` is a
wall-clock millisecond, and callers recover the continuous in-stream timeline
by passing ``live_start_ms=session.live_start_ms`` to ``loader.to_dataframe``
(which is exactly what ``app.py`` does). Gaps between chunks are recorder
downtime and need no handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from video_highlight.exceptions import DanmakuParseError
from video_highlight.parser import Danmaku, parse_metadata, parse_xml

# (platform, user_name, room_id, live_start_ms)
SessionKey = tuple[str, str, str, int]


@dataclass(frozen=True)
class DanmakuSession:
    """One logical live stream made of one or more recording chunks.

    Frozen + hashable so the object can be returned/cached by
    ``@st.cache_data`` in the Streamlit app.
    """

    key: SessionKey
    title: str
    chunks: tuple[Path, ...]

    @property
    def platform(self) -> str:
        return self.key[0]

    @property
    def user_name(self) -> str:
        return self.key[1]

    @property
    def room_id(self) -> str:
        return self.key[2]

    @property
    def live_start_ms(self) -> int:
        return self.key[3]


@dataclass
class SessionNotes:
    """Chunks that needed repair or could not be read at all."""

    recovered: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return bool(self.recovered or self.skipped)


def _live_start_ms(metadata: dict[str, str]) -> int | None:
    """The session key component, or None when the metadata lacks it."""
    raw = metadata.get("live_start_time")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def discover_sessions(root: str | Path) -> tuple[list[DanmakuSession], list[Path]]:
    """Group all ``*.xml`` under ``root`` into live sessions.

    Returns ``(sessions, unclassified)`` with sessions ordered by
    ``live_start_ms`` ascending and ``unclassified`` the files whose metadata
    carried no usable ``live_start_time`` (so they cannot be grouped).
    """
    root_path = Path(root)
    groups: dict[SessionKey, list[tuple[Path, dict[str, str]]]] = {}
    unclassified: list[Path] = []
    for xml in sorted(root_path.rglob("*.xml")):
        metadata = parse_metadata(xml)
        live = _live_start_ms(metadata)
        if live is None:
            unclassified.append(xml)
            continue
        key = (
            metadata.get("platform", ""),
            metadata.get("user_name", ""),
            metadata.get("room_id", ""),
            live,
        )
        groups.setdefault(key, []).append((xml, metadata))

    sessions = [
        DanmakuSession(
            key=key,
            title=_title_of(metadata, key),
            chunks=tuple(sorted(xml for xml, _ in entries)),
        )
        for key, entries in groups.items()
        for _, metadata in [entries[0]]
    ]
    sessions.sort(key=lambda s: s.live_start_ms)
    return sessions, unclassified


def _title_of(metadata: dict[str, str], key: SessionKey) -> str:
    return metadata.get("room_title") or key[1] or "未命名直播"


def load_records(session: DanmakuSession) -> tuple[list[Danmaku], SessionNotes]:
    """Aggregate every chunk's danmaku into one ordered record list.

    Records keep their wall-clock ``ts_ms``; timeline conversion to in-stream
    seconds is left to ``loader.to_dataframe(live_start_ms=...)``. Duplicate
    ``(ts_ms, uid, text)`` across chunk boundaries are dropped (rare, but a
    safe guard). Chunks that cannot be parsed are recorded in
    ``notes.skipped`` and do not abort the session.
    """
    notes = SessionNotes()
    records: list[Danmaku] = []
    seen: set[tuple[int, str, str]] = set()
    for chunk in session.chunks:
        repair_log: list[tuple[str, str]] = []
        try:
            chunk_records = parse_xml(chunk, repair_log=repair_log)
        except (DanmakuParseError, OSError) as exc:
            notes.skipped.append((chunk.name, str(exc)))
            continue
        notes.recovered.extend(repair_log)
        for record in chunk_records:
            key = (record.ts_ms, record.uid, record.text)
            if key not in seen:
                seen.add(key)
                records.append(record)
    records.sort(key=lambda r: r.ts_ms)
    return records, notes
