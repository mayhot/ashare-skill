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

For next-day or same-day validation of a prior shortlist, use:

```powershell
python ashare-trend-buy/scripts/validate_trend_buy.py --source-date 2026-05-27 --quote-date 2026-05-28
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
| Pullback/breakout quality | 13 | shrinking-volume stabilization, trend-stock pullback near the 20-day MA with stabilization, or clean platform breakout |
| Volume-price health | 13 | moderate expansion on rises, contraction on pullbacks, no exhaustion signal |
| Theme strength | 15 | current policy, earnings, industry, AI hardware, semiconductor, PCB, CPO, robot, energy-storage, or other verified theme; prefer recognized high-awareness, high-popularity front-runners in their industry segment |
| Support and risk control | 15 | clear support, invalidation level, acceptable distance to support |
| Fundamental/theme logic | 15 | financial reports, announcements, orders, products, capacity, policy, or industry inflection |
| Technical auxiliaries | 7 | MACD/KDJ confirmation or warning only |
| Liquidity | 5 | active turnover and tradability |

Tier rules:

```text
85-100: A档，重点观察，等待规则内买点确认
75-84: B档，逻辑较好，但需区分等待回踩和强势延续确认
65-74: C档，只跟踪，不急买；可标记低确定性高弹性
高分但过热: 过热跟踪，不追高，等待分歧后的二次确认
失效或<65: 剔除
```

State rules:

```text
A-确认观察：趋势、主线、量价和支撑条件较完整。
B-等待回踩：逻辑较好，但买点未出现，等待缩量回踩或平台确认。
B-强势延续：主线前排放量突破或强承接，但不能追高，需盘中确认。
C-低确定性高弹性：辨识度或证据不足，但弹性强，保留跟踪。
C-只跟踪：结构尚可但主线/人气/买点不足。
X-过热强势：距20日线过远、单日大涨未整理等，不追高但保留二次确认池。
X-失效剔除：放量下跌、MACD/KDJ破位、支撑失效或趋势损坏。
```

Hard downgrade/exclusion rules override raw score:

- If price is below the 20-day MA and 5/10/20-day MAs remain bearish, cap at C or remove.
- For trend stocks, a pullback toward the 20-day MA is an opportunity only after stabilization: strong stabilization near -1% to +5% from the 20-day MA with calm volume and no obvious MACD damage, or watchable stabilization near -2% to +10% with controlled volume.
- For same-tier candidates, prefer recognized high-awareness, high-popularity front-runners in their industry segment; use sector-level turnover/relative-strength rank when available, and downgrade weak followers with low recognition or poor relative strength.
- If price is far above the 20-day MA, force downgrade even when score is high. Use 18% as a caution threshold and 25% as a hard “do not chase” threshold. For high-score main-theme front-runners, route this to `X-过热强势` rather than true deletion unless price action has already failed.
- If the stock just had a sharp one-day spike and has not consolidated, do not keep A档; classify it as `B-强势延续` or `X-过热强势` depending on distance from support and theme strength.
- If there is KDJ高位死叉, MACD死叉 with broken support, high-position huge-volume upper shadow, failed breakout, or放量大跌, downgrade or remove. Treat 放量下跌 and MACD死叉叠加破位 as `X-失效剔除`.
- If a high raw-score stock is downgraded or removed by a hard rule, state the raw score, hard-rule reason, and risk-adjusted tier clearly in the table or commentary.
- MACD/KDJ are auxiliary only. They must never be the sole reason for an A档 or buy-point observation.

## Report Ordering

Always order the final table and shortlists by tier first, then score:

```text
A档 by score desc
B档 by score desc
C档 by score desc
过热跟踪 by score desc
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
- 指标口径：MA/volume ratio/20-day MA stabilization tier/MACD/KDJ/support/invalidation/front-runner popularity/scoring methodology.
- 市场环境：main-theme state and whether right-side trading conditions are supportive.
- 限制说明：lagged K-lines, missing candidates, degraded data source, or items that can only be kept as initial watchlist.
- 剔除解释：for high raw-score exclusions, state raw score and hard exclusion reason.
- 展示上限：each tier shows at most 5 names; if a tier has more than 5 candidates, show the highest-score 5 in the final report.

## 一、筛选结论
- 市场环境：
- A档，重点观察（最多5只）：
- B档，等待买点（最多5只）：
- C档，只跟踪不追（最多5只）：
- 过热强势跟踪（最多5只）：
- 失效剔除/暂不追（最多5只）：

## 二、核心表格
| 档位 | 状态 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 买点观察 |
|---|---|---:|---|---:|---|---|---|---|---|---|---|---:|---|

## 三、逐个点评
逐只按同一顺序说明：方向/主线、关键数据、趋势结构、MACD/KDJ、量价/资金、证据/逻辑、买点观察、失效条件和主要风险。

## 四、最终短名单
```text
最优先观察：最多5只
次优先观察：最多5只
只跟踪不急买：最多5只
过热强势跟踪：最多5只
失效剔除但保留复盘：最多5只
```

## 五、买点观察与失效条件
- A/B档共同纪律：
- 均线回踩：
- 20日线企稳：
- 平台突破：
- 强势延续：
- 过热跟踪：
- 强势二买：
- 统一失效：

## 六、数据限制与风险提示

## 参考来源
````

Field guidance for this skill:

- `关键数据` should include turnover amount, turnover ratio, latest move, 20-day MA deviation, 20-day MA stabilization tier, and latest K-line date.
- `证据/逻辑` should focus on main-theme/fundamental logic, not the AI-upstream evidence tier used by `ashare-ai-slowbull`; for otherwise similar candidates, state whether the stock is a recognized high-awareness, high-popularity front-runner in its industry segment, preferably with sector-level turnover/strength rank.
- `支撑/失效` must state a concrete support level, invalidation level, or downgrade trigger.
- `买点观察` must preserve the right-side models: shrinking-volume pullback, 20-day MA stabilization, platform breakout, strong second-entry, or slow-bull continuation.
- `过热强势跟踪` entries with high raw scores must show the overheat reason and the secondary-confirmation condition.
- `剔除/暂不追` entries must be true invalidation candidates where price/volume/indicator damage is already visible.
- Each displayed tier must contain no more than 5 names. Rank within each tier by score before truncating.
- The final answer shown to the user and the archived `YYYY-MM-DD.md` must contain the same report body.

## Validation Loop

When the user asks to check yesterday's selections, validate the latest shortlist with `validate_trend_buy.py`. Report:

- Quote timestamp and index background.
- Per-tier average return, median return, win rate, best/worst name.
- Per-state performance, especially `B-强势延续`, `X-过热强势`, and `X-失效剔除`.
- Reflection on which rules worked, which rules were too strict, and which candidates were false positives or false negatives.

Do not judge the skill only by next-day涨跌幅. Also check whether the predicted path was respected: did A/B wait for confirmation, did overheated names require no-chase discipline, did true invalidation underperform, and did C names remain low-confidence despite occasional single-stock bursts.

End with: `以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。`
