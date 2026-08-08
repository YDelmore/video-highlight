"""Command-line entry point for video-highlight."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_highlight.highlights import find_candidates
from video_highlight.loader import to_dataframe
from video_highlight.metrics.burst import compute as compute_burst
from video_highlight.metrics.density import compute as compute_density
from video_highlight.parser import parse_xml
from video_highlight.report import console_print, plot


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video-highlight",
        description="Analyze livestream danmaku and surface highlight candidates.",
    )
    parser.add_argument("xml_path", type=Path, help="Path to danmaku XML file.")
    parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="If provided, save a 2x2 summary chart to this PNG path. "
        "Requires matplotlib (pip install 'video-highlight[plot]').",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run end-to-end analysis. Returns process exit code."""
    try:
        args = _parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        # argparse exits via SystemExit; convert to a stubbed return code.
        return int(exc.code or 1)

    if not args.xml_path.exists():
        print(f"video-highlight: file not found: {args.xml_path}")
        return 1

    records = parse_xml(args.xml_path)
    df = to_dataframe(records)
    density = compute_density(df)
    burst = compute_burst(density)
    highlights = find_candidates(density)

    console_print(
        density=density,
        burst=burst,
        highlights=highlights,
        danmaku_count=len(records),
        duration_seconds=density.duration_seconds,
    )

    if args.plot is not None:
        ok = plot(
            density=density,
            burst=burst,
            highlights=highlights,
            output_path=args.plot,
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
