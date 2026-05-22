---
name: ashare-ai-slowbull
description: Screen A-share candidates for AI hardware upstream second-line slow-bull opportunities, strictly limited to post-close 今日A股成交额前200. Use when the user asks to filter AI硬件上游, 二线补涨, 慢牛趋势, MACD/KDJ金叉死叉, 光模块/光芯片/PCB/CCL/电子布/先进封装/连接器/液冷/AI电源/高速接口芯片等方向, and wants A/B/C分档、评分、剔除理由、买点观察或最终短名单. This skill only runs after the A-share close and is for research watchlists, not direct investment advice.
---

# A股AI硬件上游二线慢牛标的筛选

## Core Principle

Use this skill to build a research watchlist, not a buy/sell recommendation. Keep the central thesis explicit:

```text
不追AI硬件头部加速票；
不把服务器整机当作A档核心；
从今日成交金额前200中，
寻找AI硬件上游方向里成交活跃、趋势慢牛、基本面改善、涨幅尚未透支的二线补涨标的。
```

Always use current market data for real screening. Do not invent turnover rankings, market caps, prices, financials, RSI, institutional activity, announcements, or customer relationships. If current data is unavailable, ask the user to provide the turnover list or state the limitation clearly.

## Post-Close Only Hard Rule

Only execute a real screening run after the A-share regular session has closed. Use China market time unless the user explicitly provides a different market calendar.

- Do not run the real screen before 15:30 China time on an A-share trading day. If asked before then, stop and say the skill is restricted to post-close execution.
- If the current date is not an A-share trading day, use the most recent completed trading day only if the user agrees or explicitly asks for it; otherwise ask for the intended trading date.
- The report must separate `run_time`, `trade_date`, and `quote_ticktime`. Never infer the trading date only from the output folder name.
- Verify the returned quote timestamp. For a valid same-day post-close run, top rows should have `ticktime` around 15:00 or later and the data date should match `trade_date`. If timestamps are stale or ambiguous, do not present the result as today's complete top-200 screen.
- Archive both the run metadata and the quote metadata, including source, sort field, row count, `run_time`, `trade_date`, representative `quote_ticktime`, and whether any fallback source was used.

## Data Requirements

For each real screening run, gather or verify:

- Current A-share turnover ranking, strictly 今日成交金额前200.
- `run_time`, `trade_date`, quote/update time, data-source freshness, and whether the run passed the post-close timestamp check.
- Total market cap, exchange/board, latest price change, recent 3/6/12-month performance, turnover amount, and liquidity.
- Sector context: AI hardware/optical module/PCB/semiconductor packaging/liquid cooling indices or representative leaders, sector turnover, sector stage, and whether core leaders are breaking down.
- Trend indicators: 5/10/20/30-day moving averages, platform consolidation, relative strength, volume behavior, 20-day MA deviation, RSI, MACD, KDJ, and short-term overheat signals.
- Fundamental evidence: latest annual/interim/quarterly report, announcements, investor relations, institution research, customer/product/capacity progress, margin/revenue/profit changes.
- Industry-chain placement: confirm whether revenue/products truly relate to AI hardware upstream demand.

Prefer primary or high-quality sources for fundamentals and announcements. If using secondary market data sites, treat them as inputs to verify rather than final truth.

## Data Source Strategy

Use a layered data approach. Do not scatter across many platforms unless a layer fails or evidence is missing:

1. **Market data layer - Sina first**: Use Sina Finance `Market_Center.getHQNodeData` as the default free source for A-share turnover ranking, price, change percent, turnover amount, turnover ratio, PE/PB, market cap, and quote time. Sort by `amount` descending and paginate until at least 200 valid A-share records are collected.
2. **Quote fallback - Tencent**: Use Tencent quote APIs only as a backup for batch single-stock quotes after candidate codes are known. Tencent is useful for price/turnover checks, but is not the preferred source for full-market turnover ranking.
3. **Library fallback**: If Sina fails, try AkShare `stock_zh_a_spot_em`, efinance `get_realtime_quotes`, then Eastmoney `push2` directly. If all fail, use a clearly labeled degraded source such as 52daban top 100.
4. **Classification layer**: Intersect the turnover top 200 with a local AI hardware upstream watchlist when available. If no local watchlist exists, classify using the segment list in this skill and verify with company business descriptions.
5. **Evidence layer**: After candidate screening, verify only A/B candidates with announcements, financial reports, investor relations, or high-quality research/news. Do not try to verify the full market one by one.

Completeness checks:

- After fetching market data, confirm that at least 200 valid A-share rows were collected.
- If a single request returns fewer than expected, paginate and merge unique symbols until 200 are reached.
- If fewer than 200 can be obtained, state the exact count and do not present the result as a complete top-200 screen.
- If `run_time` is after 15:30 but quote timestamps are not from the completed trading day, treat the data as stale and stop unless the user accepts a degraded historical run.
- Preserve the data source name, URL or method, fetch date/time, sort field, and row count in the final report.

## Screening Scope

Only screen A-share listed companies:

- Shanghai Main Board, Shenzhen Main Board, ChiNext, STAR Market.
- Beijing Stock Exchange is not a priority unless liquidity, turnover, and industry logic are unusually strong.

Prioritize upstream or semi-upstream AI hardware segments:

- Optical modules, optical devices, optical chips.
- PCB, high-layer boards, HDI, package substrates.
- CCL, electronic cloth, fiberglass cloth, resin materials.
- Advanced packaging, Chiplet, HBM-related testing/packaging.
- High-speed connectors, copper cable, backplane interconnect.
- Liquid cooling, thermal management, cold plates, CDU.
- AI power supply, power modules, power management.
- Storage interface, high-speed interface chips, interconnect chips.
- AI compute upstream materials, components, equipment, and key processes.

Industry-chain purity tiers:

- **S tier**: Optical modules/devices/chips, AI PCB/high-layer boards/HDI/package substrates, advanced packaging/Chiplet/HBM testing-packaging, high-speed connectors/backplane/copper interconnect.
- **A tier**: CCL, electronic cloth/fiberglass/resin, liquid cooling/thermal management, AI power modules, HBM/semiconductor materials with direct AI hardware demand.
- **B tier**: Storage modules/products, broad semiconductor equipment/materials, consumer-electronics mixed logic, RF/ceramic/passive components with indirect AI hardware exposure.

Prefer S/A tier for A/B candidates. B-tier names usually cap at C unless turnover, trend, and verified fundamentals are unusually strong.

Do not put server OEMs, cloud platforms, compute leasing, or IDC operators into A档. Use them only as demand-chain references unless the user explicitly asks for broader coverage.

## Hard Filters

Try to require all of the following before a company enters the main candidate pool:

| Dimension | Requirement |
|---|---|
| Market | A-share listing |
| Theme | AI hardware upstream or semi-upstream |
| Market cap | Prefer RMB 50-200 billion |
| Turnover | Must be within today's A-share turnover top 200 |
| Price move | Avoid extremely crowded leaders or already overextended names |
| Trend | Slow-bull uptrend, strong consolidation, or medium-term rising channel |
| Fundamentals | Good fundamentals or clear positive change underway |
| Industry logic | Explainable link to incremental AI hardware demand |

Market-cap handling:

- Below RMB 50 billion: only mark as elastic observation unless turnover and fundamental change are outstanding.
- RMB 50-200 billion: best fit for this skill.
- Above RMB 200 billion: cap at B档 unless there is an unusually calm, well-consolidated slow-bull setup.
- Above RMB 300 billion: generally exclude from second-line补涨 treatment.
- Turnover rank top 10 plus market cap above RMB 200 billion: treat as a sector anchor by default, not an A档 second-line candidate.

## Market Regime Filter

Before scoring individual stocks, classify the AI hardware chain into one of four stages:

| Stage | How to Judge | Action |
|---|---|---|
| 主升 | Sector index and core leaders stay above 5/10-day MA; sector turnover expands; multiple upstream subsegments rise together | A档 can be assigned normally |
| 分歧 | Leaders still above 10/20-day MA but intraday volatility and divergence increase | Prefer B档; require stronger buy-point discipline |
| 修复 | Sector rebounds after pullback; leaders reclaim 10/20-day MA; turnover recovers | Allow A档 only for strongest slow-bull candidates |
| 退潮 | Leaders break 20-day MA, high-volume failed rebounds, sector turnover shrinks or funds rotate away | Do not assign A档; downgrade to observation unless fundamentals are unusually strong |

If the sector stage is unclear, state the uncertainty and avoid aggressive A档 conclusions.

## Quantitative Thresholds

Use these as default thresholds unless the user provides a different style:

| Check | Default Rule |
|---|---|
| 20-day gain | >50% downgrade for short-term overheat |
| 60-day gain | >100% usually not A档 unless after adequate consolidation |
| 1-year gain | >200% usually C档 or excluded as over-priced leader |
| MA20 deviation | Price >15%-20% above MA20 means avoid chasing and wait for pullback |
| RSI | RSI >75 downgrade for overheat; RSI 55-70 is healthier for slow-bull continuation |
| Daily move | Same-day gain >=9.5% caps the name at B档; if also overheated by RSI/MA20 deviation, cap at C档 |
| MACD | Zero-axis or above-zero golden cross with mild red-bar expansion is positive; high-level dead cross, expanding green bars, or bearish divergence is negative |
| KDJ | Mid/low-level golden cross is positive; high-level dead cross, J >90 reversal, or high-level passivation plus weak close is negative |
| Volume spike | Single-day turnover >2x 20-day average plus weak close indicates distribution risk |
| Platform setup | Prefer 5-15 trading days of consolidation before breakout |
| MA break | Effective break below MA20 for 2-3 sessions downgrades the setup |

Treat thresholds as guardrails, not mechanical trading signals. Explain any exception.

## Positive Signals

Upgrade candidates when several of these are present:

- AI-related revenue share is rising.
- The company is shifting from legacy business into AI hardware upstream.
- Recent reports show revenue, profit, or gross-margin improvement.
- New capacity, customers, products, or orders are ramping.
- Funds are paying attention, but the stock has not become the absolute market leader.
- Price climbs gradually along the 20-day or 30-day moving average.
- Today's turnover enters the top 200; top 100 receives an extra scoring advantage.

## Evidence Levels

Grade fundamental evidence before assigning the fundamental-change score:

| Level | Evidence | Fundamental Score Bias |
|---|---|---|
| Strong | Financial reports already show AI-related revenue, margin, profit, product mix, order, or capacity improvement | Can score high |
| Medium | Announcements, investor relations, institution research, customer/product/capacity progress support the change | Mid-to-high if consistent |
| Weak | Mainly investor Q&A, market concept labels, or unquantified product claims | Cap the score unless price/turnover evidence is very strong |
| None | No verifiable AI hardware upstream revenue/product/customer/order evidence | Exclude or at most C档 |

Do not give high fundamental-change scores to concept labels without business verification.

## Downgrade Or Exclude

Downgrade or exclude when any major risk dominates:

- Server OEM, system integrator, compute leasing, cloud service, or IDC with weak upstream exposure.
- Market cap far above RMB 200 billion, especially above RMB 300 billion.
- One-year increase is excessive or expectations look fully priced.
- Recent gains breach the quantitative overheat thresholds without adequate consolidation.
- Single-day spike, limit-up chase, or volume explosion without strong consolidation.
- Pure concept hype without order, product, customer, capacity, or earnings validation.
- Deteriorating fundamentals, persistent margin decline, or weak earnings delivery.
- AI link is only name/theme-based and weakly related to core revenue.
- RSI or short-term trend is overheated; repeated acceleration; high-volume stalling.
- Announcement warns of abnormal volatility, irrational speculation, or tiny AI revenue contribution.
- Liquidity is too weak to enter mainstream institutional/fund attention.
- Large shareholder reduction, unlock pressure, or major governance/financial risk.
- Sector stage is 退潮 and core leaders are breaking down.
- Hard cap: same-day gain >=9.5% can never be A档.
- Hard cap: RSI >80 or MA20 deviation >25% can never be A档.
- Hard cap: same-day gain >=9.5% plus RSI >80 or MA20 deviation >25% caps the name at C档.
- Hard exclude by default: market cap >RMB 300 billion, unless the user explicitly asks to track sector anchors.

## Workflow

1. Verify the post-close hard rule. If the run is before 15:30 China time on a trading day, stop instead of screening.
2. Determine and record `run_time`, `trade_date`, data-source quote timestamp, skill version, stock-pool version, threshold version, and whether fallback data is used.
3. Classify the sector stage: 主升, 分歧, 修复, or 退潮.
4. Fetch today's A-share turnover top 200, using Sina Finance as the default source and paginating until 200 valid rows are collected.
5. Validate that the quote timestamps match the completed `trade_date`; stop or label as degraded if stale.
6. Use structured market data for analysis, but do not archive raw/process data in `runs/`.
7. Intersect top 200 with the local/known AI hardware upstream universe or classify using the skill's segment list and purity tiers.
8. Keep only AI hardware upstream or semi-upstream names.
9. Remove server OEMs from A档 consideration and log excluded sector anchors separately.
10. Check market cap against the RMB 50-200 billion preferred band and apply hard caps.
11. Apply quantitative overheat, trend, MACD/KDJ, and platform thresholds.
12. Verify fundamental or industry-chain change for A/B candidates and assign evidence level.
13. Score the remaining names and assign A/B/C/excluded tiers.
14. Track known AI hardware upstream names not in today's top 200 during analysis when useful, but do not archive gap/process files in `runs/`.
15. Add buy-point observation and invalidation conditions as conditional scenarios, never as direct trading instructions.
16. Generate the final report from structured in-memory data or temporary workspace artifacts when possible.
17. Save only the final dated report under `runs/ashare-ai-slowbull/YYYY-MM-DD/YYYY-MM-DD.md`, where `YYYY-MM-DD` is the trading date.

## Scoring Model

Score out of 100:

| Dimension | Weight | Guidance |
|---|---:|---|
| AI hardware upstream purity | 20 | Higher when closer to optical modules/chips, PCB, CCL, electronic cloth, packaging, connectors, liquid cooling, power, interface chips |
| Turnover and fund behavior | 20 | Rank 1-100 scores highest; rank 101-200 scores next; look for sustained active turnover rather than one-day blowoff |
| Market-cap fit | 10 | RMB 50-200 billion scores best; too small or too large loses points |
| Moderate gains and crowding | 15 | Penalize threshold breaches, excessive MA20 deviation, RSI/MACD/KDJ overheat, and high-volume stalling |
| Trend quality | 20 | Slow bull, strong platform, multi-MA alignment, orderly volume, resilient pullbacks, healthy MACD/KDJ confirmation |
| Fundamental change | 15 | Earnings/order/customer/product/capacity/margin/business-mix improvement |

Technical momentum adjustment:

- Use MACD/KDJ only as auxiliary confirmation, not as a hard buy/sell condition.
- Add up to +5 within trend quality when MACD and KDJ strengthen in healthy positions without excessive MA20 deviation.
- Deduct up to -5 from trend/crowding when MACD/KDJ show high-level dead cross, bearish divergence, or overheat reversal.
- MACD/KDJ signals must be interpreted together with price position, volume, MA20, and sector stage.

Tiering:

```text
85+：A档，重点观察
75-84：B档，等待买点
65-74：C档，只跟踪不急买
<65：剔除
```

Hard tier caps override the numeric score. A score above 85 does not permit A档 if the name violates the post-close freshness check, market-cap anchor rule, same-day limit-up/overheat cap, or upstream purity requirement.

## Tier Logic

A档：core watchlist. Require clear upstream exposure, turnover top 200, RMB 50-200 billion market cap, non-extreme gains, slow-bull or strong-platform trend, and verified fundamental improvement. Must not be a server OEM or overheated absolute leader.

B档：logic is strong, but timing is imperfect. Typical reasons: short-term gain is large, valuation is high, just had a volume spike, needs consolidation, or market cap is near/above RMB 200 billion.

C档：track only. Typical reasons: strong industry position but too large, too hot, too extended, too crowded, or far from key moving averages.

Excluded：weak upstream relevance, concept hype, poor fundamentals, weak turnover, excessive market cap/gains, abnormal-risk announcement, or bubble-like technical state.

## Buy-Point Observation Rules

Discuss these only as watch conditions:

- Moving-average pullback: price tests 5/10/20-day MA, does not break, volume contracts, then volume expands upward. Prefer 10-day support over 20-day support; avoid intraday chase.
- Platform breakout: 5-15 trading days of sideways consolidation, mild volume expansion through platform high, close holds above breakout, and next day does not fall back into the platform.
- Strong second-entry setup: after a large up day or limit-up, wait 3-8 trading days of shrinking-volume consolidation, no break below 10/20-day MA, then renewed volume breakout.
- Slow-bull trend: price rises along 20/30-day MA, lows lift gradually, volume expands moderately, no repeated acceleration, resilient on sector pullbacks and quick to repair on rebounds.
- Momentum confirmation: MACD zero-axis/above-zero golden cross or KDJ mid/low-level golden cross can confirm a setup only when price is not far above MA20 and volume is orderly.

## Invalidation Rules

Every A/B candidate must include at least one downgrade or invalidation condition:

- Price breaks below MA20 and fails to reclaim it within 2-3 trading sessions.
- High-volume break below the consolidation platform lower edge.
- High-level long upper shadow or high-volume stalling after an extended move.
- MACD high-level dead cross, bearish divergence, or KDJ high-level dead cross appears together with weak price/volume behavior.
- Sector stage shifts to 退潮 or core AI hardware leaders break down.
- Financial report, announcement, or customer/order evidence disproves the AI hardware growth thesis.
- AI-related revenue contribution is confirmed to be very small and not improving.
- Large shareholder selling, unlock pressure, or abnormal-volatility announcement materially changes the risk profile.

## Required Report

Use the same report frame as `ashare-trend-buy` so both skills produce comparable Markdown. Keep the slow-bull-specific evidence and second-line AI hardware discipline inside the shared fields.

````markdown
# A股AI硬件上游二线慢牛筛选结果

筛选日期：
执行技能：ashare-ai-slowbull
结果类型：研究观察池，不是最终买入名单

## 数据说明
- 数据来源：source, fetch method, sort field, fetch time, and saved artifact paths.
- 数据完整性：valid A-share row count, whether today's turnover top 200 is complete, candidate count, and any missing/lagged data.
- 指标口径：MA/RSI/MACD/KDJ/volume/market-cap/fundamental evidence methodology.
- 市场环境：AI硬件链阶段：主升/分歧/修复/退潮, with one-line reason.
- 限制说明：unverified fundamentals, lagged K-lines, missing announcements, or degraded data source.
- 展示上限：each tier shows at most 5 names; if a tier has more than 5 candidates, show the highest-priority 5 in the final report.

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

- The report header must include `run_time`, `trade_date`, representative `quote_ticktime`, skill version, stock-pool version, threshold version, and fallback status.
- `关键数据` should include total market cap, today's turnover rank, latest move, and whether it fits the RMB 50-200 billion preference.
- `证据/逻辑` must include the evidence level: 强验证/中验证/弱验证/无验证.
- `买点观察` must be conditional. Never write direct buy instructions.
- `支撑/失效` must include at least one invalidation or downgrade condition for every A/B candidate.
- Each displayed tier must contain no more than 5 names. Rank within each tier by score and evidence priority before truncating.
- The final answer shown to the user and the archived `YYYY-MM-DD.md` must contain the same report body.

## Result Archive

After every completed screening run, create a date-specific run folder and save the same final result shown to the user as Markdown:

```text
runs/ashare-ai-slowbull/YYYY-MM-DD/
```

Rules:

- Use the actual screening date as `YYYY-MM-DD`. If the user specifies a screening date, use that date; otherwise use the current local date for the market being screened.
- Create `runs/ashare-ai-slowbull/` if it does not exist.
- Create a date folder: `runs/ashare-ai-slowbull/YYYY-MM-DD/`.
- Save only the final report as `runs/ashare-ai-slowbull/YYYY-MM-DD/YYYY-MM-DD.md`.
- Do not keep process data in `runs/`: no `data/`, no `scripts/`, no raw paginated responses, no normalized top200 CSV, no candidate CSV, no indicator CSV/JSON, and no temporary helper-script copies.
- The saved report must include the full final output: screening conclusion, core table, individual comments, final shortlist, buy-point observations, invalidation conditions, and risk note.
- The saved report must include a data-source section with source, fetch method, sort field, row count, and whether the top 200 is complete.
- If the date folder already exists for the same date, update `YYYY-MM-DD.md`; if preserving earlier versions matters, create timestamped Markdown files inside that date folder.
- If filesystem writing is unavailable, state that the archive could not be saved and still provide the final result in the response.

## Prompt Template

When the user asks for an example prompt, provide:

```text
请使用“A股AI硬件上游二线慢牛标的筛选Skill”，
在A股收盘后，从今日A股成交金额前200名中，
筛选AI硬件上游方向的备选标的。

要求：
1. 不要把服务器整机厂作为A档核心标的；
2. 优先筛选光模块、光芯片、PCB、CCL、电子布、先进封装、连接器、液冷、电源、存储接口等上游方向；
3. 总市值优先500亿至2000亿；
4. 剔除涨幅过大的头部AI硬件；
5. 优先找慢牛趋势、强势盘整、基本面良好或有巨大变化的二线品种；
6. 给出A/B/C分档、评分、入选理由、剔除理由和买点观察；
7. 成交额数据限定为今日A股成交金额前200名；
8. 仅在收盘后执行，并明确run_time、trade_date和quote_ticktime；
9. 优先使用新浪财经接口按成交额amount倒序分页取满200条，但不在 runs/ 中保存原始数据或top200 CSV；
10. 先判断板块处于主升、分歧、修复还是退潮；
11. 使用本地AI硬件上游股票池或产业链关键词筛选候选，并按S/A/B纯度分层；
12. 使用涨幅、均线偏离、RSI、MACD/KDJ、量能和平台整理的量化阈值；
13. 当日涨幅>=9.5%、RSI>80、MA20偏离>25%、市值>3000亿时执行硬降级或剔除；
14. 区分财报验证、公告/调研验证、互动平台弱验证和无验证；
15. 将MACD/KDJ金叉死叉作为技术动量加减分项，不作为单独买卖依据；
16. 输出最终短名单，并说明哪些适合等回踩，哪些只适合观察，以及观察失效条件；
17. 执行完成后，只在 runs/ashare-ai-slowbull/YYYY-MM-DD/ 下保存 YYYY-MM-DD.md，不保存 data/、scripts/ 或过程数据。
```
