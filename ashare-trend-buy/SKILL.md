---
name: ashare-trend-buy
description: Screen A-share research watchlists using right-side trend-following buy standards. Use when the user asks for A股右侧趋势买入、趋势买点、候选标的筛选、A/B/C分档、缩量回踩、平台突破、强势二买, or asks to evaluate A-share candidates with moving averages, volume-price behavior, MACD/KDJ, main-theme strength, support/invalidation, and fundamentals. This skill produces research watchlists only, not personalized investment advice.
---

# A股右侧趋势买入筛选

Use this skill to turn A-share candidates into a disciplined research watchlist. The goal is not to predict the lowest point; it is to find stocks that already have upward trend structure, healthy pullback or breakout behavior, current theme support, clear support/invalidation, and understandable fundamental or industry logic.

Never present output as a direct buy recommendation. Use conditional language such as “观察”, “等待确认”, “若跌破则剔除”, “条件满足后再评估”.

## Preferred Script

Prefer the bundled script for repeatable runs:

```powershell
python ashare-trend-buy/scripts/run_trend_buy.py --date 2026-05-22
```

Optional arguments:

- `--top200 PATH`: optionally reuse a user-supplied verified same-day turnover top-200 CSV.
- `--runs-dir runs`: output root.
- `--no-network`: use only the supplied/local candidate file and fail if daily K-line fetching is required.

The script must save:

```text
runs/ashare-trend-buy/YYYY-MM-DD/YYYY-MM-DD.md
```

Do not archive process data in `runs/`: raw API responses, K-line payloads, candidate CSVs, scoring JSON, and copied helper scripts are intermediate data and should stay in memory or a temporary workspace only.

## Data Discipline

1. Confirm the screening date. Do not hard-code dates in reusable skill logic.
2. Prefer a user-supplied same-day verified turnover top-200 file when present; otherwise fetch the ranking directly.
3. Otherwise fetch the A-share turnover ranking from Sina. Treat a ranking as invalid if the top rows have zero or missing turnover, zero price, or pre-open tick times.
4. Use Tencent or Sina daily OHLC for 5/10/20/30/60-day MA, volume ratio, MACD, and KDJ. Require at least 60 daily bars.
5. If the latest K-line date differs from the screening date, state the lag in the report. Do not silently mix dates.
6. Keep process data out of `runs/`; the dated Markdown report is the only required run artifact.

## Scoring And Tiering

Score out of 100:

| Dimension | Weight | Guidance |
|---|---:|---|
| Trend structure | 17 | 5/10/20-day alignment, higher lows, price above key averages |
| Pullback/breakout quality | 13 | shrinking-volume stabilization or clean platform breakout |
| Volume-price health | 13 | moderate expansion on rises, contraction on pullbacks, no exhaustion signal |
| Theme strength | 15 | current policy, earnings, industry, AI hardware, semiconductor, PCB, CPO, robot, energy-storage, or other verified theme |
| Support and risk control | 15 | clear support, invalidation level, acceptable distance to support |
| Fundamental/theme logic | 15 | financial reports, announcements, orders, products, capacity, policy, or industry inflection |
| Technical auxiliaries | 7 | MACD/KDJ confirmation or warning only |
| Liquidity | 5 | active turnover and tradability |

Tier rules:

```text
85-100: A档，重点观察，等待规则内买点确认
75-84: B档，逻辑较好，但仍需等待回调、缩量或突破确认
65-74: C档，只跟踪，不急买
<65: 剔除
```

Hard downgrade/exclusion rules override raw score:

- If price is below the 20-day MA and 5/10/20-day MAs remain bearish, cap at C or remove.
- If price is far above the 20-day MA, force downgrade even when score is high. Use 18% as a caution threshold and 25% as a hard “do not chase” threshold.
- If the stock just had a sharp one-day spike and has not consolidated, do not keep A档.
- If there is KDJ高位死叉, MACD死叉 with broken support, high-position huge-volume upper shadow, failed breakout, or放量大跌, downgrade or remove.
- MACD/KDJ are auxiliary only. They must never be the sole reason for an A档 or buy-point observation.

## Report Ordering

Always order the final table and shortlists by tier first, then score:

```text
A档 by score desc
B档 by score desc
C档 by score desc
剔除 by score desc
```

Do not let a high-score B档 appear before A档 if it was force-downgraded by risk rules.

## Required Report

Use the same report frame as `ashare-ai-slowbull` so both skills produce comparable Markdown. Keep the trend-buy-specific right-side structure, support/invalidation, and buy-point discipline inside the shared fields.

````markdown
# A股右侧趋势买入标准筛选结果

筛选日期：
执行技能：ashare-trend-buy
结果类型：研究观察池，不是最终买入名单

## 数据说明
- 数据来源：candidate source, K-line source, fetch method, and saved artifact paths.
- 数据完整性：candidate count, calculated count, latest K-line date, missing/lagged rows, and whether the candidate pool comes from a same-day top-200 file.
- 指标口径：MA/volume ratio/MACD/KDJ/support/invalidation/scoring methodology.
- 市场环境：main-theme state and whether right-side trading conditions are supportive.
- 限制说明：lagged K-lines, missing candidates, degraded data source, or items that can only be kept as initial watchlist.
- 展示上限：each tier shows at most 5 names; if a tier has more than 5 candidates, show the highest-score 5 in the final report.

## 一、筛选结论
- 市场环境：
- A档，重点观察（最多5只）：
- B档，等待买点（最多5只）：
- C档，只跟踪不追（最多5只）：
- 剔除/暂不追（最多5只）：

## 二、核心表格
| 档位 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 买点观察 |
|---|---:|---|---:|---|---|---|---|---|---|---|---:|---|

## 三、逐个点评
逐只按同一顺序说明：方向/主线、关键数据、趋势结构、MACD/KDJ、量价/资金、证据/逻辑、买点观察、失效条件和主要风险。

## 四、最终短名单
```text
最优先观察：最多5只
次优先观察：最多5只
只跟踪不急买：最多5只
剔除但跟踪板块强度：最多5只
```

## 五、买点观察与失效条件
- A/B档共同纪律：
- 均线回踩：
- 平台突破：
- 强势二买：
- 统一失效：

## 六、数据限制与风险提示

## 参考来源
````

Field guidance for this skill:

- `关键数据` should include turnover amount, turnover ratio, latest move, 20-day MA deviation, and latest K-line date.
- `证据/逻辑` should focus on main-theme/fundamental logic, not the AI-upstream evidence tier used by `ashare-ai-slowbull`.
- `支撑/失效` must state a concrete support level, invalidation level, or downgrade trigger.
- `买点观察` must preserve the right-side models: shrinking-volume pullback, platform breakout, strong second-entry, or slow-bull continuation.
- Each displayed tier must contain no more than 5 names. Rank within each tier by score before truncating.
- The final answer shown to the user and the archived `YYYY-MM-DD.md` must contain the same report body.

End with: `以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。`
