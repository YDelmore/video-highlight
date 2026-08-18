# 「按片段分析」第三种数据源 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Streamlit 分析平台新增第三种数据源「按片段分析」：平台→主播→场次→分片 四级联动，选中一个分片单独跑完整分析（t=0 = 分片首条弹幕），复用单文件管线。

**Architecture:** 在 `app.py` 内完成，不动 `sessions.py`/指标模块。把「平台→主播→场次」三级联动从 `_session_controls` 抽出为共享 `_session_cascade`；新增 `_chunk_controls` 在其上叠加「分片」下拉；`_sidebar_controls` 与页面主体按 `cfg.mode` 三分支路由。片段分析直接调 `load_analysis(chunk_path, ...)`（自带缓存）。

**Tech Stack:** Streamlit 1.61.1、AppTest、pytest（`uv run pytest`）。

## Global Constraints

- UI 文案全中文（模式名 `按片段分析`、下拉/标签/help 均中文）。
- 测试用 `uv run pytest` 运行；AppTest 通过 `streamlit.testing.v1`。
- `SourceConfig` 字段顺序：`mode, uploaded, xml_path, root, session, interval, chunk_path`——`interval` 必须在 `chunk_path` 之前（现有位置构造 `SourceConfig(mode, uploaded, xml_input, root, session, interval)` 不传 `chunk_path`）。
- 模式名常量与现有 `FILE_MODE = "单个弹幕文件"`、`SESSION_MODE = "整场直播（分片聚合）"` 同级，新增 `CHUNK_MODE = "按片段分析"`。
- 分片下拉 key 固定为 `sel_chunk`；切换主播/场次时用 `st.session_state.pop("sel_chunk", None)` 重置。
- 每个任务以可独立验证的交付物结束。

---

### Task 1: 抽出「平台→主播→场次」级联 helper（行为不变）

**Files:**
- Modify: `src/video_highlight/app.py:358-446`（`_reset_streamer_selects` / `_reset_session_select` / `_session_controls`）

**Interfaces:**
- Consumes: 无新依赖；沿用 `_discover_sessions_cached(root)`。
- Produces:
  - `_session_cascade(root: str) -> DanmakuSession | None` — 渲染平台/主播/场次三个 `st.sidebar.selectbox`，返回选中场次；无任何分片时返回 `None`。
  - `_session_controls(root: str) -> tuple[DanmakuSession | None, tuple[int, int]]` — 对外签名不变（Task 2 的 `_chunk_controls` 依赖 `_session_cascade`）。

本任务是纯重构：行为不变，回归保障 = 既有 `tests/test_app.py::test_session_mode_*` 三个用例。

- [ ] **Step 1: 新增 `_session_cascade`，`_session_controls` 改用它**

在 `_session_controls` 上方新增：

```python
def _session_cascade(root: str) -> DanmakuSession | None:
    """平台 → 主播 → 场次 三级联动，返回选中场次（无分片时 None）。"""
    sessions, _ = _discover_sessions_cached(root)
    if not sessions:
        return None
    platforms = sorted({s.platform for s in sessions})
    platform = st.sidebar.selectbox(
        "平台", platforms, key="sel_platform", on_change=_reset_streamer_selects
    )
    streamers = sorted({s.user_name for s in sessions if s.platform == platform})
    streamer = st.sidebar.selectbox(
        "主播", streamers, key="sel_streamer", on_change=_reset_session_select
    )
    chosen = [
        s for s in sessions if s.platform == platform and s.user_name == streamer
    ]
    labels = [f"{s.label}（{len(s.chunks)}分片）" for s in chosen]
    return chosen[
        st.sidebar.selectbox(
            "直播场次",
            list(range(len(chosen))),
            format_func=lambda i: labels[i],
            key="sel_session",
            help="同一场直播的所有分片会在后台聚合为连续时间轴。"
            "分场按文件创建时间排序，相邻分片的上一文件修改时间与下一文件创建时间"
            "间隔 ≤1 小时且标题相同才视为同一场。",
        )
    ]
```

把 `_session_controls` 开头改为：

```python
def _session_controls(root: str) -> tuple[DanmakuSession | None, tuple[int, int]]:
    """Cascade platform → streamer → session, plus an analysis time-interval.

    Returns ``(session, interval)`` where ``interval`` is the applied in-stream
    ``(start_s, end_s)`` — the whole stream by default, or a user-chosen
    sub-range. The range preview (record count) updates live while dragging;
    the full metric pipeline only re-runs when 「应用区间分析」 is clicked.
    """
    session = _session_cascade(root)
    if session is None:
        return None, (0, 0)
    records, _notes = load_session_records(session)
    if not records:
        return session, (0, 0)
    # 以下 origin / duration / range_value / select_slider / apply_range 逻辑原样保留
```

即：删除 `_session_controls` 里原来的「`_discover_sessions_cached` + 三个 selectbox」片段（第 377–403 行），替换为 `session = _session_cascade(root)` + 两个早期返回。

- [ ] **Step 2: 回调补 `sel_chunk` 清除**

```python
def _reset_streamer_selects() -> None:
    """Changing the platform re-defaults the streamer, session and chunk pickers."""
    st.session_state.pop("sel_streamer", None)
    st.session_state.pop("sel_session", None)
    st.session_state.pop("sel_chunk", None)


def _reset_session_select() -> None:
    """Changing the streamer re-defaults the session and chunk pickers."""
    st.session_state.pop("sel_session", None)
    st.session_state.pop("sel_chunk", None)
```

- [ ] **Step 3: 跑回归测试**

Run: `uv run pytest tests/test_app.py -q`
Expected: PASS（`test_session_mode_aggregates_chunks` / `test_session_mode_cascade_*` / `test_session_mode_time_interval_*` 全部通过，无异常）

- [ ] **Step 4: 提交**

```bash
git add src/video_highlight/app.py
git commit -m "refactor(app): 抽出平台→主播→场次三级联动为 _session_cascade"
```

---

### Task 2: 新增「按片段分析」模式（常量 / 字段 / 控件 / 路由 / 测试）

**Files:**
- Modify: `src/video_highlight/app.py`（常量区、`SourceConfig`、`_sidebar_controls`、页面主体路由）
- Test: `tests/test_app.py`（新增 `test_chunk_mode_analyzes_single_chunk`）

**Interfaces:**
- Consumes: Task 1 的 `_session_cascade(root) -> DanmakuSession | None`；`load_analysis(xml_path, window_seconds, detection)`（已有）。
- Produces:
  - `CHUNK_MODE = "按片段分析"`、`SOURCE_MODES = (FILE_MODE, SESSION_MODE, CHUNK_MODE)`。
  - `SourceConfig.chunk_path: str | None = None`（字段在 `interval` 之后）。
  - `_chunk_controls(root: str) -> tuple[DanmakuSession | None, str | None]` — 返回 `(场次, 分片绝对路径)`。
  - `_sidebar_controls` 返回的 `SourceConfig` 带 `chunk_path`。
  - 页面主体对 `cfg.mode == CHUNK_MODE` 分支渲染完整分析。

- [ ] **Step 1: 写失败测试**

在 `tests/test_app.py` 的 session-mode 区段末尾（`test_session_mode_time_interval_filters_records` 之后）新增：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_app.py::test_chunk_mode_analyzes_single_chunk -v`
Expected: FAIL（`CHUNK_MODE` 尚未定义，或 `source_mode` 取值不在 `SOURCE_MODES` 中，radio 报错）

- [ ] **Step 3: 常量与 `SourceConfig` 字段**

```python
FILE_MODE = "单个弹幕文件"
SESSION_MODE = "整场直播（分片聚合）"
CHUNK_MODE = "按片段分析"
SOURCE_MODES = (FILE_MODE, SESSION_MODE, CHUNK_MODE)
```

```python
@dataclass
class SourceConfig:
    """What the sidebar says about where the danmaku comes from."""

    mode: str
    uploaded: object | None
    xml_path: str
    root: str
    session: DanmakuSession | None
    interval: tuple[int, int] = (0, 0)
    chunk_path: str | None = None  # 按片段模式选中的分片绝对路径
```

- [ ] **Step 4: 新增 `_chunk_controls`**

在 `_session_controls` 之后新增：

```python
def _chunk_controls(root: str) -> tuple[DanmakuSession | None, str | None]:
    """平台 → 主播 → 场次 → 分片 四级联动。

    Returns ``(session, chunk_path)`` where ``chunk_path`` is the absolute
    path of the selected chunk; ``(None, None)`` when the root has no chunks.
    The chunk is analysed alone (t=0 = its first danmaku), not aggregated.
    """
    session = _session_cascade(root)
    if session is None:
        return None, None
    chunks = session.chunks  # tuple[Path, ...]，按创建时间升序
    picked = st.sidebar.selectbox(
        "分片",
        list(range(len(chunks))),
        format_func=lambda i: chunks[i].name,
        key="sel_chunk",
        help="选中后单独跑完整分析（t=0 = 该分片首条弹幕），不做场次级聚合。",
    )
    return session, str(chunks[picked])
```

- [ ] **Step 5: `_sidebar_controls` 三分支**

在 `_sidebar_controls` 中：

```python
    mode = st.sidebar.radio(
        "数据源",
        SOURCE_MODES,
        index=0,
        key="source_mode",
        help="整场直播模式：扫描分片根目录，把同一场直播的分片在后台聚合后再分析；"
        "按片段模式：选中一个分片单独分析。",
    )
    uploaded = None
    xml_input = str(DEFAULT_XML)
    root = DEFAULT_SESSION_ROOT
    session: DanmakuSession | None = None
    interval = (0, 0)
    chunk_path: str | None = None
    if mode == SESSION_MODE:
        root = st.sidebar.text_input(
            "分片根目录",
            value=DEFAULT_SESSION_ROOT,
            key="session_root",
            help="目录结构：平台 → 主播 → 分片 xml；按 metadata 的 live_start_time 聚合同一场直播。",
        )
        session, interval = _session_controls(root)
    elif mode == CHUNK_MODE:
        root = st.sidebar.text_input(
            "分片根目录",
            value=DEFAULT_SESSION_ROOT,
            key="chunk_root",
            help="目录结构：平台 → 主播 → 分片 xml。选中的分片单独分析。",
        )
        session, chunk_path = _chunk_controls(root)
    else:
        uploaded = st.sidebar.file_uploader(
            "上传弹幕 XML 文件",
            type=["xml"],
            key="uploaded_xml",
            help="直接上传虎牙风格弹幕 XML；上传后优先使用上传的文件。",
        )
        xml_input = st.sidebar.text_input(
            "或填写服务器上的 XML 路径", value=str(DEFAULT_XML), key="xml_path"
        )
```

返回值改为：

```python
    return (
        SourceConfig(mode, uploaded, xml_input, root, session, interval, chunk_path),
        window_seconds,
        weights,
        thresholds,
        detection,
    )
```

- [ ] **Step 6: 页面主体三分支**

把主体路由从 `if cfg.mode == SESSION_MODE: ... else:` 改为三分支。在 `else:` 之前插入 `elif`：

```python
    elif cfg.mode == CHUNK_MODE:
        if cfg.chunk_path is None or not Path(cfg.chunk_path).is_file():
            st.error(f"在 {cfg.root} 下未发现任何弹幕分片 XML。")
            st.stop()
        analysis = load_analysis(cfg.chunk_path, window_seconds, detection)
        source_label = (
            f"按片段：{cfg.session.platform}/{cfg.session.user_name}/"
            f"{Path(cfg.chunk_path).name}"
        )
```

注意：`if analysis.n_records == 0:` 警告、评分、图表、时间轴等后续代码对所有模式通用，无需改动；`notes.recovered/skipped/unclassified` 警告块仍包在 `if cfg.mode == SESSION_MODE:` 内，片段模式自动跳过。

- [ ] **Step 7: 跑测试**

Run: `uv run pytest tests/test_app.py::test_chunk_mode_analyzes_single_chunk -v`
Expected: PASS（`弹幕总数` 在切分片前后分别为 "2" 与 "1"；caption 含「按片段」与 `chunk1.xml`）

- [ ] **Step 8: 全量回归**

Run: `uv run pytest -q`
Expected: 全绿（既有 145 + 新增 1 = 146 passed）

- [ ] **Step 9: 提交**

```bash
git add src/video_highlight/app.py tests/test_app.py
git commit -m "feat(app): 新增第三种数据源「按片段分析」（平台→主播→场次→分片）"
```

---

## 验证清单（计划完成标准）

1. `uv run pytest` 全绿（146 passed）。
2. 手动：`uv run streamlit run src/video_highlight/app.py` → 数据源切「按片段分析」→ 填 `E:/huya` → 平台→主播→场次→分片；选中分片后标题/指标/时间轴正常，数据源标签显示「按片段：…/分片文件名」；切换分片会重新计算。
3. `README.md` 的「分析平台」章节补一条「按片段分析」说明（可选，随 Task 2 一并提交或单独 commit）。
