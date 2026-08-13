"""Chunked-recording session discovery and aggregation.

Recorder software splits one live stream into many XML chunks (one per
file, e.g. under ``E:/huya/<platform>/<streamer>/``). ``live_start_time`` in
each chunk's ``<metadata>`` is unreliable — a streamer switching devices or
restarting mid-stream changes it — so sessions are detected from **file
times** instead: chunks are sorted by file creation time, and two adjacent
chunks belong to the same stream when the gap between the previous chunk's
last-modified time and the next chunk's creation time is within an hour
**and** the two chunks carry the same ``room_title`` (a different title means
a different stream, e.g. the streamer retitled the room).

Aggregation is **not** file merging: each chunk's ``<d timestamp=...>`` is a
wall-clock millisecond, and callers recover the continuous in-stream timeline
by passing ``live_start_ms=session origin`` to ``loader.to_dataframe`` (which
is exactly what ``app.py`` does). Gaps between chunks are recorder downtime
and need no handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from video_highlight.exceptions import DanmakuParseError
from video_highlight.parser import Danmaku, parse_metadata, parse_xml

# (platform, user_name, start_ctime_ms)
SessionKey = tuple[str, str, int]

_GAP_MS = 60 * 60 * 1000  # adjacent chunks closer than this are one stream


def _ctime_ms(path: Path) -> int:
    """File creation time in ms (on Windows ``st_ctime`` is the creation time)."""
    return int(path.stat().st_ctime * 1000)


def _mtime_ms(path: Path) -> int:
    return int(path.stat().st_mtime * 1000)


@dataclass(frozen=True)
class DanmakuSession:
    """One logical live stream made of one or more recording chunks.

    Frozen + hashable so the object can be returned/cached by
    ``@st.cache_data`` in the Streamlit app.
    """

    key: SessionKey
    platform: str
    user_name: str
    chunks: tuple[Path, ...]
    start_ctime_ms: int
    end_mtime_ms: int
    label: str
    title: str = ""


@dataclass
class SessionNotes:
    """Chunks that needed repair or could not be read at all."""

    recovered: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return bool(self.recovered or self.skipped)


def _date_of(start_ctime_ms: int) -> str:
    return datetime.fromtimestamp(start_ctime_ms / 1000).strftime("%Y-%m-%d")


def _format_session_label(start_ctime_ms: int, ordinal: int) -> str:
    """``YYYY-MM-DD 第N场``: the stream's start date + that day's ordinal."""
    return f"{_date_of(start_ctime_ms)} 第{ordinal}场"


def _number_labels(start_times_ms: list[int]) -> list[str]:
    """Number a streamer's chronologically-sorted session start times.

    The ordinal is continuous within a day and **resets at midnight**: the
    first session of each ``YYYY-MM-DD`` is ``第1场`` again.
    """
    labels: list[str] = []
    ordinal = 0
    last_date = None
    for start_ms in start_times_ms:
        date = _date_of(start_ms)
        if date != last_date:
            ordinal = 0
            last_date = date
        ordinal += 1
        labels.append(_format_session_label(start_ms, ordinal))
    return labels


def _cluster_by_time(
    entries: list[tuple[Path, str]],
) -> list[tuple[list[Path], str]]:
    """Split already-ctime-sorted ``(chunk, title)`` pairs into sessions.

    Adjacent chunks stay in the same session only when the gap from the
    previous chunk's *modified* time (recording end) to the next chunk's
    *creation* time (recording start) is within an hour **and** the two
    chunks carry the same ``room_title``. Returns ``(chunk paths, title)``
    per session; the title is the first chunk's.
    """
    clusters: list[tuple[list[Path], str]] = []
    current = [entries[0][0]]
    title = entries[0][1]
    for (prev_path, prev_title), (nxt_path, nxt_title) in zip(
        entries, entries[1:]
    ):
        gap = _ctime_ms(nxt_path) - _mtime_ms(prev_path)
        if gap <= _GAP_MS and prev_title == nxt_title:
            current.append(nxt_path)
        else:
            clusters.append((current, title))
            current = [nxt_path]
            title = nxt_title
    clusters.append((current, title))
    return clusters


def discover_sessions(root: str | Path) -> tuple[list[DanmakuSession], list[Path]]:
    """Group all ``*.xml`` under ``root`` into live sessions by file times.

    Returns ``(sessions, unclassified)``. Within each ``(platform, user_name)``
    the chunks are ordered by creation time; adjacent chunks merge into one
    session only when the previous modified-to-next-created gap is within an
    hour **and** the two chunks share the same ``room_title`` (a title change
    starts a new stream). Sessions are numbered per day (the ordinal resets at
    midnight) and labelled ``YYYY-MM-DD 第N场 · 直播标题`` (title from the
    first chunk's ``room_title``; dropped when absent). ``unclassified`` are
    files whose metadata carried no usable ``platform``/``user_name``.
    """
    root_path = Path(root)
    grouped: dict[tuple[str, str], list[tuple[Path, str]]] = {}
    unclassified: list[Path] = []
    for xml in sorted(root_path.rglob("*.xml"), key=_ctime_ms):
        metadata = parse_metadata(xml)
        platform = metadata.get("platform", "")
        user_name = metadata.get("user_name", "")
        if not platform or not user_name:
            unclassified.append(xml)
            continue
        title = metadata.get("room_title", "").strip()
        grouped.setdefault((platform, user_name), []).append((xml, title))

    sessions: list[DanmakuSession] = []
    for (platform, user_name), entries in grouped.items():
        clusters = _cluster_by_time(entries)
        starts = [_ctime_ms(chunks[0]) for chunks, _ in clusters]
        base_labels = _number_labels(starts)
        for (chunks, title), start_ms, base in zip(
            clusters, starts, base_labels
        ):
            chunks_t = tuple(chunks)
            label = base if not title else f"{base} · {title}"
            sessions.append(
                DanmakuSession(
                    key=(platform, user_name, start_ms),
                    platform=platform,
                    user_name=user_name,
                    chunks=chunks_t,
                    start_ctime_ms=start_ms,
                    end_mtime_ms=_mtime_ms(chunks_t[-1]),
                    label=label,
                    title=title,
                )
            )
    sessions.sort(key=lambda s: (s.platform, s.user_name, s.start_ctime_ms))
    return sessions, unclassified


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
