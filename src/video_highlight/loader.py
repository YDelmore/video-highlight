"""Turn parsed Danmaku records into a DataFrame ready for metric modules."""

from __future__ import annotations

import pandas as pd

from video_highlight.parser import Danmaku

_REQUIRED_COLUMNS = ("t", "uid", "text", "length")


def to_dataframe(
    records: list[Danmaku],
    *,
    live_start_ms: int | None = None,
) -> pd.DataFrame:
    """Convert a list of Danmaku into a DataFrame.

    The output DataFrame always contains the columns
    ``t`` (relative seconds, float), ``uid`` (str), ``text`` (str),
    ``length`` (character count, int). The function is pure: it does not
    mutate ``records``.

    When ``live_start_ms`` is None, the smallest ``ts_ms`` is treated as
    the stream origin. This makes the first bullet land at t=0.
    """
    if not records:
        return pd.DataFrame(columns=list(_REQUIRED_COLUMNS))

    if live_start_ms is None:
        live_start_ms = min(r.ts_ms for r in records)

    df = pd.DataFrame(
        [
            {
                "t": (r.ts_ms - live_start_ms) / 1000.0,
                "uid": r.uid,
                "text": r.text,
                "length": len(r.text),
            }
            for r in records
        ]
    )

    # Ensure exact column order even if pandas inferred differently
    df = df[list(_REQUIRED_COLUMNS)]
    return df
