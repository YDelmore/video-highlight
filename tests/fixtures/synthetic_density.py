"""Hand-crafted data for density/burst metric tests.

Schema mirrors what `loader.to_dataframe` returns, so the same data can be
fed directly to metric functions without parsing.
"""

from __future__ import annotations

import pandas as pd

# 5 bullets: t=0, t=1, t=1, t=1, t=20
# Two distinct uids; user_a speaks twice.
SAMPLE_DF: pd.DataFrame = pd.DataFrame(
    {
        "t": [0.0, 1.0, 1.0, 1.0, 20.0],
        "uid": ["uid_a", "uid_b", "uid_c", "uid_a", "uid_b"],
        "text": ["first", "second", "third", "fourth", "fifth"],
        "length": [5, 6, 5, 6, 5],
    }
)


def make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame from raw row dicts for tests that need variation."""
    return pd.DataFrame(rows, columns=["t", "uid", "text", "length"])
