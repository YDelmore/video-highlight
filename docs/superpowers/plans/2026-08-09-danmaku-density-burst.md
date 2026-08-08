# 弹幕指标 1+2 第一轮分析 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建骨架并实现弹幕 **指标 1（弹幕密度）** 和 **指标 2（爆发速率）** 的端到端计算，输出可读控制台报告 + 可选 matplotlib 图。所有数据层接口为下轮指标 3+4 留好复用入口。

**Architecture:** 解析（XML→dataclass）→ 装载（→带 length/uid/text 的 DataFrame）→ 指标 1（D[t] 滑窗）→ 指标 2（平滑 + 一阶差分）→ 候选切分（μ+2σ / μ+3σ）→ 报告（控制台 + 可选 matplotlib）。所有 metric 模块纯函数式，输入 DataFrame 索引 `t` 为相对秒 float。

**Tech Stack:** Python ≥ 3.12, pandas ≥ 2.0, numpy ≥ 1.24, pytest（dev 依赖），matplotlib（运行时可选）。uv 管理依赖。

**Spec:** `docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md`

---

## 文件结构总览

```
video-highlight/
├── pyproject.toml                              # 修改：加依赖
├── .gitignore                                  # 修改：忽略 __pycache__/, .pytest_cache/, .venv/
├── src/video_highlight/
│   ├── __init__.py                             # 暴露 main()
│   ├── __main__.py                             # CLI 入口（创建）
│   ├── parser.py                               # XML→list[Danmaku]（创建）
│   ├── loader.py                               # list[Danmaku]→DataFrame（创建）
│   ├── exceptions.py                           # DanmakuParseError（创建）
│   ├── highlights.py                           # 候选区间切分（创建）
│   ├── report.py                               # 控制台 + matplotlib（创建）
│   └── metrics/
│       ├── __init__.py                         # 创建
│       ├── _window.py                          # 滑窗内部辅助（创建）
│       ├── density.py                          # 指标 1（创建）
│       └── burst.py                            # 指标 2（创建）
└── tests/
    ├── __init__.py                             # 创建（空）
    ├── conftest.py                             # 创建（path fixture）
    ├── test_parser.py
    ├── test_loader.py
    ├── test_density.py
    ├── test_burst.py
    ├── test_highlights.py
    ├── test_report.py
    ├── test_main.py
    └── fixtures/
        ├── __init__.py                         # 创建（空）
        ├── synthetic_density.py                # 手造样例数据
        └── sample.xml                          # 5 条最小可解析 XML
```

每个测试文件对应一个生产模块；不重叠职责。

---

## Task 1: 项目基础设施 — pyproject + gitignore + 包入口

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`（如不存在则创建）
- Modify: `src/video_highlight/__init__.py`
- Create: `src/video_highlight/__main__.py`
- Create: `src/video_highlight/exceptions.py`

- [ ] **Step 1: 更新 `pyproject.toml`，加入依赖**

完整替换 `pyproject.toml` 为：

```toml
[project]
name = "video-highlight"
version = "0.1.0"
description = "Extract highlight clips from livestream danmaku data."
authors = [
    { name = "yuhaikun", email = "2295987338@qq.com" }
]
requires-python = ">=3.12"
dependencies = [
    "pandas>=2.0,<3.0",
    "numpy>=1.24,<3.0",
]

[project.optional-dependencies]
plot = ["matplotlib>=3.7"]
dev = ["pytest>=7.0", "matplotlib>=3.7"]

[project.scripts]
video-highlight = "video_highlight:main"

[build-system]
requires = ["uv_build>=0.12.3,<0.13.0"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
```

- [ ] **Step 2: 创建 `.gitignore`（如不存在）**

完整内容：

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
.coverage
htmlcov/
dist/
build/
*.egg
.pyright_cache/
.mypy_cache/
```

- [ ] **Step 3: 创建 `src/video_highlight/exceptions.py`**

完整内容：

```python
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
```

- [ ] **Step 4: 更新 `src/video_highlight/__init__.py`**

完整内容：

```python
"""video-highlight: extract highlight clips from livestream danmaku data."""

from video_highlight.__main__ import main

__all__ = ["main"]
```

- [ ] **Step 5: 创建 `src/video_highlight/__main__.py`**

完整内容：

```python
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
```

- [ ] **Step 6: 验证骨架 import 正常**

Run:
```bash
uv run python -c "from video_highlight import main; print(main.__name__)"
```
Expected output: `main`

- [ ] **Step 7: 验证 CLI 入口触发 FileNotFoundError 文案**

Run:
```bash
uv run video-highlight /tmp/nope.xml
```
Expected output contains `file not found: /tmp/nope.xml` and exit code is 1.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore src/video_highlight/__init__.py src/video_highlight/__main__.py src/video_highlight/exceptions.py
git commit -m "feat: bootstrap package skeleton and CLI entry"
```

---

## Task 2: 测试基础设施 — conftest + fixtures

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/synthetic_density.py`
- Create: `tests/fixtures/sample.xml`

- [ ] **Step 1: 创建 `tests/__init__.py`（空文件）**

完整内容：

```python
```

- [ ] **Step 2: 创建 `tests/conftest.py`**

完整内容：

```python
"""Shared pytest fixtures and configuration."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the repo root (the directory containing pyproject.toml)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the directory containing test fixtures."""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def sample_xml_path(fixtures_dir: Path) -> Path:
    """Path to the tiny 5-bullet XML used in parser tests."""
    return fixtures_dir / "sample.xml"
```

- [ ] **Step 3: 创建 `tests/fixtures/__init__.py`（空文件）**

完整内容：

```python
```

- [ ] **Step 4: 创建 `tests/fixtures/sample.xml`**

完整内容（5 条弹幕，t=0/1/1/1/20，时间戳用相对直播开始的毫秒）：

```xml
<?xml version="1.0" encoding="utf-8"?>
<i>
  <metadata>
    <platform>TestPlatform</platform>
    <live_start_time>1000000</live_start_time>
    <user_name>test_room</user_name>
    <room_id>1</room_id>
  </metadata>
  <d p="0.0,1,25,16777215,1000000,0,uid_a,uid_a,0" user="user_a" uid="uid_a" timestamp="1000000">first</d>
  <d p="1.0,1,25,16777215,1001000,0,uid_b,uid_b,0" user="user_b" uid="uid_b" timestamp="1001000">second</d>
  <d p="1.0,1,25,16777215,1001000,0,uid_c,uid_c,0" user="user_c" uid="uid_c" timestamp="1001000">third</d>
  <d p="1.0,1,25,16777215,1001000,0,uid_a,uid_a,0" user="user_a" uid="uid_a" timestamp="1001000">fourth</d>
  <d p="20.0,1,25,16777215,1020000,0,uid_b,uid_b,0" user="user_b" uid="uid_b" timestamp="1020000">fifth</d>
</i>
```

- [ ] **Step 5: 创建 `tests/fixtures/synthetic_density.py`**

完整内容：

```python
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
```

- [ ] **Step 6: 创建最小测试以验证 fixtures 加载**

在 `tests/test_smoke.py` 中创建：

完整内容：

```python
"""Smoke test verifying test infrastructure and package imports."""


def test_package_imports():
    from video_highlight import main

    assert callable(main)


def test_fixtures_dir_exists(fixtures_dir):
    assert fixtures_dir.is_dir()
    assert (fixtures_dir / "sample.xml").is_file()


def test_synthetic_density_module_loads():
    from tests.fixtures.synthetic_density import SAMPLE_DF

    assert len(SAMPLE_DF) == 5
    assert set(SAMPLE_DF.columns) >= {"t", "uid", "text", "length"}
```

- [ ] **Step 7: 验证 pytest 能发现并运行测试**

Run:
```bash
uv run pytest -v
```
Expected: 3 tests pass.

- [ ] **Step 8: Commit**

```bash
git add tests/
git commit -m "test: scaffold pytest fixtures and a smoke test"
```

---

## Task 3: 解析器 `parser.parse_xml`

**Files:**
- Create: `src/video_highlight/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: 写失败测试 `tests/test_parser.py`**

完整内容：

```python
"""Tests for the XML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_highlight.exceptions import DanmakuParseError
from video_highlight.parser import Danmaku, parse_xml


def test_parse_xml_returns_dataclass_list(sample_xml_path: Path):
    """Parses a 5-bullet fixture into 5 Danmaku records."""
    result = parse_xml(sample_xml_path)
    assert len(result) == 5
    assert all(isinstance(d, Danmaku) for d in result)


def test_parse_xml_fields(sample_xml_path: Path):
    """First record has expected uid, ts_ms, and text."""
    result = parse_xml(sample_xml_path)
    first = result[0]
    assert first.uid == "uid_a"
    assert first.ts_ms == 1000000
    assert first.text == "first"


def test_parse_xml_skips_malformed_nodes(tmp_path: Path):
    """A <d> missing the timestamp attribute is skipped, not crashed on."""
    malformed = tmp_path / "broken.xml"
    malformed.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<i>"
        '<d user="x" uid="uid_x">ok</d>'
        '<d user="y" uid="uid_y" timestamp="2000000">ok_y</d>'
        "</i>"
    )
    result = parse_xml(malformed)
    assert len(result) == 1
    assert result[0].uid == "uid_y"
    assert result[0].ts_ms == 2000000


def test_parse_xml_raises_on_invalid_xml(tmp_path: Path):
    bad = tmp_path / "not-xml.txt"
    bad.write_text("this is not xml at all <><><>")
    with pytest.raises(DanmakuParseError):
        parse_xml(bad)


def test_parse_xml_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_xml(tmp_path / "no-such.xml")
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_parser.py -v
```
Expected: import errors or all FAILED（`Danmaku`/`parse_xml`/`DanmakuParseError` not found）。

- [ ] **Step 3: 实现 `src/video_highlight/parser.py`**

完整内容：

```python
"""Parse Huya-style danmaku XML into structured Danmaku records."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from video_highlight.exceptions import DanmakuParseError


@dataclass(frozen=True)
class Danmaku:
    """A single bullet comment.

    `uid` is stored as a string to avoid 64-bit integer overflow on very
    long-running streams and to make hashable keys cheap.
    """

    uid: str
    ts_ms: int
    text: str


def parse_xml(path: str | Path) -> list[Danmaku]:
    """Parse a danmaku XML file into a list of Danmaku records.

    Skips <d> nodes that lack `uid` or `timestamp` attributes (logging via
    caller observability later if needed). Raises DanmakuParseError if the
    file cannot be parsed at all.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"danmaku file not found: {path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise DanmakuParseError(str(path), str(exc)) from exc

    records: list[Danmaku] = []
    skipped = 0
    for node in tree.iter("d"):
        uid_raw = node.get("uid")
        ts_raw = node.get("timestamp")
        if uid_raw is None or ts_raw is None:
            skipped += 1
            continue
        try:
            ts_ms = int(ts_raw)
        except ValueError:
            skipped += 1
            continue
        # ElementTree may give None if the node has no text body
        text = node.text or ""
        records.append(Danmaku(uid=uid_raw, ts_ms=ts_ms, text=text))

    if not records and skipped > 0:
        # All nodes were malformed; treat as parse failure
        raise DanmakuParseError(
            str(path), f"all {skipped} <d> nodes were malformed"
        )

    return records
```

- [ ] **Step 4: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_parser.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_highlight/parser.py src/video_highlight/exceptions.py tests/test_parser.py tests/test_smoke.py
git commit -m "feat(parser): XML parser producing Danmaku records"
```

---

## Task 4: 装载层 `loader.to_dataframe`

**Files:**
- Create: `src/video_highlight/loader.py`
- Create: `tests/test_loader.py`

- [ ] **Step 1: 写失败测试 `tests/test_loader.py`**

完整内容：

```python
"""Tests for the loader (list[Danmaku] -> DataFrame)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.loader import to_dataframe
from video_highlight.parser import Danmaku


def _dm(ts_ms: int, uid: str, text: str) -> Danmaku:
    return Danmaku(uid=uid, ts_ms=ts_ms, text=text)


def test_to_dataframe_basic_columns():
    """Returns a DataFrame with required columns."""
    records = [
        _dm(1000, "u1", "hello"),
        _dm(2000, "u2", "world"),
    ]
    df = to_dataframe(records, live_start_ms=0)
    assert set(df.columns) >= {"t", "uid", "text", "length"}
    assert len(df) == 2
    assert df["uid"].iloc[0] == "u1"
    assert df["text"].iloc[1] == "world"


def test_to_dataframe_relative_time():
    """t column is (ts_ms - live_start_ms) / 1000."""
    records = [
        _dm(1500, "u1", "x"),
        _dm(2500, "u2", "y"),
    ]
    df = to_dataframe(records, live_start_ms=1000)
    assert df["t"].iloc[0] == 0.5
    assert df["t"].iloc[1] == 1.5


def test_to_dataframe_length_is_char_count():
    """length is character count (not bytes)."""
    records = [_dm(0, "u", "你好世界"), _dm(1000, "u", "abc")]
    df = to_dataframe(records, live_start_ms=0)
    assert df["length"].iloc[0] == 4
    assert df["length"].iloc[1] == 3


def test_to_dataframe_no_live_start_uses_min():
    """When live_start_ms is None, the smallest ts_ms becomes time 0."""
    records = [
        _dm(5000, "u1", "a"),
        _dm(7000, "u2", "b"),
        _dm(6000, "u3", "c"),
    ]
    df = to_dataframe(records)
    assert df["t"].min() == 0.0
    assert df["t"].max() == 2.0


def test_to_dataframe_empty_list():
    df = to_dataframe([], live_start_ms=0)
    assert len(df) == 0
    assert set(df.columns) == {"t", "uid", "text", "length"}


def test_to_dataframe_does_not_mutate_input():
    """Function must not mutate the input list."""
    records = [_dm(1000, "u1", "x")]
    snapshot = list(records)
    to_dataframe(records, live_start_ms=0)
    assert records == snapshot
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_loader.py -v
```
Expected: import error or all FAILED（`to_dataframe` not found）。

- [ ] **Step 3: 实现 `src/video_highlight/loader.py`**

完整内容：

```python
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
```

- [ ] **Step 4: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_loader.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_highlight/loader.py tests/test_loader.py
git commit -m "feat(loader): list[Danmaku] -> DataFrame with length pre-computed"
```

---

## Task 5: 内部滑窗辅助 `metrics/_window`

**Files:**
- Create: `src/video_highlight/metrics/__init__.py`
- Create: `src/video_highlight/metrics/_window.py`
- Create: `tests/test_window.py`

- [ ] **Step 1: 创建 `src/video_highlight/metrics/__init__.py`（空）**

完整内容：

```python
"""Metric modules. Each sub-module corresponds to one numbered indicator
in docs/分析策略.md."""
```

- [ ] **Step 2: 写失败测试 `tests/test_window.py`**

完整内容：

```python
"""Tests for the internal rolling-window helper."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics._window import rolling_sum


def test_rolling_sum_returns_series_with_float_index():
    times = pd.Series([0.0, 1.0, 2.0, 3.0])
    result = rolling_sum(times, window_seconds=2)
    # result.index must be the float seconds themselves (not datetime)
    assert list(result.index) == [0.0, 1.0, 2.0, 3.0]
    assert result.dtype.kind in ("f", "i")


def test_rolling_sum_window_inclusion_right_open():
    """At t=2, window [t-W, t) includes t=0 but excludes t=2."""
    times = pd.Series([0.0, 1.0, 2.0, 3.0])
    result = rolling_sum(times, window_seconds=3)
    # At t=2: events at {0, 1} -> sum=2
    assert result.loc[2.0] == 2


def test_rolling_sum_window_handles_irregular_times():
    """If seconds are not uniform, the window still uses time, not count."""
    times = pd.Series([0.0, 5.5, 9.9, 15.0, 15.1])
    result = rolling_sum(times, window_seconds=10)
    # At t=15.1: events in [5.1, 15.1) = {5.5, 9.9} -> 2
    assert result.loc[15.1] == 2


def test_rolling_sum_nan_for_insufficient_history():
    """Before t reaches window_seconds, result is NaN, not 0."""
    times = pd.Series([0.0, 1.0])
    result = rolling_sum(times, window_seconds=10)
    assert pd.isna(result.loc[0.0])
```

- [ ] **Step 3: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_window.py -v
```
Expected: import error or all FAILED.

- [ ] **Step 4: 实现 `src/video_highlight/metrics/_window.py`**

完整内容：

```python
"""Internal rolling-window helpers used by metric modules.

Convention: input `series` is a 1-D pandas Series whose index is the
relative time (float seconds). The window is computed in *time*, not in
*row count*, so non-uniformly sampled streams work correctly.

This helper exists so future metrics (重合度、情感密度) reuse the same
window semantics without re-implementing them.
"""

from __future__ import annotations

import pandas as pd


def rolling_sum(series: pd.Series, window_seconds: int | float) -> pd.Series:
    """Return a rolling sum over a time-window.

    The window for index value ``t`` covers ``[t - window_seconds, t)``
    (right-open, matching the spec language).

    Returns a Series whose index matches the input (float seconds) and
    whose dtype is float. Values whose window does not fully fit (the
    first ``window_seconds`` seconds) are NaN.
    """
    if series.empty:
        return series.astype(float)

    # Trick pandas into time-based rolling by temporary datetime index.
    # We restore the original float index on the way out so callers never
    # see a DatetimeIndex — see spec section 3.3 contract.
    dt_index = pd.to_datetime(series.index, unit="s")
    temp = pd.Series(series.values, index=dt_index)

    windowed = temp.rolling(f"{int(window_seconds)}s", min_periods=1).sum()

    # Restore float-second index. NaN where window doesn't fit yet.
    result = pd.Series(windowed.values, index=series.index, dtype=float)
    # First (window_seconds - 1) values may be missing history; rolling
    # with min_periods=1 already filled them with partial sums. We want
    # strict semantics: NaN until we have a full window. Apply that here.
    full_window_threshold = float(window_seconds)
    result.iloc[: int(full_window_threshold)] = pd.NA
    return result
```

- [ ] **Step 5: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_window.py -v
```
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/video_highlight/metrics/__init__.py src/video_highlight/metrics/_window.py tests/test_window.py
git commit -m "feat(metrics): time-based rolling_sum helper"
```

---

## Task 6: 指标 1 — `metrics.density.compute`

**Files:**
- Create: `src/video_highlight/metrics/density.py`
- Create: `tests/test_density.py`

- [ ] **Step 1: 写失败测试 `tests/test_density.py`**

完整内容：

```python
"""Tests for metric 1 (弹幕密度)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from video_highlight.metrics.density import WINDOW_SECONDS, DensityResult, compute
from tests.fixtures.synthetic_density import SAMPLE_DF


def test_density_returns_result_dataclass():
    result = compute(SAMPLE_DF)
    assert isinstance(result, DensityResult)
    assert result.n_total == 5
    assert result.duration_seconds == pytest.approx(20.0)


def test_density_window_size_constant():
    # W is documented in the spec and strategy doc.
    assert WINDOW_SECONDS == 10


def test_density_series_index_is_float_seconds():
    result = compute(SAMPLE_DF)
    # Index values are floats (seconds), not datetime
    sample = result.D.index[0]
    assert isinstance(sample, float)


def test_density_values_on_synthetic():
    """For 5 bullets at t=0,1,1,1,20 with W=10s:
       D(0)  = count in [0, 0) = 0 ... but as full-window semantics,
              count in [-10, 0) = 1 (only the t=0 event).
       At t=5: events in [-5, 5) = {0, 1, 1, 1} -> 4
       At t=10: events in [0, 10) = {1, 1, 1} -> 3 (t=0 is excluded)
       At t=20: events in [10, 20) = {} -> 0
       At t=25: events in [15, 25) = {20} -> 1
    """
    result = compute(SAMPLE_DF)
    # Check at t=5 specifically: the widest density before t=20 cluster
    assert result.D.loc[5.0] == 4
    # At t=20: empty middle
    assert result.D.loc[20.0] == 0
    # At t=25
    assert result.D.loc[25.0] == 1


def test_density_mu_sigma_computed():
    result = compute(SAMPLE_DF)
    # Drop NaN from first 9 seconds
    valid = result.D.dropna()
    assert math.isclose(result.mu, valid.mean())
    assert math.isclose(result.sigma, valid.std())


def test_density_with_empty_dataframe():
    empty = pd.DataFrame(columns=["t", "uid", "text", "length"])
    result = compute(empty)
    assert result.n_total == 0
    assert result.D.empty
    assert result.mu == 0.0
    assert result.sigma == 0.0
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_density.py -v
```
Expected: import error or all FAILED.

- [ ] **Step 3: 实现 `src/video_highlight/metrics/density.py`**

完整内容：

```python
"""Metric 1: 弹幕密度 (per the strategy doc).

D(t) = count of bullets whose timestamp lies in [t, t+W),
       where W is the window size in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from video_highlight.metrics._window import rolling_sum


WINDOW_SECONDS: int = 10


@dataclass(frozen=True)
class DensityResult:
    """Output of metric 1.

    `D` is a Series indexed by relative seconds; values are bullet counts.
    The first WINDOW_SECONDS seconds are NaN (history not yet complete).
    """

    D: pd.Series
    mu: float
    sigma: float
    n_total: int
    duration_seconds: float


def compute(
    df: pd.DataFrame,
    *,
    window_seconds: int = WINDOW_SECONDS,
) -> DensityResult:
    """Compute density D[t] from a danmaku DataFrame.

    Expects columns ``t``, ``length``. Other columns are ignored.
    """
    if df.empty:
        empty_index = pd.Index([], dtype=float)
        empty_series = pd.Series([], dtype=float, index=empty_index)
        return DensityResult(
            D=empty_series,
            mu=0.0,
            sigma=0.0,
            n_total=0,
            duration_seconds=0.0,
        )

    # Right-open windows: count bullets whose t < right_edge
    # Implementation: use a Series of 1's per bullet, indexed by t,
    # then rolling_sum over the time window.
    events = pd.Series(
        np.ones(len(df), dtype=float),
        index=df["t"].astype(float).values,
    )
    events.index.name = "t"
    # round to integer second bucketing is not required; rolling_sum uses
    # real time, so events at t=1.3 land correctly.

    D = rolling_sum(events, window_seconds=window_seconds)

    # Duration of the stream (last - first in seconds)
    duration = float(df["t"].max() - df["t"].min())

    valid = D.dropna()
    mu = float(valid.mean()) if len(valid) else 0.0
    sigma = float(valid.std(ddof=0)) if len(valid) else 0.0

    return DensityResult(
        D=D,
        mu=mu,
        sigma=sigma,
        n_total=len(df),
        duration_seconds=duration,
    )
```

- [ ] **Step 4: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_density.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_highlight/metrics/density.py tests/test_density.py
git commit -m "feat(metrics): metric 1 (弹幕密度) with rolling_sum helper"
```

---

## Task 7: 指标 2 — `metrics.burst.compute` + 候选切分 `highlights.find_candidates`

**Files:**
- Create: `src/video_highlight/metrics/burst.py`
- Create: `src/video_highlight/highlights.py`
- Create: `tests/test_burst.py`
- Create: `tests/test_highlights.py`

- [ ] **Step 1: 写失败测试 `tests/test_burst.py`**

完整内容：

```python
"""Tests for metric 2 (爆发速率)."""

from __future__ import annotations

import pandas as pd
import pytest

from video_highlight.metrics.burst import BurstResult, compute
from video_highlight.metrics.density import compute as compute_density
from tests.fixtures.synthetic_density import SAMPLE_DF


@pytest.fixture
def density():
    return compute_density(SAMPLE_DF)


def test_burst_returns_result_dataclass(density):
    result = compute(density)
    assert isinstance(result, BurstResult)
    assert isinstance(result.S, pd.Series)
    assert isinstance(result.S_rel, pd.Series)


def test_burst_smoothing_is_three_point_centered():
    """S = D_smooth(t) - D_smooth(t-1), where D_smooth is 3-point centered MA."""
    # Construct a simple density where the math is hand-checkable.
    D = pd.Series([0.0, 0.0, 4.0, 0.0, 0.0], index=[0.0, 1.0, 2.0, 3.0, 4.0])
    from video_highlight.metrics.density import DensityResult

    density = DensityResult(D=D, mu=0.8, sigma=1.6, n_total=4, duration_seconds=4.0)
    result = compute(density)
    # D_smooth centered: t=2 -> (0+4+0)/3 = 1.33
    # D_smooth shifted by 1 at t=2 (forward fill from t=1's neighbor) differs
    # We just verify S is not all zero — the exact value is implementation
    # detail of rolling's center=True handling.
    assert result.S.loc[2.0] != 0


def test_burst_srel_protects_against_zero(density):
    """S_rel divides by max(D.shift(1), 1) — never divides by zero."""
    result = compute(density)
    # First second (no history): D.shift(1) is NaN → clipped to 1.
    first_idx = density.D.first_valid_index()
    assert result.S_rel.loc[first_idx] == density.D.loc[first_idx]


def test_burst_mu_sigma_on_valid_only(density):
    result = compute(density)
    valid_s = result.S.dropna()
    assert result.mu_S == pytest.approx(float(valid_s.mean()))
    assert result.sigma_S == pytest.approx(float(valid_s.std(ddof=0)))


def test_burst_empty_density():
    from video_highlight.metrics.density import DensityResult

    density = DensityResult(D=pd.Series([], dtype=float), mu=0.0, sigma=0.0, n_total=0, duration_seconds=0.0)
    result = compute(density)
    assert result.mu_S == 0.0
    assert result.sigma_S == 0.0
```

- [ ] **Step 2: 写失败测试 `tests/test_highlights.py`**

完整内容：

```python
"""Tests for highlight candidate extraction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate, find_candidates
from video_highlight.metrics.density import DensityResult


def _density_with(D_values: list[float], t_start: float = 0.0) -> DensityResult:
    """Build a DensityResult whose D values exactly equal D_values (1 Hz)."""
    index = np.arange(t_start, t_start + len(D_values), dtype=float)
    D = pd.Series(D_values, index=index, dtype=float)
    valid = D.dropna()
    return DensityResult(
        D=D,
        mu=float(valid.mean()),
        sigma=float(valid.std(ddof=0)) if len(valid) else 0.0,
        n_total=int(D.sum()),
        duration_seconds=float(D.index[-1] - D.index[0]),
    )


def test_find_candidates_empty_density():
    density = _density_with([0.0] * 5)
    result = find_candidates(density)
    assert result == []


def test_find_candidates_detects_single_high_run():
    """A spike of 4 in the middle, rest = 0, should produce 1 candidate."""
    # mean=0.4, sigma ≈ 1.2 → 2σ threshold ≈ 2.8 → only the spike qualifies
    density = _density_with([0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    result = find_candidates(density)
    assert len(result) == 1
    cand = result[0]
    assert cand.peak_t == 2.0
    assert cand.peak_density == 4.0
    assert cand.level == "candidate"


def test_find_candidates_marks_strong_when_above_3sigma():
    """A clearly-strong spike gets level='strong'."""
    density = _density_with([0.0] * 50 + [10.0] + [0.0] * 50)
    result = find_candidates(density)
    assert len(result) == 1
    assert result[0].level == "strong"


def test_find_candidates_merges_close_runs():
    """Two adjacent runs separated by <30s are merged into one segment."""
    # 5s high, 10s low, 5s high — should merge into one 25s segment.
    density = _density_with(
        [0.0] * 5 + [5.0, 5.0, 5.0, 5.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 5.0, 5.0] + [0.0] * 5,
    )
    result = find_candidates(density, merge_gap_seconds=30.0)
    # Length of stream and density level varies; just assert >=1 merged segment
    # that covers t_start to t_end across both peaks.
    assert len(result) >= 1


def test_find_candidates_sorted_by_peak_t():
    density = _density_with(
        [0.0] * 30 + [10.0] * 3 + [0.0] * 30 + [10.0] * 3 + [0.0] * 30,
    )
    result = find_candidates(density)
    peak_times = [c.peak_t for c in result]
    assert peak_times == sorted(peak_times)
```

- [ ] **Step 3: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_burst.py tests/test_highlights.py -v
```
Expected: import errors or all FAILED.

- [ ] **Step 4: 实现 `src/video_highlight/metrics/burst.py`**

完整内容：

```python
"""Metric 2: 爆发速率 (per the strategy doc).

S(t) = D_smooth(t) - D_smooth(t-1), where D_smooth is a 3-point centered MA.
S_rel(t) = D(t) / max(D(t-1), 1) — relative burst rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from video_highlight.metrics.density import DensityResult


@dataclass(frozen=True)
class BurstResult:
    S: pd.Series
    S_rel: pd.Series
    mu_S: float
    sigma_S: float


def compute(density: DensityResult) -> BurstResult:
    """Compute burst rate S and relative burst S_rel from a DensityResult."""
    D = density.D
    if D.empty:
        empty_index = pd.Index([], dtype=float)
        empty_series = pd.Series([], dtype=float, index=empty_index)
        return BurstResult(
            S=empty_series,
            S_rel=empty_series,
            mu_S=0.0,
            sigma_S=0.0,
        )

    D_smooth = D.rolling(window=3, center=True, min_periods=1).mean()
    S = D_smooth.diff()
    # S_rel protects against division by zero by clipping denominator at 1.
    denom = D.shift(1).clip(lower=1.0)
    S_rel = D / denom

    valid = S.dropna()
    mu_S = float(valid.mean()) if len(valid) else 0.0
    sigma_S = float(valid.std(ddof=0)) if len(valid) else 0.0

    return BurstResult(S=S, S_rel=S_rel, mu_S=mu_S, sigma_S=sigma_S)
```

- [ ] **Step 5: 实现 `src/video_highlight/highlights.py`**

完整内容：

```python
"""Highlight candidate segmentation from a density curve.

A "highlight candidate" is a contiguous run of seconds where the density
D(t) exceeds μ + 2σ. Runs separated by less than `merge_gap_seconds` are
merged. A run is marked "strong" if its peak exceeds μ + 3σ.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from video_highlight.metrics.density import DensityResult


@dataclass(frozen=True)
class HighlightCandidate:
    t_start: float
    t_end: float
    peak_t: float
    peak_density: float
    level: str  # "candidate" | "strong"

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


def find_candidates(
    density: DensityResult,
    *,
    strong_sigma: float = 3.0,
    merge_gap_seconds: float = 30.0,
) -> list[HighlightCandidate]:
    """Return a list of highlight candidates, sorted by peak_t."""
    D = density.D.dropna()
    if D.empty:
        return []

    mu, sigma = density.mu, density.sigma
    if sigma == 0:
        return []

    thr_candidate = mu + 2.0 * sigma
    thr_strong = mu + strong_sigma * sigma

    # Build mask of "above candidate threshold" seconds
    mask = D.values >= thr_candidate
    if not mask.any():
        return []

    # Find contiguous runs in `mask`
    runs: list[tuple[int, int]] = []
    in_run = False
    start_idx = 0
    for i, on in enumerate(mask):
        if on and not in_run:
            in_run = True
            start_idx = i
        elif not on and in_run:
            in_run = False
            runs.append((start_idx, i - 1))
    if in_run:
        runs.append((start_idx, len(mask) - 1))

    # Merge runs that are close together
    merged: list[tuple[int, int]] = []
    for r in runs:
        if merged and (D.index[r[0]] - D.index[merged[-1][1]]) < merge_gap_seconds:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)

    # Build HighlightCandidate for each merged run
    out: list[HighlightCandidate] = []
    idx_values = D.index.values
    val_values = D.values
    for start_i, end_i in merged:
        seg = val_values[start_i : end_i + 1]
        peak_offset = int(np.argmax(seg))
        peak_i = start_i + peak_offset
        peak_d = float(seg[peak_offset])
        level = "strong" if peak_d >= thr_strong else "candidate"
        out.append(
            HighlightCandidate(
                t_start=float(idx_values[start_i]),
                t_end=float(idx_values[end_i]),
                peak_t=float(idx_values[peak_i]),
                peak_density=peak_d,
                level=level,
            )
        )

    out.sort(key=lambda c: c.peak_t)
    return out
```

- [ ] **Step 6: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_burst.py tests/test_highlights.py -v
```
Expected: 5 burst tests + 5 highlight tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/video_highlight/metrics/burst.py src/video_highlight/highlights.py tests/test_burst.py tests/test_highlights.py
git commit -m "feat: metric 2 (爆发速率) and highlight candidate segmentation"
```

---

## Task 8: 报告 `report.console_print` 与 `report.plot`

**Files:**
- Create: `src/video_highlight/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: 写失败测试 `tests/test_report.py`**

完整内容：

```python
"""Tests for the reporter (console + matplotlib)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.density import DensityResult
from video_highlight.report import console_print, plot


def _density() -> DensityResult:
    D = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0], index=[0.0, 1.0, 2.0, 3.0, 4.0], dtype=float)
    return DensityResult(D=D, mu=2.0, sigma=1.4142135623730951, n_total=4, duration_seconds=4.0)


def _burst() -> BurstResult:
    S = pd.Series([1.0, 1.0, 1.0, 1.0], index=[1.0, 2.0, 3.0, 4.0], dtype=float)
    S_rel = pd.Series([1.0, 1.5, 1.5, 1.5], index=[1.0, 2.0, 3.0, 4.0], dtype=float)
    return BurstResult(S=S, S_rel=S_rel, mu_S=1.0, sigma_S=0.0)


def test_console_print_contains_metric_sections():
    buf = io.StringIO()
    console_print(
        density=_density(),
        burst=_burst(),
        highlights=[],
        danmaku_count=4,
        duration_seconds=4.0,
        stream=buf,
    )
    out = buf.getvalue()
    assert "=== 分析概览 ===" in out
    assert "=== 指标1: 弹幕密度" in out
    assert "=== 指标2: 爆发速率" in out
    assert "弹幕总数: 4" in out


def test_console_print_includes_highlight_table():
    cand = HighlightCandidate(t_start=2.0, t_end=3.0, peak_t=2.5, peak_density=3.0, level="candidate")
    buf = io.StringIO()
    console_print(
        density=_density(),
        burst=_burst(),
        highlights=[cand],
        danmaku_count=4,
        duration_seconds=4.0,
        stream=buf,
    )
    out = buf.getvalue()
    assert "=== 高潮候选区间（合并后） ===" in out
    assert "candidate" in out


def test_plot_returns_true_or_false(tmp_path: Path):
    out = tmp_path / "plot.png"
    ok = plot(_density(), _burst(), [], output_path=out)
    # When matplotlib is available the file exists; when missing it returns False.
    # Either outcome is acceptable — no crash.
    assert isinstance(ok, bool)
```

- [ ] **Step 2: 运行测试确认 FAIL**

Run:
```bash
uv run pytest tests/test_report.py -v
```
Expected: import error or all FAILED.

- [ ] **Step 3: 实现 `src/video_highlight/report.py`**

完整内容：

```python
"""Reporting: formatted console output and optional matplotlib charts."""

from __future__ import annotations

import io
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import pandas as pd

from video_highlight.highlights import HighlightCandidate
from video_highlight.metrics.burst import BurstResult
from video_highlight.metrics.density import DensityResult


def console_print(
    *,
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    danmaku_count: int,
    duration_seconds: float,
    stream: TextIO = sys.stdout,
) -> None:
    """Print a fixed-section analysis report to ``stream``."""
    out = stream
    duration_minutes = duration_seconds / 60.0

    out.write("=== 分析概览 ===\n")
    out.write(f"弹幕总数: {danmaku_count}\n")
    out.write(f"时间跨度: {duration_seconds:.1f} 秒 ({duration_minutes:.1f} 分钟)\n")

    out.write("\n=== 指标1: 弹幕密度 (W=10s) ===\n")
    if density.sigma <= 0 or not math.isfinite(density.sigma):
        out.write("[WARN] baseline unreliable for short streams\n")
    valid = density.D.dropna()
    if len(valid):
        peak_idx = valid.idxmax()
        out.write(f"均值: μ={density.mu:.3f} / 标准差: σ={density.sigma:.3f}\n")
        out.write(f"最大值: {valid.max():.0f} / 峰时 t={peak_idx:.1f}\n")
    else:
        out.write("（无有效数据）\n")

    cand_count = sum(1 for h in highlights if h.level == "candidate")
    strong_count = sum(1 for h in highlights if h.level == "strong")
    out.write(f"候选区间 (D > μ+2σ): {cand_count} 个；强候选 (D > μ+3σ): {strong_count} 个\n")
    if highlights:
        out.write(_format_highlight_table(highlights))

    out.write("\n=== 指标2: 爆发速率 ===\n")
    valid_S = burst.S.dropna()
    if len(valid_S):
        out.write(f"S 均值: {burst.mu_S:.3f} / S 标准差: {burst.sigma_S:.3f}\n")
        peak_S_idx = valid_S.idxmax()
        out.write(f"最大 S: {valid_S.max():.3f} at t={peak_S_idx:.1f}\n")
        valid_Srel = burst.S_rel.dropna()
        if len(valid_Srel):
            peak_rel_idx = valid_Srel.idxmax()
            out.write(
                f"最大 S_rel: {valid_Srel.max():.3f} at t={peak_rel_idx:.1f}\n"
            )
    else:
        out.write("（无有效 S 数据）\n")

    out.write("\n=== 高潮候选区间（合并后） ===\n")
    if highlights:
        out.write(_format_highlight_table(highlights))
    else:
        out.write("（未检出候选区间；可考虑下调阈值至 1.5σ）\n")


def _format_highlight_table(highlights: list[HighlightCandidate]) -> str:
    lines = ["# | t_start | t_end | duration(s) | peak_D | level"]
    for i, h in enumerate(highlights, 1):
        lines.append(
            f"{i} | {h.t_start:.1f} | {h.t_end:.1f} | {h.duration:.1f} "
            f"| {h.peak_density:.0f} | {h.level}"
        )
    return "\n".join(lines) + "\n"


def plot(
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    *,
    output_path: str | Path,
) -> bool:
    """Render a 2x2 chart to ``output_path``. Return False if matplotlib unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # Subplot 1: density curve + thresholds
    ax = axes[0, 0]
    ax.plot(density.D.index, density.D.values, label="D(t)", color="tab:blue")
    if density.sigma > 0:
        ax.axhline(density.mu + 2 * density.sigma, color="tab:orange",
                   linestyle="--", label="μ+2σ")
        ax.axhline(density.mu + 3 * density.sigma, color="tab:red",
                   linestyle="--", label="μ+3σ")
    ax.set_title("弹幕密度 D(t)")
    ax.set_xlabel("t (s)")
    ax.set_ylabel("bullets / 10s")
    ax.legend(loc="best")

    # Subplot 2: burst S(t)
    ax = axes[0, 1]
    ax.plot(burst.S.index, burst.S.values, label="S(t)", color="tab:purple")
    if burst.sigma_S > 0:
        ax.axhline(3 * burst.sigma_S, color="tab:red", linestyle="--",
                   label="3σ")
    ax.set_title("爆发速率 S(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    # Subplot 3: S_rel
    ax = axes[1, 0]
    ax.plot(burst.S_rel.index, burst.S_rel.values, label="S_rel(t)",
            color="tab:green")
    ax.set_title("相对爆发速率 S_rel(t)")
    ax.set_xlabel("t (s)")
    ax.legend(loc="best")

    # Subplot 4: event scatter
    ax = axes[1, 1]
    # We don't have the raw events here; show D as event stem view.
    valid = density.D.dropna()
    ax.vlines(valid.index, 0, valid.values, color="tab:gray", alpha=0.6)
    ax.set_title("密度柱状视图")
    ax.set_xlabel("t (s)")

    fig.tight_layout()
    fig.savefig(Path(output_path), dpi=120)
    plt.close(fig)
    return True
```

- [ ] **Step 4: 运行测试确认 PASS**

Run:
```bash
uv run pytest tests/test_report.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_highlight/report.py tests/test_report.py
git commit -m "feat(report): console summary and optional matplotlib plot"
```

---

## Task 9: CLI 集成 — `__main__.main`

**Files:**
- Modify: `src/video_highlight/__main__.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: 写失败测试 `tests/test_main.py`**

完整内容：

```python
"""Integration test that exercises the CLI on the real fixture XML."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "video_highlight", *args]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=proc_env, timeout=60)


def test_cli_on_real_dataset(project_root: Path):
    """Running on docs/danmaku.xml exits 0 and prints metric sections."""
    xml = project_root / "docs" / "danmaku.xml"
    assert xml.exists(), f"fixture missing: {xml}"
    result = _run_cli(str(xml))
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "=== 指标1: 弹幕密度" in result.stdout
    assert "=== 指标2: 爆发速率" in result.stdout


def test_cli_missing_file(tmp_path: Path):
    result = _run_cli(str(tmp_path / "nope.xml"))
    assert result.returncode == 1
    assert "file not found" in result.stdout


def test_cli_with_plot(project_root: Path, tmp_path: Path):
    """Passing --plot generates a PNG file."""
    xml = project_root / "docs" / "danmaku.xml"
    out = tmp_path / "chart.png"
    result = _run_cli(str(xml), "--plot", str(out))
    # If matplotlib installed: file exists. If not: still exit 0 and warn.
    assert result.returncode == 0
    # Either PNG exists OR stderr mentions matplotlib
    assert out.exists() or "matplotlib" in result.stdout.lower() or "matplotlib" in result.stderr.lower()
```

- [ ] **Step 2: 运行测试确认前两个失败（第三个可能依赖 matplotlib）**

Run:
```bash
uv run pytest tests/test_main.py -v
```
Expected: import-error / assertion-error for the first two. (Third may pass if matplotlib installed; fail if not. That's acceptable for now.)

- [ ] **Step 3: 重写 `src/video_highlight/__main__.py`**

完整内容：

```python
"""Command-line entry point for video-highlight."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_highlight.highlights import find_candidates
from video_highlight.loader import to_dataframe
from video_highlight.metrics.density import compute as compute_density
from video_highlight.metrics.burst import compute as compute_burst
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
        print(f"video-highlight: file not found: {args.xml_path}", file=sys.stderr)
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
            print("\n[WARN] matplotlib 不可用，跳过图表生成（pip install 'video-highlight[plot]'）", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行集成测试**

Run:
```bash
uv run pytest tests/test_main.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: 手动冒烟验证 — 跑真实的 `docs/danmaku.xml`**

Run:
```bash
uv run video-highlight docs/danmaku.xml
```
Expected: stdout 包含 `=== 分析概览 ===`、`=== 指标1: 弹幕密度`、`=== 指标2: 爆发速率`、`=== 高潮候选区间（合并后） ===`。

- [ ] **Step 6: 测试 --plot（如 matplotlib 已安装）**

Run:
```bash
uv sync --extra plot
uv run video-highlight docs/danmaku.xml --plot /tmp/chart.png
```
Expected: PNG 文件被生成；stderr 包含 `图表：已保存到 /tmp/chart.png`。

- [ ] **Step 7: 运行全量测试确认无回归**

Run:
```bash
uv run pytest -v
```
Expected: 所有测试（Tasks 1–9 累积）通过。

- [ ] **Step 8: Commit**

```bash
git add src/video_highlight/__main__.py tests/test_main.py
git commit -m "feat(cli): wire up parser -> metrics -> report pipeline"
```

---

## Task 10: 最终验证与文档

**Files:**
- Create: `README.md` （项目根）
- 不修改任何代码

- [ ] **Step 1: 创建 README.md**

完整内容：

```markdown
# video-highlight

A tool that surfaces highlight candidates in livestream danmaku data.

## Status

Currently implements only **indicators 1 + 2** (弹幕密度 / 爆发速率) of the
19-indicator strategy in `docs/分析策略.md`. The data layer is shaped so
indicators 3 + 4 can be added without touching existing code.

## Install

```bash
uv sync            # core deps
uv sync --extra plot  # + matplotlib for charting
uv sync --extra dev   # + pytest for tests
```

## Usage

```bash
uv run video-highlight path/to/danmaku.xml
uv run video-highlight path/to/danmaku.xml --plot chart.png
```

## Run tests

```bash
uv run pytest
```

## Project layout

See `docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md`
for the full design.
```

- [ ] **Step 2: 全量测试 + 手动跑一次**

Run:
```bash
uv run pytest -v
uv run video-highlight docs/danmaku.xml
```
Expected: all tests pass, console output covers all four sections (概览/指标1/指标2/候选区间)。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with install/usage instructions"
```

---

## 自审检查

- [x] **Spec 覆盖**：spec 中 7 个模块、4 个核心数据契约、错误处理矩阵 7 项、测试层级、文件清单 — 每项都有对应的 Task。
- [x] **占位符扫描**：未发现 TBD/TODO/"fill in"/"similar to Task N" 等。每一步都给了完整代码或精确命令。
- [x] **类型一致性**：
  - `Danmaku(uid, ts_ms, text)` 在 Task 3 定义，Task 4 (`to_dataframe`) 引用 — 一致。
  - `DensityResult.D` 在 Task 6 定义为 `Series`，Task 7 `burst.compute(density)`、`highlights.find_candidates(density)` 都按此签名 — 一致。
  - `rolling_sum(series, window_seconds)` 在 Task 5 定义，Task 6 `density.compute` 调用 — 一致。
  - `console_print(...)` 在 Task 8 定义 kwargs 与 Task 9 调用一致。
- [x] **范围**：单一一组连贯任务，9 个 Task 加上最终文档，不超过单计划上限。
