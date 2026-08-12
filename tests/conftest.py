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


@pytest.fixture
def chunk_xml() -> callable:
    """Build a recorder-style chunk XML string (utf-8).

    ``nodes`` is a sequence of ``(uid, ts_ms, text)`` triples rendered as
    ``<d>`` nodes; the metadata block carries ``live_start_time`` so the chunk
    can be grouped by session.
    """

    def _build(
        live_start_ms: int,
        *,
        title: str = "测试直播",
        user: str = "主播",
        room: str = "42",
        platform: str = "HuYa",
        nodes: list[tuple[str, int, str]] = (),
    ) -> str:
        body = "".join(
            f'<d p="0,1,25,16777215,{ts},0,{uid},0,0" user="u" uid="{uid}"'
            f' timestamp="{ts}">{text}</d>'
            for uid, ts, text in nodes
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n<i>\n<metadata>\n'
            f"  <platform>{platform}</platform>\n"
            f"  <user_name>{user}</user_name>\n"
            f"  <room_id>{room}</room_id>\n"
            f"  <room_title>{title}</room_title>\n"
            f"  <live_start_time>{live_start_ms}</live_start_time>\n"
            f"  <video_start_time>{live_start_ms}</video_start_time>\n"
            "</metadata>\n" + body + "\n</i>"
        )

    return _build
