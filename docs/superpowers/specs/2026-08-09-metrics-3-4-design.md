# 弹幕指标 3+4 设计 — 沉默用户激活率 & 弹幕长度分布

- 日期：2026-08-09
- 范围：在已完成指标 1+2（密度/爆发速率）的基础上，新增**指标 3（沉默用户激活率）**与**指标 4（弹幕长度分布）**，集成进现有报告与图表。
- 设计基线：`docs/分析策略.md` 指标 3、4 公式与阈值；`docs/superpowers/specs/2026-08-09-danmaku-density-burst-design.md` 中已落地的数据层与网格语义。
- 输入：`loader.to_dataframe` 产出的 DataFrame（列 `t, uid, text, length`），其中 `uid` 与 `length` 在指标 1+2 轮已预计算就位。

---

## 1. 目标与范围

### 1.1 本设计要达成的目标

1. 计算指标 3 的**激活率时间序列**：出圈程度（潜水用户被炸出）。
2. 计算指标 4 的**短/中/长弹幕占比时间序列**：情绪宣泄 vs 深度讨论。
3. 两条序列与指标 1+2 同网格（1 秒、尾随窗口 W=10s），集成进现有控制台报告与 2×3 图表。
4. 复用既有数据层与 `_window` 语义，**不修改任何已通过代码路径**（仅 `report.py`、`__main__.py` 增补调用点）。

### 1.2 不在本设计范围内

- 高潮"类型判定"（密度高+激活率高=真高潮等组合规则）— 属第五阶段，后续再做。
- 假峰过滤、大模型接口、指标 5+ 的任何实现。
- 对候选区间做激活率/长度分布的重排或打分。

---

## 2. 架构

### 2.1 数据流

```
loader.to_dataframe → DataFrame (t, uid, text, length)
  ├─► metrics.activation.compute  → ActivationResult
  └─► metrics.length_dist.compute → LengthDistResult
          │
          ▼
report.console_print / report.plot   （新增 section / 扩为 2×3）
```

### 2.2 网格与窗口约定（与指标 1+2 完全一致）

- 时间轴：自直播开始的相对秒，1 秒整数网格。
- 窗口：**尾随** `[t-W, t)`，W=10s，右开。
- 网格上 `t < W` 的前段为 NaN（窗口未填满）。
- 指标 3 额外在 `t < 观测期` 为 NaN（见 §3）。

---

## 3. 指标 3：沉默用户激活率（`metrics/activation.py`）

### 3.1 自适应观测期

```
观测期 O = min(300, 流时长 × 0.25)
流时长 = t.max() - t.min()
```

- 长流（≥20 分钟）：O=300s，即策略文档标准的 5 分钟。
- 短流：O 自动缩短为流时长的 25%，保证沉默池有意义（用户已选定此方案）。
- 参数化：`compute(df, *, window_seconds=10, k=2, max_observation_seconds=300, observation_ratio=0.25)`。

### 3.2 全局用户分类

```
对每个 uid，统计 t ≥ O 的发言数 c：
  c == 0 → 不入池（开场后才出现，或只在观测期内发言）
  c ≤ k（k=2）→ 沉默用户
  c > k      → 活跃用户
```

### 3.3 窗口激活率

```
对网格每个 t：
  t < O            → NaN（跳过开场观测期，策略文档"建议跳过"）
  否则：
    窗口 U(t) = { 在 [t-W, t) 内发言的 uid 集合 }
    激活率(t) = |U(t) ∩ 沉默池| / |U(t)|
    |U(t)| == 0     → NaN
```

### 3.4 输出

```python
@dataclass(frozen=True)
class ActivationResult:
    activation: pd.Series      # 1 秒网格，float，NaN 处为无效
    silent_uids: frozenset[str]
    active_uids: frozenset[str]
    observation_seconds: float
    n_silent: int
    n_active: int

def compute(df, *, window_seconds=10, k=2,
            max_observation_seconds=300, observation_ratio=0.25) -> ActivationResult
```

### 3.5 实现要点

- 按秒分组 uid 集合 → 尾随窗口内集合取并集 → 计数。O(网格 × W) 集合运算，当前数据量（几百条弹幕）无压力；在 docstring 注明大流可改用按 uid 的 0/1 网格向量化。
- 阈值参考（仅用于报告展示，不做判定）：<40% 正常 / 40-60% 轻度出圈 / 60-80% 明显出圈 / >80% 出圈级。

---

## 4. 指标 4：弹幕长度分布（`metrics/length_dist.py`）

### 4.1 定义

```
短 = length ≤ 5
长 = length > 15
中 = 5 < length ≤ 15
```

### 4.2 窗口占比

```
对网格每个 t：
  窗口弹幕数 N(t) = count(窗口内所有弹幕)  = count(短) + count(中) + count(长)
  短占比(t) = count(短 in 窗口) / N(t)
  长占比(t) = count(长 in 窗口) / N(t)
  中占比(t) = 1 - 短占比 - 长占比
  N(t) == 0 → NaN；t < W → NaN
```

### 4.3 输出

```python
@dataclass(frozen=True)
class LengthDistResult:
    short_ratio: pd.Series
    long_ratio: pd.Series
    mid_ratio: pd.Series

def compute(df, *, window_seconds=10) -> LengthDistResult
```

### 4.4 实现要点

- 复用 `_window.rolling_sum`：先按秒聚合短/中/长计数序列，再尾随滑窗求和。
- 阈值参考（报告展示）：短占比突升 >70% = 情绪宣泄；长占比突升 >30% = 深度讨论/争议。

---

## 5. 输出集成

### 5.1 控制台（`report.console_print` 新增两段，位于指标 2 之后）

```
=== 指标3: 沉默用户激活率 ===
观测期: 43.2 秒 (流时长 172.8s 的 25%)
沉默池: N 人 / 活跃: M 人 (K=2)
有效区间: t ≥ 43.2
激活率 均值: x.xx / 峰值: x.xx at t=...
候选窗口内平均激活率:  #1: xx%  #2: xx%

=== 指标4: 弹幕长度分布 (W=10s) ===
短/中/长占比均值: xx / xx / xx
短弹幕激增(>70%)窗口数: N  / 长弹幕激增(>30%)窗口数: N
候选窗口内平均 短占比/长占比:  #1: xx/xx  #2: xx/xx
```

- "候选窗口内平均激活率/占比"：对 `highlights.find_candidates` 产出的每个区间，取该区间内网格点均值（NaN 忽略）。该行呼应策略文档"对每个候选点一键跑批"与"密度高+激活率高=真高潮"。

### 5.2 图表（`report.plot` 扩为 2×3）

| 位置 | 内容 |
|------|------|
| (0,0) | 密度 D(t) + μ+2σ / μ+3σ 阈值线 |
| (0,1) | 爆发速率 S(t) + 3σ |
| (0,2) | 激活率(t) + 40% / 60% / 80% 参考线 |
| (1,0) | 相对爆发速率 S_rel(t) |
| (1,1) | 短占比 / 长占比 曲线 + 70% / 30% 参考线 |
| (1,2) | 密度柱状视图（事件 stem） |

---

## 6. 错误处理与边界

| 场景 | 行为 |
|------|------|
| 观测期 ≥ 流时长（极短流） | 自适应后仍无 `t ≥ O` 网格点 → 激活率全 NaN + 警告"观测期超过流时长" |
| 沉默池为空 | 警告"无沉默用户，激活率恒为 0"；序列全 0（分子恒为 0，分母正常，0/0 场合为 NaN） |
| 窗口总用户数 = 0 | 激活率 NaN |
| 窗口总弹幕数 = 0 | 三占比 NaN |
| DataFrame 为空 | 返回空序列的 Result，不崩溃 |

---

## 7. 测试策略（TDD，沿用既有模式）

| 测试文件 | 覆盖 |
|---------|------|
| `tests/test_activation.py` | 用户分类（沉默/活跃/不入池）；窗口分子分母含去重；`t<O` 为 NaN；分母为 0 → NaN；自适应观测期（短流 25%、长流 300） |
| `tests/test_length_dist.py` | 短/中/长判定边界（5、15、6、16）；窗口占比；N=0 → NaN；`t<W` → NaN |
| `tests/test_report.py` | 新增两个 section 标题出现；候选窗口均值行存在 |
| `tests/test_main.py` | 集成冒烟：输出含指标3/指标4 section |

---

## 8. 文件清单

```
src/video_highlight/
├── metrics/
│   ├── activation.py      # 新增：指标 3
│   └── length_dist.py     # 新增：指标 4
├── report.py              # 修改：console_print 增两段、plot 扩 2×3
└── __main__.py            # 修改：串联 activation + length_dist
tests/
├── test_activation.py     # 新增
├── test_length_dist.py    # 新增
├── test_report.py         # 修改：断言新 section
└── test_main.py           # 修改：断言集成输出
```

不修改：parser、loader、_window、density、burst、highlights。

---

## 9. 完成定义（DoD）

- [ ] `uv run pytest` 全量通过（含既有 41 项 + 新增）
- [ ] `uv run video-highlight docs/danmaku.xml`（无参默认）输出含指标 3、指标 4 两段
- [ ] `--plot` 生成 2×3 六子图 PNG
- [ ] 激活率序列在 `t < 观测期` 为 NaN，观测期值符合自适应公式
- [ ] 长度分布短/中/长占比和为 1（有效点）
- [ ] 不修改 parser/loader/_window/density/burst/highlights
- [ ] 无占位、无自创阈值（阈值全部来自策略文档）
