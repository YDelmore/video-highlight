# 弹幕指标 5-8 设计 — 用户行为与参与模式

- 日期：2026-08-09
- 范围：在已完成指标 1-4 的基础上，新增**指标 5（发言集中度）、6（用户重合度）、7（用户生命周期）、8（回锅用户比例）**，并切换主数据集。
- 设计基线：`docs/分析策略.md` 指标 5-8 公式与阈值；既有网格/窗口语义。
- 主数据集：`docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml`（6286 条弹幕，约 1796.6s ≈ 30 分钟，1896 去重用户，检出一个强候选窗口 [687,734]）。

---

## 0. 数据集切换（用户已确认）

- CLI 无参默认 `xml_path` 改为新文件 `docs/2026-08-07-22-24-43-052-解说一下今天比赛.xml`。
- 集成测试 `tests/test_main.py` 改用新文件断言。
- 旧 `docs/danmaku.xml` 仍可通过显式传参使用；单元测试不依赖具体 XML。
- 指标 7/8 在新数据上 `s ≈ 1`（时长 ≈ 参考值 1800s），以策略原值工作；自适应缩放保留，供未来短流使用。

---

## 1. 架构

```
loader.to_dataframe → DataFrame (t, uid, text, length)
  ├─► metrics.concentration.compute → ConcentrationResult   (指标5, 系列)
  ├─► metrics.overlap.compute        → OverlapResult        (指标6, 系列)
  ├─► metrics.lifecycle.compute      → LifecycleResult      (指标7, 每窗口)
  └─► metrics.returning.compute      → ReturningResult      (指标8, 每窗口)
          │                                  │
          ▼                                  ▼
   report.console_print / report.plot (4 新 section / 图 3×3)
```

- 网格语义与既有指标一致：1 秒整数网格、尾随右开窗口 `[t-W, t)`、`t<W` 为 NaN。
- 指标 7/8 需要候选窗口（`highlights` 列表）作为输入；`compute(df, highlights, ...)`。

---

## 2. 共享自适应时间偏移（`metrics/_offsets.py`）

```python
def adaptive_scale(duration_seconds: float, reference_seconds: float = 1800.0) -> float:
    """s = min(1, duration/reference). Offsets are multiplied by s."""
    return min(1.0, duration_seconds / reference_seconds)
```

- 参考 1800s = 30 分钟。`duration >= 1800s` → s=1（策略原值）；更短按比例收缩。
- 与指标 3 观测期（`min(300, duration*0.25)`）同样解决"短流偏移超界"问题，此处统一为比例缩放。

---

## 3. 指标 5：发言集中度（Top-3 占比）— `metrics/concentration.py`

### 算法

```
窗口 [t-W, t)，W=10s：
  per-uid 发言计数
  Top3 之和 / 窗口总弹幕数
  窗口总弹幕数 == 0 → NaN
```

- 采用工程简化版 Top-3 占比（策略文档推荐，与完整基尼 r>0.9，成本低）。窗口内用户 < 3 时 Top3 = 全部用户，比值 = 1.0（数学上正确：少人发言即高集中）。

### 输出

```python
@dataclass(frozen=True)
class ConcentrationResult:
    concentration: pd.Series   # 1s 网格，float，NaN 处无效

def compute(df, *, window_seconds=10) -> ConcentrationResult
```

### 阈值参考（报告展示）

Top3 占比：<20% 群体共鸣 / 20-40% 正常 / 40-60% 明显刷屏 / >60% 少数人垄断。

---

## 4. 指标 6：用户重合度（Jaccard）— `metrics/overlap.py`

### 算法

```
U(t) = 窗口 [t-30s, t) 内发言 uid 集合
重合度(t) = |U(t) ∩ U(t-30)| / |U(t) ∪ U(t-30)|
t < 2×window_seconds   → NaN（前窗未满）
U(t) 与 U(t-30) 皆空   → NaN
一个空另一非空          → 0
```

- 1 秒网格滑动；窗口 30s（策略明确）；比较"当前窗口"与"30s 前的窗口"。

### 输出

```python
@dataclass(frozen=True)
class OverlapResult:
    overlap: pd.Series

def compute(df, *, window_seconds=30) -> OverlapResult
```

### 阈值参考

重合度：>60% 同一事件延续 / 30-60% 正常过渡 / <30% 新事件开始。

---

## 5. 指标 7：用户生命周期聚类 — `metrics/lifecycle.py`

### 算法（每候选窗口）

```
设候选窗口 [t_start, t_end]，缩放 s = adaptive_scale(duration)：
  A = 300s·s   (持续用户前后缓冲 5min)
  B = 120s·s   (转化用户前窗 2min)
  C = 600s·s   (转化用户后窗 10min)

对每个 uid 的全局首次/末次发言 (first, last)：
  瞬时用户 = first ∈ [t_start, t_end] ∧ last ∈ [t_start, t_end]
  持续用户 = first < t_start - A ∧ last > t_end + A
  转化用户 = first ∈ [t_start - B, t_end] ∧ last > t_end + C
```

- 三类互斥判定按序；不满足任一类的用户不计入三类（属"其他"）。
- 输出每窗口计数 + 占比（占比 = 该类别数 / 窗口内去重用户数）。
- 候选窗口贴近流尾时，持续/转化可能为 0（无可观察的"之后仍在"），如实呈现。

### 输出

```python
@dataclass(frozen=True)
class LifecycleWindow:
    t_start: float
    t_end: float
    instant: int
    persistent: int
    converted: int
    total_users: int   # 窗口内去重用户数
    scale: float

@dataclass(frozen=True)
class LifecycleResult:
    windows: list[LifecycleWindow]

def compute(df, highlights, *, ...) -> LifecycleResult
```

---

## 6. 指标 8：回锅用户比例 — `metrics/returning.py`

### 算法（每候选窗口）

```
设候选窗口 [t_start, t_end]，以 t_start 为参考时刻，s = adaptive_scale(duration)：
  早期期   = [0, 1800s·s)          # "证明来过"
  静默窗   = [t_start - 1200s·s, t_start - 120s·s)   # "证明离开过"
  回锅用户 = 早期期有发言 ∧ 静默窗零发言 ∧ 窗口内又发言
  比例     = 回锅用户数 / 窗口内去重用户数
```

- 边界：静默窗下界 < 0 时截断为 0；早期期与静默窗重叠（超短流）时"来过且离开"不可同时满足 → 比例 0，报告标注"流过短无法观察回锅"。
- 输出每窗口回锅数、总用户数、比例。

### 输出

```python
@dataclass(frozen=True)
class ReturningWindow:
    t_start: float
    t_end: float
    returning_count: int
    total_users: int
    ratio: float      # NaN 若 total_users == 0

@dataclass(frozen=True)
class ReturningResult:
    windows: list[ReturningWindow]

def compute(df, highlights, *, ...) -> ReturningResult
```

### 阈值参考

回锅比例：<5% 正常 / 5-15% 明显召回 / >15% 极强召回。

---

## 7. 输出集成

### 7.1 控制台（`report.console_print` 新增 4 段）

位于指标 4 之后、候选区间之前：

```
=== 指标5: 发言集中度 (Top-3, W=10s) ===
均值 / 峰值 at t / 候选窗口内均值
=== 指标6: 用户重合度 (30s窗) ===
均值 / 重合度跌破30%的窗口数
```

位于候选区间之后：

```
=== 指标7: 用户生命周期 (缩放 s=1.000) ===
候选#1 [687,734]: 瞬时 X (xx%) / 持续 Y (yy%) / 转化 Z (zz%) / 窗口用户 N
=== 指标8: 回锅用户比例 (缩放 s=1.000) ===
候选#1 [687,734]: 回锅 R / 总数 N → rr.r%
```

### 7.2 图（`report.plot` 2×3 → 3×3）

| 位置 | 内容 |
|------|------|
| (0,0) | 密度 D(t) + 阈值 |
| (0,1) | 爆发速率 S(t) |
| (0,2) | 激活率(t) |
| (1,0) | S_rel(t) |
| (1,1) | 短/长占比 |
| (1,2) | 密度柱状视图（保持 3+4 布局不变） |
| (2,0) | 集中度(t) |
| (2,1) | 重合度(t) + 30% 参考线 |
| (2,2) | 候选窗口视图（D(t) 曲线 + axvspan 标出 highlight 区间） |

- 指标 7/8 为每窗口分类，不进图（控制台展示）。

---

## 8. 错误与边界

| 场景 | 行为 |
|------|------|
| 窗口空（集中度/重合度分母） | NaN |
| `t < 60s`（重合度） | NaN |
| 流过短、静默窗无法观察回锅 | 指标8 比例 0 + 标注 |
| 无候选窗口 | 指标7/8 空列表；section 提示"无候选窗口" |
| DataFrame 空 | 各 Result 空，不崩溃 |

---

## 9. 测试策略（TDD）

| 测试文件 | 覆盖 |
|---------|------|
| `tests/test_concentration.py` | Top3 手算；空窗 NaN；<3 用户窗口→1.0 |
| `tests/test_overlap.py` | Jaccard 手算；t<60 NaN；双空 NaN；一空→0 |
| `tests/test_lifecycle.py` | 三类分类手算；s=1 长流；s<1 短流；流尾窗口退化 |
| `tests/test_returning.py` | 回锅判定；静默窗越界截断；短流退化 |
| `tests/test_report.py` | 4 新 section；图 3×3 结构 |
| `tests/test_main.py` | 切换新文件；集成冒烟含新 section |

---

## 10. 文件清单

```
src/video_highlight/
├── metrics/
│   ├── _offsets.py          # 新增：adaptive_scale
│   ├── concentration.py     # 新增：指标5
│   ├── overlap.py           # 新增：指标6
│   ├── lifecycle.py         # 新增：指标7
│   └── returning.py         # 新增：指标8
├── report.py                # 修改：4 新 section + 图 3×3
└── __main__.py              # 修改：串联 + 默认文件切换
tests/
├── test_concentration.py    # 新增
├── test_overlap.py          # 新增
├── test_lifecycle.py        # 新增
├── test_returning.py        # 新增
├── test_report.py           # 修改
└── test_main.py             # 修改（新默认文件 + 断言）
```

不修改：parser / loader / _window / density / burst / highlights / activation / length_dist。

---

## 11. 完成定义（DoD）

- [ ] `uv run pytest` 全量通过
- [ ] CLI 无参运行新文件：输出含 指标5/6/7/8 四个新 section，且指标7/8 展示候选窗口 [687,734] 的生命周期与回锅数据
- [ ] `--plot` 生成 3×3 九子图 PNG
- [ ] 指标5 集中度序列有效点 ∈ [0,1]，空窗 NaN
- [ ] 指标6 重合度序列有效点 ∈ [0,1]，边界 NaN 正确
- [ ] 指标7/8 每窗口计数、占比、缩放 s 与手算一致
- [ ] 不修改 parser/loader/_window/density/burst/highlights/activation/length_dist
- [ ] 无占位、无自创阈值（阈值全部来自策略文档）
