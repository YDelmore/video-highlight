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
