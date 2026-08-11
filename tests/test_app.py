"""Smoke tests for the Streamlit platform via AppTest."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "src" / "video_highlight" / "app.py"
DEFAULT_XML = (
    REPO_ROOT / "docs" / "2026-08-07-22-24-43-052-解说一下今天比赛.xml"
)

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _timeline_slider(at: AppTest):
    return next(s for s in at.slider if s.key == "timeline_slider")


def _jump_button(at: AppTest, key: str = "jump_0"):
    return next(b for b in at.button if b.key == key)


def test_app_boots_and_renders() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    assert not at.exception
    # master timeline is present
    assert len(at.slider) >= 1
    _timeline_slider(at)


def test_timeline_drag_links_clock() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    slider = _timeline_slider(at)
    slider.set_value(100.0)
    at.run()
    assert not at.exception
    assert at.session_state["current_time"] == 100.0


def test_jump_button_moves_clock_to_climax_start() -> None:
    from video_highlight.highlights import find_candidates
    from video_highlight.loader import to_dataframe
    from video_highlight.metrics.density import compute as compute_density
    from video_highlight.parser import parse_xml

    records = parse_xml(str(DEFAULT_XML))
    candidates = find_candidates(compute_density(to_dataframe(records)))
    if not candidates:
        pytest.skip("default dataset has no highlight candidate")

    at = AppTest.from_file(str(APP_PATH))
    at.run()
    _jump_button(at).click()
    at.run()
    assert not at.exception
    assert at.session_state["current_time"] == candidates[0].t_start


# ---------------------------------------------------------------------------
# Uploaded danmaku file (file_uploader takes precedence over the path input)
# ---------------------------------------------------------------------------

def _uploader(at: AppTest):
    return next(u for u in at.file_uploader if u.key == "uploaded_xml")


def test_uploaded_file_is_used_as_source(sample_xml_path: Path) -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    _uploader(at).upload(
        sample_xml_path.name, sample_xml_path.read_bytes(), "text/xml"
    )
    at.run()
    assert not at.exception
    # the 5-bullet upload replaced the default dataset (headline metric + source label)
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "5"
    captions = [c.value for c in at.caption]
    assert any("已上传" in c and sample_xml_path.name in c for c in captions)


def test_upload_invalid_xml_shows_error_not_crash() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    _uploader(at).upload("broken.xml", b"this is not xml at all <><><>", "text/xml")
    at.run()
    assert not at.exception  # surfaced as st.error, not an uncaught traceback
    assert at.error
