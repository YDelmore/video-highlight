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


NEW_XML = "docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml"


def test_cli_on_real_dataset(project_root: Path):
    """Running on the new XML exits 0 and prints all eight metric sections."""
    xml = project_root / NEW_XML
    assert xml.exists(), f"fixture missing: {xml}"
    result = _run_cli(str(xml))
    assert result.returncode == 0, f"stderr: {result.stderr}"
    for marker in [
        "=== 指标1: 弹幕密度",
        "=== 指标2: 爆发速率",
        "=== 指标3: 沉默用户激活率",
        "=== 指标4: 弹幕长度分布",
        "=== 指标5: 发言集中度",
        "=== 指标6: 用户重合度",
        "=== 指标7: 用户生命周期",
        "=== 指标8: 回锅用户比例",
    ]:
        assert marker in result.stdout


def test_cli_missing_file(tmp_path: Path):
    result = _run_cli(str(tmp_path / "nope.xml"))
    assert result.returncode == 1
    assert "file not found" in result.stdout


def test_cli_no_args_defaults_to_new_xml(project_root: Path):
    """With no arguments, running from the project root uses the new XML."""
    assert (project_root / NEW_XML).exists()
    result = _run_cli()
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "=== 指标1: 弹幕密度" in result.stdout


def test_cli_with_plot(project_root: Path, tmp_path: Path):
    """Passing --plot generates a PNG file (or degrades gracefully)."""
    xml = project_root / NEW_XML
    out = tmp_path / "chart.png"
    result = _run_cli(str(xml), "--plot", str(out))
    assert result.returncode == 0
    # Either the PNG was created, or matplotlib was unavailable (warned).
    assert out.exists() or "matplotlib" in (
        result.stdout + result.stderr
    ).lower()


def test_cli_help_exits_zero():
    """--help prints usage and exits 0 (not 1)."""
    from video_highlight.__main__ import main

    assert main(["--help"]) == 0
