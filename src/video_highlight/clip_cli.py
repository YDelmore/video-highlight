"""CLI: slice video recordings into highlight clips.

Usage::

    python -m video_highlight.clip_cli <xml-or-root> [--out clips] [--fast]
            [--pre-roll 10] [--post-roll 15] [--max-duration 300]
            [--anchor-ms MS] [--dry-run] [--ffmpeg PATH] [--ffprobe PATH]

``<xml-or-root>`` is either a single danmaku XML (its sibling video is
located automatically) or a directory of chunks (every discovered session is
processed, chunks are aggregated exactly like the analysis platform).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from video_highlight.clipper import (
    PlannedClip,
    build_ffmpeg_cmd,
    chunk_videos,
    find_sibling_video,
    plan_clips,
    probe,
    write_manifest,
)
from video_highlight.highlights import DetectionParams, find_candidates
from video_highlight.loader import to_dataframe
from video_highlight.metrics.burst import compute as compute_burst
from video_highlight.metrics.concentration import compute as compute_concentration
from video_highlight.metrics.density import compute as compute_density
from video_highlight.metrics.overlap import compute as compute_overlap
from video_highlight.metrics.repeat import compute as compute_repeat
from video_highlight.metrics.repeat import spam_exclude_mask
from video_highlight.parser import parse_xml
from video_highlight.sessions import discover_sessions, load_records

VIDEO_SUFFIX = ".mp4"


def _detect(records, anchor_ms: int, detection: DetectionParams) -> list:
    """Run the detection pipeline (mirrors the CLI/app) and return candidates."""
    df = to_dataframe(records, live_start_ms=anchor_ms)
    density = compute_density(df)
    concentration = compute_concentration(df)
    overlap = compute_overlap(df)
    repeat = compute_repeat(df)
    exclude = None
    if detection.spam_min_repeats > 0:
        exclude = spam_exclude_mask(
            repeat,
            concentration,
            max_ratio=detection.spam_max_ratio,
            conc_threshold=detection.spam_concentration,
        )
    return find_candidates(
        density,
        exclude=exclude,
        merge_overlap=overlap.overlap,
        **detection.find_kwargs(),
    )


def _hms(ms: int) -> str:
    """Compact ``HH-MM-SS`` for file names (local wall-clock, wraps at 24h)."""
    dt = datetime.fromtimestamp(int(ms) / 1000.0)
    return f"{dt.hour:02d}-{dt.minute:02d}-{dt.second:02d}"


def _safe_dirname(label: str) -> str:
    keep = "".join(c if c.isalnum() or c in " _-." else "_" for c in label)
    return keep.strip() or "session"


def _output_name(clip: PlannedClip, index: int, segment_index: int) -> str:
    h = clip.candidate
    base = (
        f"clip_{index:03d}_{h.level}_{h.shape}_"
        f"{_hms(clip.abs_start_ms)}-{_hms(clip.abs_end_ms)}"
    )
    if len(clip.segments) > 1:
        base += f"_p{segment_index + 1}"
    return base + VIDEO_SUFFIX


def _run_ffmpeg(cmd: list[str], dry_run: bool) -> dict[str, object]:
    if dry_run:
        return {"status": "dry-run", "cmd": cmd}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
    if proc.returncode != 0:
        return {
            "status": "failed",
            "stderr": (proc.stderr or "").strip()[-2000:],
        }
    return {"status": "ok"}


def process_source(
    *,
    xml_paths: list[Path],
    records,
    anchor_ms: int,
    out_dir: Path,
    pre_roll: float,
    post_roll: float,
    max_duration: float,
    precise: bool,
    dry_run: bool,
    ffmpeg: str,
    ffprobe: str,
    detection: DetectionParams = DetectionParams(),
) -> int:
    """Detect highlights, slice, validate and write the manifest. Returns #clips."""
    chunks = chunk_videos(xml_paths)
    highlights = _detect(records, anchor_ms, detection)
    clips = plan_clips(
        highlights,
        chunks,
        anchor_ms,
        pre_roll=pre_roll,
        post_roll=post_roll,
        max_duration=max_duration,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, list[dict[str, object]]] = {}
    n_ok = 0
    for i, clip in enumerate(clips):
        if not clip.segments:
            print(f"[warn] clip {i}: no video chunk covers [{clip.abs_start_ms}..{clip.abs_end_ms}]")
            results[i] = []
            continue
        per_seg: list[dict[str, object]] = []
        for j, seg in enumerate(clip.segments):
            out_path = out_dir / _output_name(clip, i, j)
            cmd = build_ffmpeg_cmd(seg, out_path, precise=precise, ffmpeg=ffmpeg)
            info = _run_ffmpeg(cmd, dry_run)
            info["output"] = str(out_path)
            if info.get("status") == "ok" and not dry_run:
                try:
                    p = probe(out_path, ffprobe=ffprobe)
                    info["actual_duration_s"] = round(p.duration_seconds, 3)
                    info["has_video"] = p.has_video
                    info["has_audio"] = p.has_audio
                    ok = p.has_video and p.has_audio and p.duration_seconds > 0
                    info["status"] = "ok" if ok else "invalid"
                    if ok:
                        n_ok += 1
                except Exception as exc:  # noqa: BLE001 - report and continue
                    info["status"] = f"probe-failed: {exc}"
            elif info.get("status") == "ok":
                n_ok += 1
            per_seg.append(info)
            print(
                f"[{'DRY' if dry_run else 'OK '}] clip {i} seg {j}: "
                f"{seg.video.name} +{seg.local_start_ms / 1000:.1f}s → {out_path.name}"
            )
        results[i] = per_seg

    manifest = out_dir / "manifest.csv"
    write_manifest(clips, results, manifest)
    print(f"\n候选 {len(clips)} 个 → 片段 {n_ok} 个；清单: {manifest}")
    return len(clips)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="video-highlight-clip",
        description="Slice video recordings into highlight clips from "
        "detected danmaku climax intervals.",
    )
    parser.add_argument("xml_or_root", type=Path,
                        help="单个弹幕 XML，或包含分片 XML 的根目录（整场直播模式）。")
    parser.add_argument("--out", type=Path, default=Path("clips"),
                        help="输出目录（默认 ./clips）。")
    parser.add_argument("--pre-roll", type=float, default=10.0,
                        help="高潮起点前缓冲秒数（默认 10，>= 弹幕窗口 W）。")
    parser.add_argument("--post-roll", type=float, default=15.0,
                        help="高潮结束后缓冲秒数（默认 15，让余波完整）。")
    parser.add_argument("--max-duration", type=float, default=300.0,
                        help="单条切片时长上限（秒，默认 300；0=不限制）。")
    parser.add_argument("--fast", action="store_true",
                        help="快速模式：-c copy 关键帧对齐（起点最多偏差一个 GOP）。")
    parser.add_argument("--anchor-ms", type=int, default=None,
                        help="弹幕 t=0 对应的墙钟毫秒；默认取首条弹幕 ts_ms。")
    parser.add_argument("--threshold-mode", choices=["sigma", "robust", "percentile"],
                        default=DetectionParams().threshold_mode,
                        help="候选阈值基线（同 video-highlight CLI）。")
    parser.add_argument("--candidate-sigma", type=float,
                        default=DetectionParams().candidate_sigma)
    parser.add_argument("--strong-sigma", type=float,
                        default=DetectionParams().strong_sigma)
    parser.add_argument("--min-duration", type=float,
                        default=DetectionParams().min_duration_seconds,
                        help="丢弃短于此的候选（秒）。")
    parser.add_argument("--no-spam-filter", action="store_true",
                        help="关闭重复文本刷屏假峰过滤。")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印 ffmpeg 命令，不执行、不探测。")
    parser.add_argument("--ffmpeg", default=None, help="ffmpeg 可执行文件路径。")
    parser.add_argument("--ffprobe", default=None, help="ffprobe 可执行文件路径。")
    args = parser.parse_args(argv)

    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    ffprobe = args.ffprobe or shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        print("错误：未找到 ffmpeg/ffprobe，请先安装 FFmpeg 或 --ffmpeg/--ffprobe 指定路径。")
        return 1

    detection = DetectionParams(
        threshold_mode=args.threshold_mode,
        candidate_sigma=args.candidate_sigma,
        strong_sigma=args.strong_sigma,
        min_duration_seconds=args.min_duration,
        spam_min_repeats=0 if args.no_spam_filter else DetectionParams().spam_min_repeats,
    )

    source = args.xml_or_root
    total_clips = 0
    if source.is_dir():
        sessions, unclassified = discover_sessions(source)
        if not sessions:
            print(f"错误：{source} 下未发现任何弹幕分片。")
            return 1
        for session in sessions:
            records, notes = load_records(session)
            if not records:
                print(f"[warn] 场次 {session.label} 无弹幕，跳过。")
                continue
            anchor = args.anchor_ms if args.anchor_ms is not None else records[0].ts_ms
            out_dir = args.out / _safe_dirname(
                f"{session.platform}_{session.user_name}_{session.label}"
            )
            n = process_source(
                xml_paths=list(session.chunks),
                records=records,
                anchor_ms=anchor,
                out_dir=out_dir,
                pre_roll=args.pre_roll,
                post_roll=args.post_roll,
                max_duration=args.max_duration,
                precise=not args.fast,
                dry_run=args.dry_run,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                detection=detection,
            )
            total_clips += n
    else:
        if not source.is_file():
            print(f"错误：文件不存在 {source}")
            return 1
        records = parse_xml(source)
        if not records:
            print(f"错误：{source} 未解析出任何弹幕。")
            return 1
        anchor = args.anchor_ms if args.anchor_ms is not None else records[0].ts_ms
        total_clips = process_source(
            xml_paths=[source],
            records=records,
            anchor_ms=anchor,
            out_dir=args.out,
            pre_roll=args.pre_roll,
            post_roll=args.post_roll,
            max_duration=args.max_duration,
            precise=not args.fast,
            dry_run=args.dry_run,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            detection=detection,
        )
    return 0 if total_clips >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
