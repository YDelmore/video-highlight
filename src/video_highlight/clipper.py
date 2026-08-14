"""Slice video recordings into highlight clips.

Pipeline: detected candidates (danmaku-relative seconds) -> wall-clock
intervals -> per-video-chunk local offsets -> ffmpeg commands -> validation
-> manifest.

Time model
----------
- Danmaku timeline: ``t=0`` sits at ``anchor_ms`` (default: the first
  bullet's ``ts_ms``, matching the analysis platform). A candidate
  ``[t_start, t_end]`` therefore spans absolute
  ``[anchor_ms + t_start*1000, anchor_ms + t_end*1000)``.
- Video chunks: the recorder writes one file per chunk with the wall-clock
  start encoded in the file-name prefix
  (``2026-08-07-22-24-43-052-<title>.flv`` = yyyy-MM-dd-HH-mm-ss-fff). The
  sibling video of an XML chunk lives in the same directory and shares the
  same prefix.
- A highlight may span several chunks (recorder downtime leaves holes): each
  intersecting chunk yields one ``(file, local_start, local_end)`` segment,
  and holes are reported instead of cut across.

The only free parameter is the offset between the video's start and the
first bullet (the anchor). By default they are assumed aligned
(``anchor = first bullet ts``); pass ``--anchor-ms`` to calibrate when the
recorder starts earlier/later than the first bullet.

This module is pure (no streamlit/plotly); ffmpeg/ffprobe are external
executables resolved at call time.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from video_highlight.exceptions import ClipperError
from video_highlight.highlights import HighlightCandidate

VIDEO_EXTENSIONS: tuple[str, ...] = (".flv", ".mp4", ".ts", ".mkv", ".mov")

# Recorder chunk prefix: 2026-08-07-22-24-43-052-<title>
_CHUNK_PREFIX_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{3})"
)

MANIFEST_COLUMNS: tuple[str, ...] = (
    "clip_index",
    "grade",
    "shape",
    "level",
    "t_start",
    "t_end",
    "peak_t",
    "abs_start_ms",
    "abs_end_ms",
    "overlaps_previous",
    "segment_index",
    "n_segments",
    "source",
    "local_start_ms",
    "local_end_ms",
    "output",
    "status",
    "actual_duration_s",
    "has_video",
    "has_audio",
)


@dataclass(frozen=True)
class ChunkVideo:
    """One recording chunk plus its wall-clock time span."""

    path: Path
    start_ms: int  # wall-clock start (from the file-name prefix)
    end_ms: int | None  # start of the next contiguous chunk, when known


@dataclass(frozen=True)
class Segment:
    """One contiguous cut inside one video file."""

    video: Path
    local_start_ms: int  # offset from the video's start
    local_end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.local_end_ms - self.local_start_ms


@dataclass
class PlannedClip:
    """A highlight plus the concrete cuts needed to produce its clip."""

    candidate: HighlightCandidate
    abs_start_ms: int
    abs_end_ms: int
    segments: list[Segment]
    overlaps_previous: bool = False

    @property
    def duration_ms(self) -> int:
        return self.abs_end_ms - self.abs_start_ms


@dataclass(frozen=True)
class ProbeInfo:
    """Parsed ffprobe output for one media file."""

    path: Path
    duration_seconds: float
    has_video: bool
    has_audio: bool


# --------------------------------------------------------------------------
# Chunk discovery
# --------------------------------------------------------------------------

def parse_chunk_start(name: str) -> int | None:
    """Wall-clock start (epoch ms) encoded in a recorder file name prefix.

    ``2026-08-07-22-24-43-052-...`` → ms since epoch (naive local time, the
    clock the recorder used). Returns None when the name has no such prefix.
    """
    m = _CHUNK_PREFIX_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = (int(g) for g in m.groups())
    try:
        dt = datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000) + ms


def find_sibling_video(xml_path: Path, root: Path | None = None) -> Path | None:
    """Locate the video recorded alongside an XML chunk.

    Preference: exact stem (``2026-08-07-22-24-43-052-标题.xml`` →
    ``2026-08-07-22-24-43-052-标题.flv``), then any video file in the same
    directory sharing the time-prefix. Raises ``ClipperError`` when the
    prefix matches several videos (ambiguous) or none (missing).
    """
    directory = root if root is not None else xml_path.parent
    stem = xml_path.stem
    exact = directory / f"{stem}.flv"
    for ext in VIDEO_EXTENSIONS:
        cand = directory / f"{stem}{ext}"
        if cand.is_file():
            return cand
    # Prefix-only fallback (title may differ slightly between the XML and the
    # video file).
    prefix = _CHUNK_PREFIX_RE.match(stem)
    if prefix:
        matches = [
            p
            for p in directory.iterdir()
            if p.is_file()
            and p.suffix.lower() in VIDEO_EXTENSIONS
            and p.stem.startswith(prefix.group(0))
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ClipperError(
                f"ambiguous sibling video for {xml_path}: {[m.name for m in matches]}"
            )
    raise ClipperError(
        f"no sibling video for {xml_path.name} in {directory} "
        f"(expected a {VIDEO_EXTENSIONS} file with the same name prefix)"
    )


def chunk_videos(
    xml_paths: list[Path],
    *,
    contiguous_gap_ms: int = 60 * 60 * 1000,
) -> list[ChunkVideo]:
    """Build the chunk list for one session, ordered by start time.

    Each XML's sibling video becomes one chunk; the chunk's start is the
    file-name prefix (falling back to file creation time when the prefix is
    unparseable); a chunk's end is the next chunk's start when the two are
    close enough to be contiguous (matching ``sessions.py``), else unknown.
    """
    chunks: list[ChunkVideo] = []
    for xml in xml_paths:
        video = find_sibling_video(xml)
        start = parse_chunk_start(video.name)
        if start is None:
            start = int(video.stat().st_ctime * 1000)
        chunks.append(ChunkVideo(path=video, start_ms=start, end_ms=None))
    chunks.sort(key=lambda c: c.start_ms)

    # Fill each chunk's end with the next chunk's start when contiguous.
    out: list[ChunkVideo] = []
    for i, c in enumerate(chunks):
        end = (
            chunks[i + 1].start_ms
            if i + 1 < len(chunks)
            and (chunks[i + 1].start_ms - c.start_ms <= contiguous_gap_ms)
            else None
        )
        out.append(ChunkVideo(path=c.path, start_ms=c.start_ms, end_ms=end))
    return out


# --------------------------------------------------------------------------
# Clip planning
# --------------------------------------------------------------------------

def plan_clips(
    highlights: list[HighlightCandidate],
    chunks: list[ChunkVideo],
    anchor_ms: int,
    *,
    pre_roll: float = 10.0,
    post_roll: float = 15.0,
    max_duration: float = 300.0,
) -> list[PlannedClip]:
    """Map every candidate to absolute intervals and per-chunk segments.

    - buffers: ``pre_roll`` seconds before ``t_start`` (the density window W
      means the event actually started earlier) and ``post_roll`` after
      ``t_end`` (let the decay play out);
    - ``max_duration`` caps the clip length, centred on the candidate's peak
      (0 disables the cap);
    - each intersecting chunk contributes one segment; holes between chunks
      are simply not covered (no cutting across gaps);
    - clips that overlap after buffering are flagged via
      ``overlaps_previous`` (rare: the detector already merges runs < 30s).
    """
    ordered = sorted(chunks, key=lambda c: c.start_ms)
    out: list[PlannedClip] = []
    for h in highlights:
        abs_start = anchor_ms + int(round(h.t_start * 1000)) - int(round(pre_roll * 1000))
        abs_end = anchor_ms + int(round(h.t_end * 1000)) + int(round(post_roll * 1000))
        cap_ms = int(round(max_duration * 1000)) if max_duration > 0 else 0
        if cap_ms and (abs_end - abs_start) > cap_ms:
            peak_abs = anchor_ms + int(round(h.peak_t * 1000))
            half = cap_ms // 2
            abs_start = max(abs_start, peak_abs - half)
            abs_end = min(abs_end, peak_abs + half)

        segments: list[Segment] = []
        for c in ordered:
            c_end = c.end_ms if c.end_ms is not None else abs_end
            lo = max(abs_start, c.start_ms)
            hi = min(abs_end, c_end)
            if lo < hi:
                segments.append(
                    Segment(
                        video=c.path,
                        local_start_ms=lo - c.start_ms,
                        local_end_ms=hi - c.start_ms,
                    )
                )
        out.append(
            PlannedClip(
                candidate=h,
                abs_start_ms=abs_start,
                abs_end_ms=abs_end,
                segments=segments,
            )
        )

    for prev, cur in zip(out, out[1:]):
        if cur.abs_start_ms < prev.abs_end_ms:
            cur.overlaps_previous = True
    return out


# --------------------------------------------------------------------------
# ffmpeg / ffprobe
# --------------------------------------------------------------------------

def fmt_ffmpeg_time(ms: int) -> str:
    """``HH:MM:SS.mmm`` (hours may exceed 24 for very long sources)."""
    total_ms = int(ms)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms3 = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms3:03d}"


def build_ffmpeg_cmd(
    segment: Segment,
    output_path: Path,
    *,
    precise: bool = True,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """ffmpeg command that cuts one segment.

    ``precise`` (default) re-encodes to H.264/AAC for frame-accurate cuts;
    ``precise=False`` uses ``-c copy`` (keyframe-aligned, seconds instead of
    minutes, start may be up to one GOP early). ``-ss`` sits before ``-i``
    (input seeking) so both modes locate the region fast.
    """
    start = fmt_ffmpeg_time(segment.local_start_ms)
    duration = f"{(segment.local_end_ms - segment.local_start_ms) / 1000.0:.3f}"
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", start, "-i", str(segment.video), "-t", duration]
    if precise:
        return base + [
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-movflags", "+faststart", str(output_path),
        ]
    return base + ["-c", "copy", "-avoid_negative_ts", "make_zero", str(output_path)]


def probe(path: Path, *, ffprobe: str = "ffprobe") -> ProbeInfo:
    """Read duration and stream presence from a media file via ffprobe."""
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise ClipperError(f"ffprobe not found (need ffmpeg installed): {exc}") from exc
    if proc.returncode != 0:
        raise ClipperError(
            f"ffprobe failed for {path}: {proc.stderr.strip() or 'unknown error'}"
        )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ClipperError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc
    duration = float(data.get("format", {}).get("duration") or 0.0)
    codec_types = [s.get("codec_type") for s in data.get("streams", [])]
    return ProbeInfo(
        path=Path(path),
        duration_seconds=duration,
        has_video="video" in codec_types,
        has_audio="audio" in codec_types,
    )


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

def write_manifest(
    clips: list[PlannedClip],
    results: dict[int, list[dict[str, object]]],
    path: Path,
) -> None:
    """Write one CSV row per (clip, segment) with source/offsets/outcome.

    ``results`` maps clip index → per-segment dicts (status, output, probe
    info); segments without a result still appear with empty fields. Written
    as UTF-8 with BOM so Excel opens Chinese text correctly.
    """
    rows: list[dict[str, object]] = []
    for i, clip in enumerate(clips):
        h = clip.candidate
        seg_results = results.get(i) or []
        for j, seg in enumerate(clip.segments):
            info = seg_results[j] if j < len(seg_results) else {}
            rows.append(
                {
                    "clip_index": i,
                    "grade": h.level,
                    "shape": h.shape,
                    "level": h.level,
                    "t_start": f"{h.t_start:.1f}",
                    "t_end": f"{h.t_end:.1f}",
                    "peak_t": f"{h.peak_t:.1f}",
                    "abs_start_ms": clip.abs_start_ms,
                    "abs_end_ms": clip.abs_end_ms,
                    "overlaps_previous": clip.overlaps_previous,
                    "segment_index": j,
                    "n_segments": len(clip.segments),
                    "source": str(seg.video),
                    "local_start_ms": seg.local_start_ms,
                    "local_end_ms": seg.local_end_ms,
                    "output": info.get("output", ""),
                    "status": info.get("status", ""),
                    "actual_duration_s": info.get("actual_duration_s", ""),
                    "has_video": info.get("has_video", ""),
                    "has_audio": info.get("has_audio", ""),
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
