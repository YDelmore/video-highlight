# 弹幕热度与规模分析（指标 1–2）— 设计文档

- 日期：2026-08-09
- 范围：第一轮扫描。实现指标 **1（弹幕密度）** 与 **2（爆发速率）**，构建可被后续指标 3–4 直接复用的数据层。
- 数据输入：`docs/danmaku.xml`（虎牙"5点面试"直播间，500 行测试样本）
- 设计基线：`docs/分析策略.md` 中关于指标 1、2 的全部公式与阈值

---

## 1. 目标与范围

### 1.1 本设计要达成的目标

1. 用户在终端运行一条命令即可对一份虎牙弹幕 XML 完成 **指标 1 + 指标 2** 的完整计算，并把候选高潮区间打印出来。
2. 输出形态：控制台报告 + 可选的 matplotlib 图（matplotlib 未安装时优雅降级）。
3. 模块与数据结构为后续 **指标 3（沉默用户激活率）** 与 **指标 4（弹幕长度分布）** 预留接口，第二轮不再返工。

### 1.2 不在本设计范围内

- 指标 3、4 本身的实现（数据层先就位，逻辑留待下一轮 spec）。
- 假峰过滤（抽奖/红包环节识别）— 文档提及，预留 hook。
- 大模型接口、Web 服务、第三方存储后端。
- 多文件批量处理（命令行只接受单个 XML 路径，扩展时再考虑）。

---

## 2. 架构

### 2.1 顶层数据流

```
XML 源 (danmaku.xml)
  └─► [parser]                      ElementTree 解析 <d> 节点
        └─► list[Danmaku]           dataclass, 字段 = (uid, ts_ms, text)
              └─► [loader]          DataFrame[t(s), uid, text, length]
                    │
                    ├─► [metrics.density]   → Series D[t]  （指标 1）
                    │       └─► [metrics.burst]    → Series S[t], S_rel[t]  （指标 2）
                    │
                    └─► [highlights]        从 D[t] 切分候选区间
                          └─► [report]       控制台 + JSON + 可选 matplotlib
```

### 2.2 设计原则

- **解析—装载—指标—报告**四层清晰分离。每一层只依赖下一层的输入类型，不互相 import。
- **指标模块独立**：`metrics.density` 和 `metrics.burst` 是纯函数，输入约定明确，便于单测。后续指标 3/4 也是平级的同级模块，不会改这两个。
- **复用友好**：所有后续轮次共用的中间数据（uid 列、text、length）由 `loader` 一次性全部就位。第一轮指标 1+2 用不到，但"先空跑不报错"，第二轮直接消费。
- **基线 = 策略文档**：所有阈值（窗口大小、平滑系数、σ 倍数）直接来自策略文档，不引入自创参数。

---

## 3. 模块设计

### 3.1 `video_highlight/parser.py`

```python
@dataclass(frozen=True)
class Danmaku:
    uid: str        # 字符串，避免 64 位整数溢出
    ts_ms: int      # 原始毫秒时间戳
    text: str       # 弹幕文本

def parse_xml(path: str | Path) -> list[Danmaku]: ...
```

- 使用 `xml.etree.ElementTree.iterparse`，遇到 `</d>` 立即 yield 释放内存。
- 不解析 `p=...` 字段（包含颜色、字号等不影响指标的样式信息），仅提取 `uid` 属性、`timestamp` 属性、文本节点内容。
- 异常：XML 解析错误时抛出 `DanmakuParseError` 子类异常，并在消息中包含文件路径。

### 3.2 `video_highlight/loader.py`

```python
def to_dataframe(
    danmaku: list[Danmaku],
    *,
    live_start_ms: int | None = None,
) -> pd.DataFrame:
    """返回列：t (相对秒, float), uid (str), text (str), length (int)
    若 live_start_ms=None，则以最小的 ts_ms 作为基准 0。
    """
```

- 时间基线：相对秒 `t = (ts_ms - live_start_ms) / 1000.0`，与策略文档"时间窗口"概念一致。
- 提前计算 `length = len(text)`（字符数，非字节数）— 第二轮指标 4 不重算。
- 不去重、不洗文本。第一轮指标 1+2 不用文本内容，保留原样。
- 不消费任何全局 mutable 状态。函数幂等。

### 3.3 `video_highlight/metrics/_window.py`（内部辅助）

```python
def rolling_count(series_by_t: pd.Series, window_seconds: int) -> pd.Series:
    """对按秒索引的 Series 计算滑窗计数。
    对应策略文档指标 1 的 D(t) = count(弹幕时间戳 ∈ [t, t+W))。
    """
```

- 实现：使用 pandas 的 `.rolling(f'{W}s').sum()`，前提是 index 是 `DatetimeIndex`（秒精度）。
- 内部把 `t` 列转为 `pd.DatetimeIndex`（epoch 秒为单位），函数对外承诺"index 仍是 float 秒级"，因此后续模块可以按 t 直接取数。
- 抽成内部模块是为了让未来指标（基尼、用户重合度）共享相同的滑窗语义。

> **契约约定**：本项目所有 metric 模块的输入 DataFrame，索引列 `t` 永远是相对秒级 `float`（与控制台可打印的秒数一致）。`_window.py` 内部如需 `DatetimeIndex` 来驱动 pandas rolling，会在调用边界处做完转换再恢复 `float` 索引，对外不可见。

### 3.4 `video_highlight/metrics/density.py` （指标 1）

```python
WINDOW_SECONDS = 10

@dataclass
class DensityResult:
    D: pd.Series                 # index = t（秒），值 = D(t)
    mu: float                    # 整场均值
    sigma: float                 # 整场标准差
    n_total: int                 # 弹幕总数
    duration_seconds: float      # 时间跨度

def compute(df: pd.DataFrame, *, window_seconds: int = WINDOW_SECONDS) -> DensityResult: ...
```

- 算法：
  1. 用 `loader.to_dataframe` 的结果，按 `t` 取 1 秒粒度的事件序列。
  2. 以 `event_series[t] = 1`（每秒 1 条或多条分别累积）建序列。
  3. 滑窗求和：`D = event_series.rolling(window_seconds).sum()`。
  4. 计算 `μ, σ`（基于非 NaN 的 D 值）。
- 输出边界：D 序列可能在前 `window_seconds-1` 秒为 NaN，调用方按 NaN 跳过。

### 3.5 `video_highlight/metrics/burst.py` （指标 2）

```python
@dataclass
class BurstResult:
    S: pd.Series       # 一阶差分（平滑后）
    S_rel: pd.Series   # 相对爆发速率 D(t) / max(D(t-1), 1)
    mu_S: float
    sigma_S: float

def compute(density: DensityResult) -> BurstResult: ...
```

- 算法严格按策略文档：
  1. `D_smooth = density.D.rolling(3, center=True, min_periods=1).mean()`
  2. `S = D_smooth.diff()`（自动得 1 秒步长差分）
  3. `S_rel = density.D / density.D.shift(1).clip(lower=1)`
- `μ_S, σ_S`：仅基于 `S` 的非 NaN 值。

### 3.6 `video_highlight/highlights.py`

```python
@dataclass
class HighlightCandidate:
    t_start: float        # 区间起点（秒）
    t_end: float          # 区间终点（秒）
    peak_t: float         # 区间内密度最大值对应时刻
    peak_density: float   # 密度峰值
    level: str            # 'candidate' (>μ+2σ) | 'strong' (>μ+3σ)

def find_candidates(
    density: DensityResult,
    *,
    strong_sigma: float = 3.0,
    merge_gap_seconds: float = 30.0,
) -> list[HighlightCandidate]: ...
```

- 算法：
  1. `mask = D > μ + 2σ`，`strong_mask = D > μ + 3σ`。
  2. 在 mask 为 True 的连续区间内，每段记录 `[t_start, t_end]`。若两段间隔 < `merge_gap_seconds` 且区间内 user_overlap 暂未实现，则保守地合并成一段（合并的 level 取两段更高者）。
  3. 每段内取 `D.idxmax()` 作为 `peak_t`。
  4. 候选区间按 `peak_t` 排序输出。
- 在这一轮"合并"逻辑只靠 `merge_gap_seconds`，不结合用户重合度（那是指标 6，留给后续）。

### 3.7 `video_highlight/report.py`

```python
def console_print(
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    *,
    danmaku_count: int,
    duration_seconds: float,
    stream=sys.stdout,
) -> None: ...

def plot(
    density: DensityResult,
    burst: BurstResult,
    highlights: list[HighlightCandidate],
    output_path: str | Path,
) -> bool:
    """返回 True 表示成功生成；matplotlib 不可用返回 False。"""
```

- console_print 输出严格按 section 顺序：概览 → 指标 1 → 指标 2 → 候选区间表。
- plot 输出 2 行 2 列：
  - 子图 1：D(t) 曲线 + μ+2σ / μ+3σ 阈值线 + 候选区间阴影。
  - 子图 2：S(t) 曲线 + 3σ 阈值线。
  - 子图 3：S_rel(t) 曲线。
  - 子图 4：弹幕事件散点图（每个 t 一根竖线），便于直观看到原始分布。
- 所有图表用统一的 `rcParams`（背景白、字号 11、color 用默认 tab10）。

### 3.8 `video_highlight/__main__.py`

```python
import argparse

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("xml_path", type=Path)
    parser.add_argument("--plot", type=Path, default=None, help="保存图表 PNG 路径")
    args = parser.parse_args(argv)

    danmaku = parse_xml(args.xml_path)
    df = to_dataframe(danmaku)
    density = compute_density(df)
    burst = compute_burst(density)
    highlights = find_candidates(density)
    console_print(density, burst, highlights, ...)
    if args.plot:
        ok = plot(density, burst, highlights, args.plot)
        if not ok: print("[WARN] matplotlib 不可用，跳过图表生成", file=sys.stderr)
    return 0
```

- 入口也通过 pyproject 的 `video-highlight = "video_highlight:main"` 暴露（已配置）。

---

## 4. 数据契约与时间轴约定

| 项 | 值 |
|----|---|
| `t`（相对秒） | `(ts_ms - live_start_ms) / 1000`；`live_start_ms=None` 时取 `min(ts_ms)` |
| 滑窗 | W=10s，步长 1s |
| 平滑核 | 3 点中心移动平均 |
| 高潮阈值 | 候选 D > μ+2σ；强候选 D > μ+3σ |
| 爆发阈值 | 候选 S > 3·σ_S |
| 合并间隔 | 同段内回落 ≤ 30s 视为同一段 |
| 入场期 | 0–300s（不应用于指标 3+；此处预留给后续轮） |

---

## 5. 输出契约

控制台输出顺序固定：

```
=== 分析概览 ===
直播: <user_name> / 房间 <room_id>
弹幕总数: N
时间跨度: T 秒 (X 分钟)

=== 指标1: 弹幕密度 (W=10s) ===
均值: μ / 标准差: σ / 最大值: max(D) / 峰时 t_peak
[若 baseline 不可靠: WARN 提示]
候选区间 (D > μ+2σ): K 个
  # | t_start | t_end | duration(s) | peak_D | level

=== 指标2: 爆发速率 ===
S 均值 / S 标准差 / 最大 S / 最大 S_rel (at t)
爆发候选 (S > 3σ_S): M 个
  # | t | S | S_rel

=== 高潮候选区间（合并后） ===
（同指标 1 的列表，但去掉 level 字段的"candidate"列）

=== 图表：已保存到 <path> === 或 === 图表：跳过（matplotlib 不可用）===
```

---

## 6. 错误处理与边界条件

| 场景 | 期望行为 |
|------|---------|
| XML 文件不存在 | 抛出 `FileNotFoundError`，消息含原路径 |
| XML 解析错误 | 抛出 `DanmakuParseError`，消息含路径与出错行号 |
| `<d>` 节点缺失必要属性 | 跳过该节点，控制台 `WARN: skipped N malformed <d>` |
| 时长 < 60 秒 | μ/σ 不可靠；console 打印 `[WARN] baseline unreliable for short streams`，但仍输出全部结果 |
| 候选区间为 0 个 | 打印提示 `未检出候选区间，可下调阈值至 1.5σ`，候选表为空（不报错） |
| matplotlib 未安装 | `plot` 返回 False，`__main__` 打印 WARN，不影响退出码 |
| 数据为空（0 条） | 在概览里打印 "无有效弹幕"，提前 exit 0 |

---

## 7. 测试策略

### 7.1 测试框架
- `pytest`（添加为 dev 依赖）。

### 7.2 测试层级

| 层级 | 测试 | 验证 |
|------|------|------|
| 单元 | `tests/test_parser.py` | 解析正确 uid/ts/text；malformed 节点安全跳过 |
| 单元 | `tests/test_loader.py` | 相对时间计算；length 字段正确 |
| 单元 | `tests/test_density.py` | 滑窗边界；μ/σ 与手算一致 |
| 单元 | `tests/test_burst.py` | 3 点平滑；差分；S_rel 公式（含 clip） |
| 单元 | `tests/test_highlights.py` | 给定手工 D，验证段切分 + 强候选标记 + 合并 |
| 集成 | `tests/test_main.py` | 跑 `danmaku.xml`，返回 exit 0，输出含 "指标1" 与 "指标2" 段标题 |

### 7.3 手工验证样例（测试用例里直接 inline）

构造 `{t:0, t:1, t:1, t:1, t:20}`（5 条弹幕，4 条聚集在 t=1）：

- 指标 1 在 W=10s 下 D(0)=1, D(1)=4, D(2)=3, ..., D(10)=1 等，可用眼睛校验。
- 指标 2 在 t=1 处应有极大正 S，t=11 附近应有较大负 S。
- highlights：在 t=1 附近应检出 1 个候选段，peak_t=1, peak_D=4。

把这个样例固化在 `tests/fixtures/synthetic_density.py` 中。

---

## 8. 依赖与依赖管理

新增依赖（写入 `pyproject.toml` 的 `dependencies`）：

- `pandas>=2.0`
- `numpy>=1.24`

dev 依赖（写入 `[dependency-groups].dev` 或 `[project.optional-dependencies].test`）：

- `pytest>=7.0`
- `matplotlib>=3.7`（运行时可选，缺失时优雅降级）

`pyproject.toml` 已是 uv 风格（`uv_build`），保持一致。

---

## 9. 文件清单（提交后状态）

```
video-highlight/
├── pyproject.toml                # 修改：加 pandas/numpy/pytest；matplotlib 设为 optional
├── src/video_highlight/
│   ├── __init__.py               # 导出 main()
│   ├── __main__.py               # CLI 入口（新增）
│   ├── parser.py                 # XML 解析（新增）
│   ├── loader.py                 # 转 DataFrame（新增，prelength 计算）
│   ├── exceptions.py             # DanmakuParseError（新增）
│   ├── highlights.py             # 候选区间切分（新增）
│   ├── report.py                 # 控制台 + matplotlib（新增）
│   └── metrics/
│       ├── __init__.py           # 模块占位
│       ├── _window.py            # 滑窗辅助（新增）
│       ├── density.py            # 指标 1（新增）
│       └── burst.py              # 指标 2（新增）
├── tests/
│   ├── __init__.py               # 空
│   ├── test_parser.py
│   ├── test_loader.py
│   ├── test_density.py
│   ├── test_burst.py
│   ├── test_highlights.py
│   ├── test_main.py
│   └── fixtures/
│       └── synthetic_density.py
└── docs/superpowers/specs/
    └── 2026-08-09-danmaku-density-burst-design.md   # 本文件
```

---

## 10. 复用接口与下一轮扩展点

- `loader.to_dataframe` 已经返回 `uid, text, length` 三列，**第二轮直接复用**，无需触碰 parser 层。
- `metrics/_window.py` 是未来指标 6（用户重合度）、指标 9（情感密度）的滑窗公共代码。
- `highlights.find_candidates` 第一轮只用时间合并；下一轮加"用户重合度>50% 才合并"扩展时，新增可选参数 `user_overlap_check: Callable[[float, float], bool]`，第一轮的调用点不破坏。
- `report.plot` 已经预留 subplot 轴对象；下一轮新指标可作为子图追加，不重新搭画布。

---

## 11. 完成定义（Definition of Done）

- [ ] `uv sync` 安装依赖无报错
- [ ] `uv run pytest` 全部用例通过
- [ ] `uv run video-highlight docs/danmaku.xml` 输出符合本设计第 5 节
- [ ] `uv run video-highlight docs/danmaku.xml --plot /tmp/h.png` 生成 PNG（matplotlib 可用时）
- [ ] 控制台摘要里能看到 `指标1`、`指标2`、候选区间三个段
- [ ] 不在策略文档中引入任何自创阈值
- [ ] 不修改任何已通过的代码路径（仅新增文件 + pyproject 新增依赖）
- [ ] spec 自审通过：无占位、无矛盾、无歧义、范围聚焦
