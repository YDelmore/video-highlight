"""Tests for the video-clipping planner (alignment, planning, commands)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from video_highlight.clipper import (
    ChunkVideo,
    PlannedClip,
    Segment,
    build_ffmpeg_cmd,
    chunk_videos,
    find_sibling_video,
    fmt_ffmpeg_time,
    parse_chunk_start,
    plan_clips,
    write_manifest,
)
from video_highlight.exceptions import ClipperError
from video_highlight.highlights import HighlightCandidate

ANCHOR = 1_000_000  # wall-clock ms of danmaku t=0


def _cand(t_start=100.0, t_end=120.0, peak=None, level="strong") -> HighlightCandidate:
    return HighlightCandidate(
        t_start=t_start,
        t_end=t_end,
        peak_t=peak if peak is not None else (t_start + t_end) / 2,
        peak_density=50.0,
        level=level,
    )


# ---------------------------------------------------------------------------
# File-name time parsing
# ---------------------------------------------------------------------------

def test_parse_chunk_start_epoch_ms():
    assert parse_chunk_start("2026-08-07-22-24-43-052-解说一下今天比赛.xml") is not None
    # 1-second step is exactly 1000 ms regardless of timezone
    a = parse_chunk_start("2026-08-07-22-24-43-000-x.xml")
    b = parse_chunk_start("2026-08-07-22-24-44-000-x.xml")
    assert b - a == 1000
    # 1-day step
    c = parse_chunk_start("2026-08-08-22-24-43-000-x.xml")
    assert c - a == 24 * 3600 * 1000


def test_parse_chunk_start_rejects_non_recorder_names():
    assert parse_chunk_start("notes.xml") is None
    assert parse_chunk_start("2026-13-99-99-99-99-999-bad.xml") is None
    assert parse_chunk_start("") is None


# ---------------------------------------------------------------------------
# Sibling video discovery
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"fake video")
    return p


def test_find_sibling_video_exact_stem(tmp_path):
    xml = _write(tmp_path, "2026-08-07-22-24-43-052-标题.xml")
    video = _write(tmp_path, "2026-08-07-22-24-43-052-标题.flv")
    assert find_sibling_video(xml) == video


def test_find_sibling_video_prefix_fallback(tmp_path):
    xml = _write(tmp_path, "2026-08-07-22-24-43-052-标题.xml")
    video = _write(tmp_path, "2026-08-07-22-24-43-052-标题-视频录制.flv")
    assert find_sibling_video(xml) == video


def test_find_sibling_video_ambiguous_raises(tmp_path):
    xml = _write(tmp_path, "2026-08-07-22-24-43-052-标题.xml")
    _write(tmp_path, "2026-08-07-22-24-43-052-a.flv")
    _write(tmp_path, "2026-08-07-22-24-43-052-b.mp4")
    with pytest.raises(ClipperError):
        find_sibling_video(xml)


def test_find_sibling_video_missing_raises(tmp_path):
    xml = _write(tmp_path, "2026-08-07-22-24-43-052-标题.xml")
    with pytest.raises(ClipperError):
        find_sibling_video(xml)


def test_chunk_videos_orders_and_fills_contiguous_end(tmp_path):
    xml_a = _write(tmp_path, "2026-08-07-22-00-00-000-a.xml")
    xml_b = _write(tmp_path, "2026-08-07-22-10-00-000-b.xml")
    _write(tmp_path, "2026-08-07-22-00-00-000-a.flv")
    _write(tmp_path, "2026-08-07-22-10-00-000-b.flv")
    chunks = chunk_videos([xml_a, xml_b])
    assert len(chunks) == 2
    assert chunks[0].start_ms < chunks[1].start_ms
    # 10 min gap <= 1h -> contiguous, so chunk A ends where B starts
    assert chunks[0].end_ms == chunks[1].start_ms
    assert chunks[1].end_ms is None


def test_chunk_videos_keeps_gap_open(tmp_path):
    xml_a = _write(tmp_path, "2026-08-07-22-00-00-000-a.xml")
    xml_b = _write(tmp_path, "2026-08-07-23-00-00-000-b.xml")  # 1h gap -> not contiguous
    _write(tmp_path, "2026-08-07-22-00-00-000-a.flv")
    _write(tmp_path, "2026-08-07-23-00-00-000-b.flv")
    chunks = chunk_videos([xml_a, xml_b], contiguous_gap_ms=30 * 60 * 1000)
    assert chunks[0].end_ms is None


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def test_plan_clips_single_chunk_applies_buffers():
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    clips = plan_clips(
        [_cand()], chunks, ANCHOR, pre_roll=10.0, post_roll=15.0, max_duration=300.0
    )
    assert len(clips) == 1
    clip = clips[0]
    # t_start=100s -> abs 100_000; minus 10s pre-roll; t_end=120s plus 15s
    assert clip.abs_start_ms == ANCHOR + 90_000
    assert clip.abs_end_ms == ANCHOR + 135_000
    assert len(clip.segments) == 1
    seg = clip.segments[0]
    assert seg.local_start_ms == ANCHOR + 90_000
    assert seg.local_end_ms == ANCHOR + 135_000
    assert seg.duration_ms == 45_000


def test_plan_clips_max_duration_centers_on_peak():
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    cand = _cand(t_start=100.0, t_end=200.0, peak=150.0)
    clips = plan_clips([cand], chunks, ANCHOR, pre_roll=10.0, post_roll=15.0,
                       max_duration=60.0)
    clip = clips[0]
    # expanded [90,215]s = 125s > 60s cap -> centred on the 150s peak
    assert clip.duration_ms == 60_000
    assert clip.abs_start_ms == ANCHOR + 120_000
    assert clip.abs_end_ms == ANCHOR + 180_000


def test_plan_clips_max_duration_zero_disables_cap():
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    cand = _cand(t_start=100.0, t_end=200.0, peak=150.0)
    clips = plan_clips([cand], chunks, ANCHOR, max_duration=0.0)
    assert clips[0].duration_ms == 125_000  # 90s pre + 115s + 15s post... 10+100+15


def test_plan_clips_spans_chunks_with_hole():
    chunks = [
        ChunkVideo(path=Path("a.flv"), start_ms=ANCHOR - 100_000, end_ms=ANCHOR + 110_000),
        ChunkVideo(path=Path("b.flv"), start_ms=ANCHOR + 130_000, end_ms=None),
    ]
    cand = _cand(t_start=100.0, t_end=130.0, peak=115.0)
    clips = plan_clips([cand], chunks, ANCHOR, pre_roll=10.0, post_roll=15.0)
    clip = clips[0]
    assert len(clip.segments) == 2
    a, b = clip.segments
    # chunk A covers [abs 90s, 110s] -> local [190s, 210s]
    assert a.local_start_ms == 190_000 and a.local_end_ms == 210_000
    # chunk B covers [abs 130s, 145s] -> local [0, 15s]
    assert b.local_start_ms == 0 and b.local_end_ms == 15_000
    # the 20s hole [110s, 130s] is not cut across


def test_plan_clips_flags_overlaps_after_buffering():
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    c1 = _cand(t_start=0.0, t_end=10.0, peak=5.0)
    c2 = _cand(t_start=30.0, t_end=40.0, peak=35.0)
    clips = plan_clips([c1, c2], chunks, ANCHOR, pre_roll=10.0, post_roll=15.0)
    assert clips[1].overlaps_previous is True
    assert clips[0].overlaps_previous is False


def test_plan_clips_empty_chunks_yields_no_segments():
    clips = plan_clips([_cand()], [], ANCHOR)
    assert clips[0].segments == []


# ---------------------------------------------------------------------------
# ffmpeg commands / time formatting
# ---------------------------------------------------------------------------

def test_fmt_ffmpeg_time():
    assert fmt_ffmpeg_time(0) == "00:00:00.000"
    assert fmt_ffmpeg_time(61_000) == "00:01:01.000"
    assert fmt_ffmpeg_time(3_661_234) == "01:01:01.234"
    assert fmt_ffmpeg_time(90_000_000) == "25:00:00.000"  # >24h sources


def test_build_ffmpeg_cmd_precise():
    seg = Segment(video=Path("in.flv"), local_start_ms=1_090_000, local_end_ms=1_135_000)
    cmd = build_ffmpeg_cmd(seg, Path("out.mp4"), precise=True)
    assert cmd[:2] == ["ffmpeg", "-hide_banner"]
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "00:18:10.000"
    assert cmd[cmd.index("-t") + 1] == "45.000"
    assert "-c:v" in cmd and "libx264" in cmd
    assert "-c:a" in cmd and "aac" in cmd
    assert cmd[-1] == str(Path("out.mp4"))


def test_build_ffmpeg_cmd_fast_copy():
    seg = Segment(video=Path("in.flv"), local_start_ms=0, local_end_ms=5_000)
    cmd = build_ffmpeg_cmd(seg, Path("out.mp4"), precise=False)
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert "-avoid_negative_ts" in cmd
    assert "libx264" not in cmd


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_write_manifest(tmp_path):
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    clips = plan_clips([_cand()], chunks, ANCHOR, pre_roll=10.0, post_roll=15.0)
    results = {
        0: [
            {
                "output": "clip_000_strong_spike_00-00-00-00-00-00.mp4",
                "status": "ok",
                "actual_duration_s": 45.0,
                "has_video": True,
                "has_audio": True,
            }
        ]
    }
    path = tmp_path / "manifest.csv"
    write_manifest(clips, results, path)

    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    row = rows[0]
    assert row["clip_index"] == "0"
    assert row["shape"] == "spike"
    assert row["source"] == "a.flv"
    assert row["local_start_ms"] == str(ANCHOR + 90_000)
    assert row["status"] == "ok"
    assert row["actual_duration_s"] == "45.0"


def test_write_manifest_reports_missing_segments(tmp_path):
    chunks = [ChunkVideo(path=Path("a.flv"), start_ms=0, end_ms=None)]
    clips = plan_clips([_cand()], chunks, ANCHOR)
    path = tmp_path / "manifest.csv"
    write_manifest(clips, {}, path)  # no execution results
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["status"] == ""
    assert rows[0]["output"] == ""
