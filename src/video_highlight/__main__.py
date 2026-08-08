"""Command-line entry point for video-highlight.

This module wires together the parser, loader, metric modules, and reporter.
The actual analysis steps will be added in Task 8 (CLI integration).
For now it only validates that the package imports work end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Entry point. Print a stub message and exit successfully.

    Real analysis wiring happens in Task 8.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("video-highlight: usage: video-highlight <path-to-xml>")
        return 1
    path = Path(args[0])
    if not path.exists():
        print(f"video-highlight: file not found: {path}")
        return 1
    print(f"video-highlight: stub OK, received {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
