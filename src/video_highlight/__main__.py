"""Command-line entry point for video-highlight."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_highlight.highlights import DetectionParams, find_candidates, resolve_thresholds
from video_highlight.loader import to_dataframe
from video_highlight.metrics.activation import compute as compute_activation
from video_highlight.metrics.burst import compute as compute_burst
from video_highlight.metrics.concentration import compute as compute_concentration
from video_highlight.metrics.density import compute as compute_density
from video_highlight.metrics.length_dist import compute as compute_length_dist
from video_highlight.metrics.lifecycle import compute as compute_lifecycle
from video_highlight.metrics.overlap import compute as compute_overlap
from video_highlight.metrics.repeat import compute as compute_repeat
from video_highlight.metrics.repeat import spam_exclude_mask
from video_highlight.metrics.returning import compute as compute_returning
from video_highlight.parser import parse_xml
from video_highlight.report import console_print, plot

_DEFAULT_XML = Path("docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video-highlight",
        description="Analyze livestream danmaku and surface highlight candidates.",
    )
    parser.add_argument(
        "xml_path",
        type=Path,
        nargs="?",
        default=None,
        help=f"Path to danmaku XML file. When omitted, {_DEFAULT_XML} in the "
        "current directory is used if present.",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="If provided, save a 3x3 summary chart to this PNG path. "
        "Requires matplotlib (pip install 'video-highlight[plot]').",
    )
    parser.add_argument(
        "--threshold-mode",
        choices=["sigma", "robust", "percentile"],
        default="sigma",
        help="Baseline for the density thresholds: sigma (μ+kσ), robust "
        "(median+k·MAD, resists outlier inflation), or percentile "
        "(quantiles of the density curve).",
    )
    parser.add_argument(
        "--candidate-sigma",
        type=float,
        default=DetectionParams().candidate_sigma,
        help="Candidate threshold multiplier (μ/median + k·σ/MAD).",
    )
    parser.add_argument(
        "--strong-sigma",
        type=float,
        default=DetectionParams().strong_sigma,
        help="Strong-candidate threshold multiplier.",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=DetectionParams().min_duration_seconds,
        help="Drop candidate runs shorter than this many seconds "
        "(filters single-second noise spikes).",
    )
    parser.add_argument(
        "--merge-gap",
        type=float,
        default=DetectionParams().merge_gap_seconds,
        help="Merge runs separated by less than this many seconds.",
    )
    parser.add_argument(
        "--no-spam-filter",
        action="store_true",
        help="Disable the repeated-text (刷屏) false-peak filter.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run end-to-end analysis. Returns process exit code."""
    try:
        args = _parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        # argparse exits via SystemExit; convert to a return code (help -> 0).
        return int(exc.code if exc.code is not None else 1)

    if args.xml_path is None:
        # Convenience default for IDE "Run" / interactive use: pick the
        # repo's sample file when present, otherwise fail with usage.
        if _DEFAULT_XML.is_file():
            args.xml_path = _DEFAULT_XML
        else:
            print(
                f"video-highlight: no xml_path given and no {_DEFAULT_XML} "
                "found in the current directory"
            )
            print("usage: video-highlight <path-to-xml> [--plot OUT]")
            return 1

    if not args.xml_path.exists():
        print(f"video-highlight: file not found: {args.xml_path}")
        return 1

    params = DetectionParams(
        threshold_mode=args.threshold_mode,
        candidate_sigma=args.candidate_sigma,
        strong_sigma=args.strong_sigma,
        min_duration_seconds=args.min_duration,
        merge_gap_seconds=args.merge_gap,
    )

    records = parse_xml(args.xml_path)
    df = to_dataframe(records)
    density = compute_density(df)
    burst = compute_burst(density)
    repeat = compute_repeat(df)
    concentration = compute_concentration(df)
    overlap = compute_overlap(df)

    exclude = None
    if not args.no_spam_filter:
        exclude = spam_exclude_mask(
            repeat,
            concentration,
            max_ratio=params.spam_max_ratio,
            conc_threshold=params.spam_concentration,
        )

    highlights = find_candidates(
        density,
        exclude=exclude,
        merge_overlap=overlap.overlap,
        **params.find_kwargs(),
    )

    activation = compute_activation(df)
    length_dist = compute_length_dist(df)
    lifecycle = compute_lifecycle(df, highlights)
    returning = compute_returning(df, highlights)

    thr_c, thr_s = resolve_thresholds(
        density,
        threshold_mode=params.threshold_mode,
        candidate_sigma=params.candidate_sigma,
        strong_sigma=params.strong_sigma,
        candidate_percentile=params.candidate_percentile,
        strong_percentile=params.strong_percentile,
    )

    spam_note = None
    if exclude is not None:
        n_excluded = int(exclude.sum())
        spam_note = (
            f"[刷屏过滤] 排除 {n_excluded} 个秒级窗口 "
            f"(重复占比≥{params.spam_max_ratio:.0%} 且 Top-3 集中度"
            f"≥{params.spam_concentration:.0%})"
        )

    console_print(
        density=density,
        burst=burst,
        highlights=highlights,
        activation=activation,
        length_dist=length_dist,
        concentration=concentration,
        overlap=overlap,
        lifecycle=lifecycle,
        returning=returning,
        danmaku_count=len(records),
        duration_seconds=density.duration_seconds,
        candidate_threshold=thr_c,
        strong_threshold=thr_s,
        threshold_label=params.threshold_mode,
        spam_note=spam_note,
    )

    if args.plot is not None:
        ok = plot(
            density=density,
            burst=burst,
            highlights=highlights,
            activation=activation,
            length_dist=length_dist,
            concentration=concentration,
            overlap=overlap,
            output_path=args.plot,
            candidate_threshold=thr_c,
            strong_threshold=thr_s,
        )
        if ok:
            print(f"\n=== 图表：已保存到 {args.plot} ===", file=sys.stderr)
        else:
            print(
                "\n[WARN] matplotlib 不可用，跳过图表生成"
                "（pip install 'video-highlight[plot]'）",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
