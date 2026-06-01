---
name: ashare-holdings-check
description: Daily A-share position health check for existing holdings. Use when the user provides持仓表、每日持仓数据、成交/行情数据、成本价、现价、仓位、浮盈浮亏、K线或技术指标，并 wants a disciplined research-only holding diagnosis with actions such as继续持有、加仓观察、减仓、清仓/退出观察, position sizing bands, invalidation levels, and daily risk notes. This skill is for portfolio review and risk control, not personalized investment advice.
---

# A股每日持仓体检

Use this skill to inspect an existing A-share portfolio after each trading day. The goal is to protect capital first, keep winners that still have healthy structure, avoid emotional补仓, and turn every holding into a clear next-day plan.

Always label outputs as research/risk-control suggestions, not personalized investment advice. Use conditional language: `若放量跌破...则减仓`, `若缩量企稳并重新站上...才考虑加仓`, `继续持有但不追高`.

## Quick Start

Prefer the bundled script when the user has structured CSV data:

```powershell
python ashare-holdings-check/scripts/check_positions.py --holdings path/to/holdings.csv --prices path/to/prices.csv --benchmark path/to/benchmark.csv --sectors path/to/sectors.csv --events path/to/events.csv --date 2026-05-28 --runs-dir runs
```

`--prices`, `--benchmark`, `--sectors`, and `--events` are optional. Without price history, the script still checks仓位、浮盈浮亏、成本/现价 and data completeness, but technical conclusions must be marked as limited. Without benchmark/sector/event inputs, do not invent大盘环境、板块强弱 or event-calendar conclusions.

The script writes:

```text
runs/ashare-holdings-check/YYYY-MM-DD/YYYY-MM-DD.md
```

If the user provides Excel, screenshots, broker exports, or pasted tables, normalize them into a table with as many of these fields as possible before analyzing:

```text
code, name, quantity, cost_price, latest_price, market_value, portfolio_weight,
today_pct, unrealized_pct, hold_days, industry, note
```

Optional daily price history should use:

```text
code, date, open, high, low, close, volume, amount, turnover, pct_chg
```

Optional benchmark CSV uses the same K-line columns as prices; include at least one broad index such as沪深300、中证1000、创业板指 or上证指数. Optional sector CSV should use:

```text
industry, date, open, high, low, close, volume
```

Optional event CSV should use:

```text
code, date, event, impact
```

Use `impact` values such as `高`, `中`, `低`, `upcoming`, or short labels like减持、解禁、财报、问询. Treat event data as a risk calendar, not as a prediction.

## Daily Workflow

1. Confirm the体检日期、数据来源、是否收盘后、是否有最新行情/K线.
2. Normalize holdings by stock code; calculate market value, weight, floating P/L, and missing fields.
3. Calculate technical indicators when price history exists: MA5/10/20/60, MA20 deviation, MA60 position, 20-day high drawdown, 20/60-day return, volume ratio, RSI14, MACD, KDJ, ATR-style volatility, support and invalidation level.
4. If benchmark data exists, judge大盘环境 and calculate relative strength RS20/RS60 against the benchmark.
5. If sector data exists, judge板块强弱, sector MA20 state, and sector relative strength against the benchmark.
6. If event data exists, mark upcoming or recent risk windows such as财报、减持、解禁、问询、处罚、重大公告.
7. Check portfolio structure before judging single stocks: cash ratio if available, single-stock concentration, same-sector concentration, loss concentration, and whether all holdings depend on one market theme.
8. Score each holding out of 100, then apply hard downgrade/exit rules and context adjustments.
9. Produce one clear action for each holding: `继续持有`, `加仓观察`, `减仓`, `清仓/退出观察`, or `只观察不操作`.
10. Save only the final Markdown report under `runs/ashare-holdings-check/YYYY-MM-DD/`; do not archive raw broker exports or temporary data unless the user asks.

## Health Indicators

Score each holding with these default weights:

| Dimension | Weight | What to check |
|---|---:|---|
| Trend structure | 20 | Price vs MA5/10/20/60, MA alignment, higher highs/lows, MA20 slope |
| Position safety | 15 | Current weight, single-name concentration, sector crowding, liquidity |
| Profit/loss quality | 15 | Floating P/L, distance from cost, giveback from recent high, whether profit is protected |
| Volume-price health | 15 | Volume expansion on rises, contraction on pullbacks, abnormal high-volume stall or selloff |
| Support and invalidation | 15 | Concrete support, stop/downgrade level, distance to invalidation |
| Momentum auxiliaries | 10 | MACD/KDJ/RSI confirmation or warning; never use alone |
| Thesis and event risk | 10 | Earnings, announcements, policy/sector logic, negative events, unlock/reduction pressure |

Context adjustments after the 100-point base score:

| Indicator | Adjustment | Guidance |
|---|---:|---|
| Market environment | -2 to hard cap | If benchmark is below MA20, do not upgrade weak holdings and cap new add suggestions unless the stock is clearly outperforming |
| Sector strength | +3 / -4 | Upgrade stocks in sectors outperforming the benchmark; downgrade weak-sector holdings, especially if both stock and sector are below MA20 |
| Relative strength RS20/RS60 | +4 / -6 | Reward holdings that outperform the benchmark; downgrade names that lag badly while occupying capital |
| ATR volatility | +1 / -5 | Low/normal volatility supports holding; ATR14 above 5%-8% requires smaller position size and wider-but-defined invalidation |
| Event calendar | -4 / -8 and hard cap | Medium-risk events reduce add aggressiveness; high-risk events can force减仓 even if the chart is still acceptable |

Portfolio-level checks:

- Single stock above 20% of portfolio: mark as concentration warning unless it is a deliberate core position.
- Single stock above 30%: cap action at `继续持有` or `减仓`; do not suggest adding.
- Same sector above 45%: downgrade add suggestions in that sector unless the user explicitly runs a集中持仓 strategy.
- Any loss-making holding below -8% with broken MA20: require a defined repair condition or reduce.
- Any holding below -15% with trend damage: default to `清仓/退出观察` unless there is strong, newly verified fundamental evidence.
- Weak benchmark + weak sector + stock below MA20: default to `减仓` or worse; do not mark as `加仓观察`.
- Strong stock with weak benchmark: may continue holding, but only mark `加仓观察` if RS20 is positive, sector is not weak, and there is no event risk.
- ATR14 above 8%: reduce position-size ceiling unless the user explicitly accepts high volatility.
- High-risk event window: cap action at `减仓` or `只观察不操作` until the event is digested.

## Action Rules

Use score plus hard rules; hard rules override the raw score.

| Action | Normal trigger | Position wording |
|---|---|---|
| 继续持有 | Score >= 75, trend intact, support clear, current weight reasonable | Hold existing size; trail stop to support/MA20/platform low |
| 加仓观察 | Score >= 82, current weight below target, trend healthy, pullback or breakout condition not overheated | Add only on confirmation; suggest add band such as +20%-30% of current position, not all-in |
| 减仓 | Score 55-74, trend weakening, overweight, profit giveback, or support distance too large | Reduce 20%-50%; keep observation size if thesis remains |
| 清仓/退出观察 | Score < 55 or hard invalidation appears | Exit or reduce to token tracking position; wait for full reset before reconsidering |
| 只观察不操作 | Data incomplete, suspended stock, extreme volatility, or no clear edge | Ask for missing data or wait for next close |

加仓观察 is the strictest action:

- Never suggest adding to a falling knife, a high-volume breakdown, or a holding already above the concentration limit.
- Prefer加仓 after缩量回踩 MA10/MA20 企稳, platform breakout that holds, or strong trend second-entry after 3-8 days of consolidation.
- If price is more than 15% above MA20, cap at `继续持有`; if more than 25% above MA20, mark as overheat and consider trimming instead.
- If the position is losing money, adding is allowed only after price reclaims MA20/support and volume confirms; otherwise use `等待修复`.
- If大盘 is below MA20 or板块 is below MA20, adding requires extra confirmation: stock RS20 positive, volume not abnormal, and price holding above MA20.
- Do not add before high-risk events such as减持窗口、解禁、财报不确定期、监管问询 or重大公告 unless the user explicitly requests an event-driven strategy.

Hard减仓/清仓 rules:

- 放量跌破 MA20 or platform lower edge and fails to reclaim within 1-3 sessions.
- Price breaks MA60 with MA20 turning down, unless it is a planned long-cycle position with explicit thesis.
- MACD high-level dead cross plus weak close, KDJ high-level dead cross plus support break, or RSI overheat reversal with volume spike.
- Single-day high-volume long upper shadow after a large rise.
- Floating loss <= -12% and no visible repair path; <= -15% with broken trend usually exit.
- Company thesis is disproved by financial report, announcement, regulatory/event risk, or major shareholder reduction.
- Stock underperforms benchmark by more than 8 percentage points over 20 trading days while also below MA20.
- Sector below MA20 and weaker than benchmark, while the stock also loses key support.
- ATR14 rises above 8% with放量下跌 or gap-down behavior.
- High-risk event appears and the position is already overweight or亏损.

## Support And Sizing

Every action must include at least one trigger:

- `继续持有`: support level, trailing stop, and what would change the action.
- `加仓观察`: exact confirmation condition and maximum add size.
- `减仓`: what portion to cut and what condition would allow holding the remainder.
- `清仓/退出观察`: invalidation reason and what full reset would be needed before re-entry.

Default sizing language:

```text
核心强势且仓位合理：维持原仓，最多加到目标仓位上限。
加仓观察：确认后加现有仓位的20%-30%，总仓位不超过组合的15%-20%。
减仓：先降20%-50%，若再破关键位则继续降至观察仓或退出。
清仓/退出观察：退出后至少等待重新站回MA20/平台并完成缩量企稳。
```

## Required Report

Use this Markdown shape:

````markdown
# A股每日持仓体检报告
体检日期：
执行技能：ashare-holdings-check
结果类型：持仓风控体检，不构成个性化投资建议

## 数据说明
- 持仓数据：
- 行情/K线数据：
- 数据完整性：
- 指标口径：
- 环境/板块/事件：
- 主要限制：

## 一、组合结论
- 总市值/现金/仓位：
- 集中度：
- 环境与事件：
- 今日主要风险：
- 明日优先动作：

## 二、持仓体检表
| 操作建议 | 优先级 | 标的 | 代码 | 仓位 | 浮盈浮亏 | 趋势状态 | 量价/动量 | 支撑/失效 | 评分 | 具体动作 |
|---|---:|---|---:|---:|---:|---|---|---|---:|---|

## 三、逐个点评
按同一顺序说明：持仓状态、趋势结构、盈亏质量、量价/动量、支撑/失效、建议动作、明日观察点。

## 四、组合调整清单
```text
继续持有：
加仓观察：
减仓：
清仓/退出观察：
只观察不操作：
```

## 五、风险提示
````

Ordering: show `清仓/退出观察` and `减仓` first by priority, then `加仓观察`, `继续持有`, and `只观察不操作`. Risk control comes before optimism.

## Validation

Before finishing a run:

1. Confirm every holding has exactly one action.
2. Confirm every add/reduce/exit action has a trigger and size guidance.
3. Confirm overweight names are not marked `加仓观察`.
4. Confirm technical claims are not made when price history is missing.
5. Confirm the final user response and saved Markdown report contain the same report body.
