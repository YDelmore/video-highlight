"""Smoke tests for the Streamlit platform via AppTest."""

from __future__ import annotations

from datetime import time
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


def _window_slider(at: AppTest):
    return next(s for s in at.slider if s.key == "window_seconds")


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
    # the master timeline is a HH:MM:SS time slider, so drive it with a time
    slider.set_value(time(0, 1, 40))  # 100s
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


def test_window_slider_dynamically_recomputes() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    slider = _window_slider(at)
    assert slider.value == 10  # default window
    # wider window -> longer NaN warm-up on the density signal
    assert int(at.session_state["analysis"].signals["density"].isna().sum()) == 10

    slider.set_value(30)
    at.run()
    assert not at.exception
    assert int(at.session_state["analysis"].signals["density"].isna().sum()) == 30
    captions = [c.value for c in at.caption]
    assert any("弹幕窗口 W=30s" in c for c in captions)


def test_jump_chip_shows_hms_time() -> None:
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
    start = int(candidates[0].t_start)
    hms = f"{start // 3600:02d}:{(start % 3600) // 60:02d}:{start % 60:02d}"
    assert hms in _jump_button(at).label


def test_upload_invalid_xml_shows_error_not_crash() -> None:
    at = AppTest.from_file(str(APP_PATH))
    at.run()
    _uploader(at).upload("broken.xml", b"this is not xml at all <><><>", "text/xml")
    at.run()
    assert not at.exception  # surfaced as st.error, not an uncaught traceback
    assert at.error


# ---------------------------------------------------------------------------
# Chunked-recording session mode (整场直播·分片聚合)
# ---------------------------------------------------------------------------

def _session_app(tmp_path, at: AppTest | None = None) -> AppTest:
    """Boot the app straight into session mode with a given root."""
    at = at or AppTest.from_file(str(APP_PATH))
    at.session_state["source_mode"] = "整场直播（分片聚合）"
    at.session_state["session_root"] = str(tmp_path)
    at.run()
    return at


def test_session_mode_aggregates_chunks(tmp_path, chunk_xml) -> None:
    import pathlib

    streamer_dir = pathlib.Path(tmp_path) / "HuYa" / "主播"
    streamer_dir.mkdir(parents=True, exist_ok=True)

    live = 1_786_000_000_000
    # chunk 1 has a raw control character in a username -> recovered on load
    (streamer_dir / "chunk1.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><i><metadata>'
        f"<platform>HuYa</platform><user_name>主播</user_name><room_id>42</room_id>"
        f"<room_title>测试直播</room_title>"
        f"<live_start_time>{live}</live_start_time></metadata>"
        f'<d p="0,1,25,16777215,{live + 1000},0,1,0,0" user="\x01bad"'
        f' uid="1" timestamp="{live + 1000}">hi</d></i>',
        encoding="utf-8",
    )
    (streamer_dir / "chunk2.xml").write_text(
        chunk_xml(
            live,
            user="主播",
            nodes=[("uid_b", live + 2000, "bbb"), ("uid_c", live + 3000, "ccc")],
        ),
        encoding="utf-8",
    )

    at = _session_app(tmp_path)

    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "3"  # 1 recovered + 2 from the clean chunk
    warnings = [w.value for w in at.warning]
    assert any("已修复" in w for w in warnings)
    assert any("chunk1.xml" in w for w in warnings)
    captions = [c.value for c in at.caption]
    # the source label shows 年月日 + 序号 instead of the room title
    assert any("第1场" in c and "分片聚合" in c for c in captions)


def test_session_mode_cascade_selects_platform_streamer_session(
    tmp_path, chunk_xml
) -> None:
    import pathlib

    # two sessions: different platforms and streamers
    (pathlib.Path(tmp_path) / "HuYa" / "主播A").mkdir(parents=True, exist_ok=True)
    (pathlib.Path(tmp_path) / "Bili" / "主播B").mkdir(parents=True, exist_ok=True)
    live_a, live_b = 1_786_000_000_000, 1_786_000_000_100
    (pathlib.Path(tmp_path) / "HuYa" / "主播A" / "a.xml").write_text(
        chunk_xml(
            live_a,
            platform="HuYa",
            user="主播A",
            nodes=[("u1", live_a + 1000, "a"), ("u2", live_a + 2000, "a2")],
        ),
        encoding="utf-8",
    )
    (pathlib.Path(tmp_path) / "Bili" / "主播B" / "b.xml").write_text(
        chunk_xml(
            live_b,
            platform="Bili",
            user="主播B",
            nodes=[("u3", live_b + 1000, "b")],
        ),
        encoding="utf-8",
    )

    at = _session_app(tmp_path)
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "1"  # default platform "Bili" -> 主播B

    # switching the platform re-defaults the streamer and session pickers
    next(s for s in at.selectbox if s.key == "sel_platform").set_value("HuYa")
    at.run()
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "2"  # now 主播A's 2-record session


def test_session_mode_time_interval_filters_records(tmp_path, chunk_xml) -> None:
    import pathlib

    streamer_dir = pathlib.Path(tmp_path) / "HuYa" / "主播"
    streamer_dir.mkdir(parents=True, exist_ok=True)
    live = 1_786_000_000_000
    # Timeline origin = first danmaku (live+60s), so t = 0/100/300/400s.
    (streamer_dir / "chunk1.xml").write_text(
        chunk_xml(
            live,
            user="主播",
            nodes=[("uid_a", live + 60_000, "early1"),
                   ("uid_b", live + 160_000, "early2")],
        ),
        encoding="utf-8",
    )
    (streamer_dir / "chunk2.xml").write_text(
        chunk_xml(
            live,
            user="主播",
            nodes=[("uid_c", live + 360_000, "late1"),
                   ("uid_d", live + 460_000, "late2")],
        ),
        encoding="utf-8",
    )

    at = _session_app(tmp_path)
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "4"  # full session by default

    # narrow the range to [60, 360]s of the stream and apply it
    # (range_value is now an HH:MM:SS select_slider)
    next(s for s in at.select_slider if s.key == "range_value").set_value((60, 360))
    at.run()
    next(b for b in at.button if b.key == "apply_range").click()
    at.run()

    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    # only t=100 (early2) and t=300 (late1) fall inside [60, 360]
    assert values["弹幕总数"] == "2"
    captions = [c.value for c in at.caption]
    assert any("00:01:00" in c for c in captions)


def test_chunk_mode_analyzes_single_chunk(tmp_path, chunk_xml) -> None:
    import pathlib

    streamer_dir = pathlib.Path(tmp_path) / "HuYa" / "主播"
    streamer_dir.mkdir(parents=True, exist_ok=True)
    live = 1_786_000_000_000
    (streamer_dir / "chunk1.xml").write_text(
        chunk_xml(
            live,
            user="主播",
            nodes=[("u1", live + 1000, "a"), ("u2", live + 2000, "b")],
        ),
        encoding="utf-8",
    )
    (streamer_dir / "chunk2.xml").write_text(
        chunk_xml(
            live,
            user="主播",
            nodes=[("u3", live + 3000, "c")],
        ),
        encoding="utf-8",
    )

    at = AppTest.from_file(str(APP_PATH))
    at.session_state["source_mode"] = "按片段分析"
    at.session_state["chunk_root"] = str(tmp_path)
    at.run()

    assert not at.exception
    # 默认选中该场第一个分片 chunk1.xml -> 2 条弹幕
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "2"
    captions = [c.value for c in at.caption]
    assert any("按片段" in c and "chunk1.xml" in c for c in captions)

    # 切到第二个分片 chunk2.xml -> 1 条弹幕
    next(s for s in at.selectbox if s.key == "sel_chunk").set_value(1)
    at.run()
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["弹幕总数"] == "1"
