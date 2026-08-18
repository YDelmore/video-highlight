# 第三种数据源「按片段分析」— 设计文档

- 日期：2026-08-18
- 范围：Streamlit 分析平台新增第三种数据源模式。侧边栏数据源由两种（单个弹幕文件 / 整场直播·分片聚合）扩展为三种，新增「按片段分析」。
- 用户需求：`现在分析时数据源有两种，帮我再添加一种根据每个片段的分析`。澄清后确定为：**平台→主播→场次→分片** 四级联动，**选中一个分片单独分析**，不复用场次级聚合。

---

## 1. 目标与范围

### 1.1 目标

1. 侧边栏「数据源」radio 三选一：`单个弹幕文件` / `整场直播（分片聚合）` / `按片段分析`。
2. 「按片段分析」下：输入分片根目录，通过 **平台 → 主播 → 直播场次 → 分片** 四级联动选中一个 XML 分片。
3. 选中分片后跑**与「单个弹幕文件」完全相同**的完整指标管线（复用 `load_analysis`，自带缓存），时间轴 **t=0 = 该分片首条弹幕**（不做场次级聚合）。
4. 数据源标签清晰标识：`按片段：{平台}/{主播}/{分片文件名}`。

### 1.2 不在范围内（YAGNI）

- 逐片对比清单 / 概览下钻（用户在澄清时明确选择「选一个片段单独分析」）。
- 分片内的「分析时间区间」子区间选择（区间控件仍属整场模式；单分片时长本身有界）。
- 未归入场次的分片（走 session 级联无法选到；如需要后续可加「未分类」组）。
- 分片解析失败后的行为与单文件模式一致（`st.error`），不新增容错逻辑。

---

## 2. 架构

### 2.1 顶层数据流

```
按片段分析（新 mode）
  └─► discover_sessions(root)              复用：扫描分片、按文件时间+标题分场
        └─► 平台 → 主播 → 场次 级联（共享 helper）
              └─► 分片下拉（session.chunks，按创建时间排序）
                    └─► load_analysis(chunk_path, window, detection)   复用单文件管线
                          └─► 与 FILE_MODE 相同的图表/评分/时间轴渲染
```

### 2.2 设计原则

- **最大化复用**：不加新指标、新管线；片段分析就是「单个弹幕文件」管线套在一个由 session 级联选出的分片路径上。唯一新增逻辑是第 4 级分片下拉与路由分支。
- **级联抽出为共享 helper**：平台→主播→场次的三级联动从 `_session_controls` 中抽出，`_session_controls`（整场模式）与 `_chunk_controls`（片段模式）各自在其上叠加专属控件，避免复制粘贴。
- **缓存复用**：`load_analysis` 按 `(xml_path, window, detection)` 缓存，分片分析天然复用该缓存键。

---

## 3. 模块改动（`src/video_highlight/app.py`）

### 3.1 常量与 `SourceConfig`

```python
CHUNK_MODE = "按片段分析"
SOURCE_MODES = (FILE_MODE, SESSION_MODE, CHUNK_MODE)

@dataclass
class SourceConfig:
    mode: str
    uploaded: object | None
    xml_path: str
    root: str
    session: DanmakuSession | None
    interval: tuple[int, int] = (0, 0)   # 保持在后，避免现有位置构造错位
    chunk_path: str | None = None        # 片段模式选中分片
```

现有位置构造 `SourceConfig(mode, uploaded, xml_input, root, session, interval)`
不受影响（`chunk_path` 默认 `None`）；片段模式用关键字或补位置参数构造。

### 3.2 抽出三级联动 helper

从 `_session_controls` 抽出：

```python
def _session_cascade(root: str) -> DanmakuSession | None:
    """平台 → 主播 → 场次 三级联动，返回选中场次（无分片时 None）。"""
    sessions, _ = _discover_sessions_cached(root)
    if not sessions:
        return None
    # ... 平台 / 主播 / 直播场次 三个 selectbox（沿用现有 key 与回调）
    return chosen[sel_index]
```

- `_session_controls(root)` 改为先调 `_session_cascade`，拿到 session 后再做区间控件（`load_session_records`、`range_value`、`应用区间分析`），返回 `(session, interval)`，对外签名不变。
- 回调 `_reset_streamer_selects` 增加 `pop("sel_chunk")`；`_reset_session_select` 增加 `pop("sel_chunk")`（切换主播/场次时重置分片）。

### 3.3 片段选择控件

```python
def _chunk_controls(root: str) -> tuple[DanmakuSession | None, str | None]:
    session = _session_cascade(root)
    if session is None:
        return None, None
    chunks = session.chunks  # tuple[Path, ...]，按创建时间升序
    chosen = chunks[st.sidebar.selectbox(
        "分片", range(len(chunks)),
        format_func=lambda i: chunks[i].name,
        key="sel_chunk",
        help="选中后单独跑完整分析（t=0 = 该分片首条弹幕），不做场次级聚合。",
    )]
    return session, str(chosen)
```

- 分片下拉显示**文件名**（自带时间戳+标题，如 `2026-08-07-22-24-43-052-解说一下今天比赛.xml`）。
- 不渲染「分析时间区间」控件。

### 3.4 侧边栏路由

```python
if mode == SESSION_MODE:
    root = st.sidebar.text_input("分片根目录", ...)   # 既有
    session, interval = _session_controls(root)
elif mode == CHUNK_MODE:
    root = st.sidebar.text_input("分片根目录", ..., key="chunk_root")
    session, chunk_path = _chunk_controls(root)
else:
    # 既有单文件模式
```

### 3.5 页面主体路由

```python
if cfg.mode == SESSION_MODE:
    ...  # 既有：load_analysis_interval + 整场 source_label + 分片警告
elif cfg.mode == CHUNK_MODE:
    if cfg.chunk_path is None or not Path(cfg.chunk_path).is_file():
        st.error(f"在 {cfg.root} 下未发现任何弹幕分片 XML。"); st.stop()
    analysis = load_analysis(cfg.chunk_path, window_seconds, detection)
    source_label = f"按片段：{cfg.session.platform}/{cfg.session.user_name}/{Path(cfg.chunk_path).name}"
else:
    ...  # 既有单文件模式
```

- 片段模式不展示 `notes.recovered / skipped / unclassified` 警告块（单分片，走 `load_analysis`；解析失败抛 `DanmakuParseError` → 既有 `st.error` 兜底）。

### 3.6 未改动

- `sessions.py` / `parser.py` / `loader.py` / `charts.py` / `scoring.py` / 所有指标模块：零改动。
- `_render_master_timeline`、评分、高潮图谱、明细表：零改动（`analysis` 结构一致）。

---

## 4. 测试（`tests/test_app.py`）

新增用例 `test_chunk_mode_analyzes_single_chunk`：

1. 构造根目录：`HuYa/主播` 下两个分片（复用 `chunk_xml`，同标题、时间接近 → 同一场）。
2. `AppTest` 启动 → `session_state["source_mode"] = "按片段分析"`、`session_state["chunk_root"] = tmp` → `run()`。
3. 断言：无异常；弹幕总数 = 默认选中分片（场次第一个分片）的记录数；存在数据源标签 caption 含 `按片段` 与分片文件名。
4. 切换分片下拉（`sel_chunk` 设为另一分片）→ `run()` → 弹幕总数随之变化。

既有用例不受影响：新 mode 不进 `SESSION_MODE` / 单文件分支；radio 默认 `index=0` 仍是单文件模式。

---

## 5. 验证

1. `uv run pytest` 全量通过（新增用例 + 既有 145 用例）。
2. `uv run streamlit run src/video_highlight/app.py` 手动验证：数据源切到「按片段分析」→ 填 `E:/huya` → 平台→主播→场次→分片，选中后标题、指标、时间轴正常，数据源标签显示「按片段」。
