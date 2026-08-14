"""Custom exceptions raised by video_highlight."""


class DanmakuError(Exception):
    """Base class for all errors raised by video_highlight."""


class DanmakuParseError(DanmakuError):
    """Raised when the XML source cannot be parsed into Danmaku records."""

    def __init__(self, path: str, message: str, line_number: int | None = None) -> None:
        suffix = f" (line {line_number})" if line_number is not None else ""
        super().__init__(f"failed to parse {path}{suffix}: {message}")
        self.path = path
        self.line_number = line_number


class ClipperError(DanmakuError):
    """Raised when highlight clipping cannot be planned or executed."""
