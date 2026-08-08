"""Integration test that exercises the CLI on the real fixture XML."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "video_highlight", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=60,
    )


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
    """Passing --plot generates a PNG file (or degrades gracefully)."""
    xml = project_root / "docs" / "danmaku.xml"
    out = tmp_path / "chart.png"
    result = _run_cli(str(xml), "--plot", str(out))
    assert result.returncode == 0
    # Either the PNG was created, or matplotlib was unavailable (warned).
    assert out.exists() or "matplotlib" in (
        result.stdout + result.stderr
    ).lower()
