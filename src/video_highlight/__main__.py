"""Command-line entry point for video-highlight."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_highlight.highlights import find_candidates
from video_highlight.loader import to_dataframe
from video_highlight.metrics.activation import compute as compute_activation
from video_highlight.metrics.burst import compute as compute_burst
from video_highlight.metrics.density import compute as compute_density
from video_highlight.metrics.length_dist import compute as compute_length_dist
from video_highlight.parser import parse_xml
from video_highlight.report import console_print, plot


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
        help="Path to danmaku XML file. When omitted, docs/danmaku.xml in the "
        "current directory is used if present.",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="If provided, save a 2x3 summary chart to this PNG path. "
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

    if args.xml_path is None:
        # Convenience default for IDE "Run" / interactive use: pick the
        # repo's sample file when present, otherwise fail with usage.
        default_xml = Path("docs/danmaku.xml")
        if default_xml.is_file():
            args.xml_path = default_xml
        else:
            print(
                "video-highlight: no xml_path given and no docs/danmaku.xml "
                "found in the current directory"
            )
            print("usage: video-highlight <path-to-xml> [--plot OUT]")
            return 1

    if not args.xml_path.exists():
        print(f"video-highlight: file not found: {args.xml_path}")
        return 1

    records = parse_xml(args.xml_path)
    df = to_dataframe(records)
    density = compute_density(df)
    burst = compute_burst(density)
    highlights = find_candidates(density)
    activation = compute_activation(df)
    length_dist = compute_length_dist(df)

    console_print(
        density=density,
        burst=burst,
        highlights=highlights,
        activation=activation,
        length_dist=length_dist,
        danmaku_count=len(records),
        duration_seconds=density.duration_seconds,
    )

    if args.plot is not None:
        ok = plot(
            density=density,
            burst=burst,
            highlights=highlights,
            activation=activation,
            length_dist=length_dist,
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
