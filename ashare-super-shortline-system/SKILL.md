---
name: ashare-super-shortline-system
description: Turn the article "职业超级短线交易系统" into an executable A-share super-short-term trading discipline. Use when the user asks for 超级短线、职业短线、短线交易系统、短线买点、账户红绿线、月/周/日盈利目标、短线心态检查、下单战术、短线复盘, or wants a checklist-style trading plan based on the article. This skill produces research and discipline checklists, not personalized investment advice.
---

# A股职业超级短线交易系统

Use this skill to convert the article's ideas into a repeatable short-term trading workflow. The system is about survival, compounding, discipline, and execution quality, not fantasy returns. Always adapt conclusions to the user's capital size, personality, market experience, and current market conditions.

This skill must use conditional, research-only language. Do not write "must buy", "guaranteed profit", or personalized investment advice.

## Executable Quick Start

Prefer the bundled script whenever the user provides candidate stock names/codes or structured market/account/candidate data. The script turns inputs into an executable discipline report with gates, public K-line derived fields, scores, classifications, position ceilings, and a Markdown output.

Most common use: the user gives only candidate codes/names plus private account state.

```powershell
python ashare-super-shortline-system/scripts/build_shortline_plan.py `
  --symbols 300308,300502,603986 `
  --market-phase rising `
  --money-effect strong `
  --broad-index-month-pct 5.8 `
  --leading-themes CPO,AI `
  --account-month-return 8.5 `
  --account-week-return 2.0 `
  --max-single-position 25% `
  --trader-state calm `
  --output runs/ashare-super-shortline-system/YYYY-MM-DD/YYYY-MM-DD.md
```

For Chinese stock names, prefer a `--name-map` JSON/CSV when the name is not already in local context:

```json
{
  "新易盛": "300502",
  "中际旭创": "300308",
  "兆易创新": "603986"
}
```

```powershell
python ashare-super-shortline-system/scripts/build_shortline_plan.py --symbols 新易盛,中际旭创 --name-map path/to/name_map.json --account-json path/to/account.json
```

Use complete JSON when the user already provides manually judged pattern/trigger/invalidation fields:

```powershell
python ashare-super-shortline-system/scripts/build_shortline_plan.py --input path/to/shortline_input.json --output runs/ashare-super-shortline-system/YYYY-MM-DD/YYYY-MM-DD.md
```

If the user provides pasted text, screenshots, or a table, first normalize the private fields into CLI flags or the JSON shape below, then run the script. If there is not enough private account/psychology data, still fetch public stock data but mark account/psychology gates as unknown and reduce aggressiveness.

Minimum executable JSON:

```json
{
  "date": "2026-06-01",
  "market_phase": "rising",
  "money_effect": "strong",
  "broad_index_month_pct": 5.8,
  "leading_themes": ["AI", "CPO"],
  "account_month_return": 12.5,
  "account_week_return": 3.2,
  "max_single_position": "30%",
  "trader_state": "calm",
  "candidates": [
    {
      "code": "000001",
      "name": "示例股份",
      "theme": "AI",
      "pattern": "breakthrough",
      "trigger": "放量突破平台且回落不破平台上沿",
      "invalidation": "跌回平台上沿且次日无法修复",
      "invalidation_distance_pct": 4.5,
      "volume_state": "confirmed",
      "liquidity": "good"
    }
  ]
}
```

Supported `pattern` values:

```text
breakthrough, sector_leader_ignition, airborne_add, pre_launch_dig,
bull_volume, slowbull_neighbor, continuous_strong, board_follow,
platform_reentry, hot_market_safe, super_pullback
```

The script must be treated as the first-pass executor. Codex may then add a concise human review, but should not override a red gate or rejected candidate without explaining the missing evidence.

The script automatically derives these public fields from A-share daily K-lines when `--symbols` is used:

- latest close and latest K-line date
- MA5/10/20/60 relationship
- distance from MA20 or platform high
- volume confirmation
- basic pattern guess: `breakthrough`, `continuous_strong`, `platform_reentry`, `bull_volume`, or blank when no system buy point is visible
- invalidation line and invalidation distance

The user should still provide private fields that cannot be fetched: account returns, current position/risk ceiling, goal reached or not, and trader state.

## Source And Task Modes

When the user provides a screenshot/article, extract the written trading rules first. Ignore illustrations, ads, and unrelated UI elements unless the user explicitly asks about them.

Choose one mode before answering:

| Mode | Use When | Output |
|---|---|---|
| System extraction | User provides the article or asks to summarize the method | Reusable rulebook and checklist, no stock names unless supplied |
| Daily planning | User provides market/account/date context | Market gate, account state, allowed action, candidate table |
| Candidate review | User provides one or more stocks | Pattern match, invalidation, size ceiling, pass/fail decision |
| Intraday discipline | User asks whether to chase/add/cut during trading | Fast gate: market, theme, pattern, risk line, psychology |
| Post-market review | User provides trades or account result | Execution audit, mistake type, next-day rule |

If the user does not provide current market data or candidate stocks, do not invent them. Produce a reusable plan/checklist and ask for the missing inputs only if needed for a concrete trading decision.

## Required Inputs For Concrete Plans

For a daily or candidate-specific plan, prefer these fields:

```text
date, account_month_return, account_week_return, recent_3day_pnl,
cash_ratio, max_single_position, broad_index_month_pct,
market_phase, leading_themes, candidates,
candidate_code, candidate_name, theme, latest_price,
recent_pct, volume_state, pattern, support_or_invalidation,
trader_state
```

If some inputs are missing, mark the conclusion as `信息不足，仅可做纪律框架`. Missing data must reduce aggressiveness, not invite speculation.

Normalize natural-language values before running the script:

| Chinese Input | JSON Value |
|---|---|
| 上涨/强势 | `rising` or `strong` |
| 震荡/分化 | `range` or `mixed` |
| 下跌/弱势 | `falling` or `weak` |
| 赚钱效应强 | `strong` |
| 赚钱效应一般 | `mixed` |
| 赚钱效应差 | `weak` |
| 冷静/有计划 | `calm` |
| 兴奋/犹豫/疲惫 | `excited`, `hesitant`, or `tired` |
| 焦虑/恐慌/报复/上头 | `panic`, `fear`, `revenge`, or `fomo` |

## Core Principles

- Protect principal first. The bottom line is not losing money when the market has no clear opportunity.
- Treat the system as a personal discipline, not a public formula. The article stresses that the method must be adjusted to the trader's character, account size, and experience.
- Reject unrealistic thinking such as "annual 500%" or blindly chasing black-horse stocks.
- Use super-short trading to pursue high capital efficiency only when market conditions, account state, and buy point quality align.
- Stop, rest, or shrink exposure when the account curve, market environment, or psychology becomes unhealthy.

## Goal System

Set goals by market environment, not by desire.

### Monthly Goals

| Market Environment | Reference | Account Goal | Operating Posture |
|---|---|---:|---|
| Strong market | Broad index monthly gain above +5% | +30% or more | Active, but still rule-based |
| Range market | Broad index between -5% and +5% | About +20% | Selective, focus on strongest opportunities |
| Weak market | Broad index below -5% | Preserve capital, near 0% is acceptable | Stop trading, go short-term empty, or use very small test size |

If a clear high-quality opportunity appears during the period, the tactical profit goal for operating capital can be set around +10%, with "no loss" as the first rule.

### Weekly Goals

- When actively trading, use about +10% as the weekly goal and use outperforming the broad market as a basic benchmark.
- If the weekly goal is already reached, reduce aggression. Do not let excitement turn profits into pressure.
- If the account shows weekly loss around -8% or one full bad week, stop or shrink positions, clear the trading state, and review the cause.
- If the monthly goal is already achieved, consider resting for about one week instead of forcing more trades.
- The ideal account curve is small gains/small losses with occasional large gains, not frequent large drawdowns.

### Daily Goals

- After two consecutive strong-profit days, the third day must be conservative; inspect whether the account is overheated.
- Multiple negative days, big losing days, or loss of rhythm means stop trading and review before the next order.
- Daily operation should be tied to market opportunity and account state, not to a fixed urge to trade.

## Trading Permission Gate

Before evaluating any stock, decide whether trading is allowed today:

| Gate | Green | Yellow | Red |
|---|---|---|---|
| Market | Main index and leading themes have money-making effect | Mixed market, only a few leaders work | Broad weakness or fast distribution |
| Account | Month/week curve healthy and drawdown controlled | Slight damage or goal already close | Weekly loss near -8%, one bad week, or account rhythm broken |
| Psychology | Calm, prepared, accepts invalidation | Excited or hesitant but aware | Revenge trading, fear of missing out, panic, major distraction |
| Candidate | Clear named pattern and close risk line | Pattern exists but confirmation weak | No named pattern, late chase, or invalidation far away |

Action by gate:

- All green: allow normal short-term research plan.
- Any yellow: reduce size or wait for confirmation.
- Any red: no new aggressive trade; use observation or review.

## Pre-Trade Decision Tree

Before any order, answer in order:

1. Market phase: Is the market in rising, range-bound, or falling state?
2. Policy and news: Is the environment supportive, uncertain, or risk-heavy?
3. Funds and theme: Are institutions, hot-money desks, and retail participants in attack, pullback, or distribution mode?
4. Hot spots: Which themes or leading stocks are currently strongest?
5. Account state: Is the account in a healthy green-line state or a warning red-line state?
6. Psychology: Is the trader calm, excited after profit, panicked after loss, or distracted by life events?
7. Buy point: Does the stock match a named buy pattern below?
8. Risk line: What invalidates the trade?
9. Size: What is the maximum size if the setup is confirmed?

If any answer is vague, the default action is `wait`, not `force a trade`.

## Account And Psychology Check

Classify the account before selecting stocks:

| State | Meaning | Action |
|---|---|---|
| Healthy green line | Smooth curve, controlled drawdown, clear rhythm | Trade only high-quality setups |
| Warning red line | Recent losses, emotional pressure, unclear rhythm | Reduce size, stop after mistakes, review |
| Rest state | Reached goal or suffered clear damage | No new aggressive trades |

Check these causes when the account turns red:

- Is the market itself lacking money-making opportunities?
- Is the trading psychology broken by greed, fear, urgency, or revenge trading?
- Is the execution rhythm wrong, such as buying late, selling late, or chasing without a plan?

Do not trade aggressively while excited after large gains or anxious after losses. The article treats mentality as part of the system, not a side note.

## Buy Point Playbook

Use only named patterns. Each trade must map to one pattern and one invalidation line.

| Pattern | Trigger | Required Confirmation | Main Risk |
|---|---|---|---|
| Breakthrough pattern buy | Stock breaks a clear technical pattern or platform | Breakout is recognized by volume and price, and does not immediately fail | False breakout |
| Sector leader ignition | A theme leader or hot stock suddenly becomes strong for the first time | Theme has market attention and the leading stock is identifiable | Chasing after the first wave is exhausted |
| Strong-stock airborne add | Strong stock continues in mid-air strength | Trend remains intact and pullback is shallow | Buying into exhaustion |
| Pre-launch digging buy | Price dips or shakes out before a likely market/theme start | The decline looks like preparation rather than breakdown | Misreading true weakness as a shakeout |
| Bull-market volume buy | In a hot bull phase, a strong bullish candle appears with major volume | Market is broadly hot and the stock is in a recognized hot theme | Late-stage climax |
| Slow-bull neighbor buy | Related slow-bull names show signs of rapid start | Same theme or comparable logic is recognized by the market | Weak follower trap |
| Strong-stock continuous operation | A strong stock remains tradable for 1-2 weeks | Buy intraday pullbacks, not emotional highs | Profit fracture after trend fatigue |
| Board-strength follow buy | Theme board is strong and the leader creates clear profit space | Followers have enough room only when the leader is still powerful | Buying weak followers too late |
| Platform re-entry | Strong stock enters a platform after earlier strength | Platform holds for about 1-2 weeks and restarts | Platform breakdown |
| Hot-market safe point | In a very hot market, broad indexes and hot leaders start together | Prefer safer buy points in the hottest line for 3-5 days | Market-wide reversal |
| Super-strong pullback | Super-strong stock shrinks volume after several days | One safe rebound point appears after a strong rise | Only attempt once; do not cling |

Rules:

- The buy point must come from the market's strongest current direction, not from personal preference.
- Late chasing is not a buy point unless the pattern explicitly supports it and the risk line is close.
- If a strong stock has already given the easy profit, downgrade to observation.
- If the setup cannot explain where to exit, do not enter.

## Candidate Scoring

Use scoring to keep the plan consistent. Scores guide discipline; hard-stop rules still override.

| Dimension | Weight | What To Check |
|---|---:|---|
| Market permission | 15 | Is today suitable for super-short trading? |
| Theme strength | 15 | Is the candidate in the strongest active direction? |
| Buy point quality | 20 | Does it match a named pattern with clear trigger? |
| Risk line quality | 15 | Is invalidation close, visible, and acceptable? |
| Volume-price confirmation | 10 | Is strength supported rather than exhausted? |
| Account state | 10 | Is the account green-line enough to act? |
| Psychology | 10 | Is the trader calm and rule-following? |
| Liquidity and A-share constraints | 5 | Avoid illiquidity, limit-up traps, and impossible exits |

Classification:

| Score | Classification | Action |
|---:|---|---|
| 85+ | A setup | Can plan conditional action if no hard stop appears |
| 70-84 | B setup | Watchlist or small test after confirmation |
| 55-69 | C setup | Observe only |
| Below 55 | Reject | No trade |

Do not upgrade a stock above B if market permission, account state, or psychology is red.

## Position Rules

Use position size as a risk-control output, not a reward for conviction.

| Setup Quality | Suggested Research Size Ceiling |
|---|---:|
| High-quality confirmed setup in strong market | 20%-30% of short-term account |
| Good setup in range market | 10%-20% |
| Test setup or uncertain rhythm | 5%-10% |
| Weak market, red-line account, or unclear psychology | 0%-5% or no trade |

Never increase size after an emotional loss. Never add size simply because the monthly or weekly target has not been met.

A-share execution constraints:

- Consider T+1 and the inability to sell shares bought the same day.
- Treat limit-up entries, one-word boards, and poor liquidity as execution risks, not just opportunities.
- Avoid plans that require perfect intraday fills.
- Prefer close, observable invalidation levels over vague "watch tomorrow" wording.

## Sell And Stop Discipline

The screenshot focuses more on goals, account state, and buy tactics than detailed sell techniques. Therefore, when using this skill, derive exits conservatively:

- Predefine invalidation before entry: failed breakout, loss of platform, theme collapse, or broad-market turn.
- If the reason for buying disappears, exit or reduce.
- If a trade quickly moves against the plan, do not average down unless a new valid buy point appears.
- If profit target is reached faster than expected, protect part of the gain and avoid turning a green-line account into a red-line account.
- If the account hits weekly or monthly damage thresholds, stop new trades first; individual stock hope is secondary.

## Daily Execution Loop

Use this loop for actionable trading days:

1. Pre-market: identify market phase, themes, risk events, and whether trading is allowed.
2. Watchlist: keep only candidates with named patterns and close invalidation.
3. Intraday: act only when trigger, theme, volume-price behavior, and account state align.
4. Post-entry: immediately record entry reason, invalidation, expected holding window, and size.
5. Exit/reduce: follow invalidation, goal protection, theme failure, or account damage rules.
6. Post-market: classify every action as `按系统执行`, `买点错误`, `卖点错误`, `仓位错误`, or `心态错误`.

For the next day, convert the review into one concrete rule, such as `不追高`, `只做龙头`, `跌破平台不补仓`, or `达成周目标后减速`.

## Operating Output Template

Use this shape for plans:

```markdown
# 职业超级短线交易计划
日期：
结果类型：研究纪律清单，不构成个性化投资建议

## 1. 大盘与环境
- 阶段：上涨 / 震荡 / 下跌
- 指数月度位置：
- 政策与消息：
- 当前主线：
- 是否适合超级短线：

## 2. 账户红绿线
- 本月收益：
- 本周收益：
- 近3日节奏：
- 当前状态：健康绿线 / 预警红线 / 休息
- 今日允许动作：进攻 / 轻仓试错 / 只看不做 / 停止交易

## 3. 今日目标
- 月目标：
- 周目标：
- 日目标：
- 最大亏损容忍：
- 达标后的休息或降速规则：

## 4. 候选交易清单
| 优先级 | 标的 | 代码 | 所属主线 | 买点模式 | 评分 | 触发条件 | 失效条件 | 计划仓位 | 处理 |
|---:|---|---|---|---|---:|---|---|---:|---|

## 5. 下单前最后检查
- 是否属于当前最强方向：
- 是否有明确买点名称：
- 是否有明确失效位：
- 是否因为贪婪/恐惧/报复交易而下单：
- 若失败，是否仍能保持账户绿线：

## 6. 盘后复盘
- 执行是否符合计划：
- 买点是否真实：
- 仓位是否过重：
- 心态是否变形：
- 明日第一动作：
```

## Hard Stop Rules

Stop trading or shrink to observation when:

- Broad market is weak and there is no clear money-making effect.
- Weekly account loss is near -8% or the account has one clearly bad week.
- The trader is excited, anxious, revenge-trading, or distracted by major life events.
- No candidate maps to a named buy pattern.
- Profit targets are already achieved and continued trading is only for stimulation.
- The market has already moved from opportunity phase into distribution or exhaustion.

## Final Self-Check

Before delivering an answer:

- Every suggested action must include market state, account state, buy pattern, invalidation, and size ceiling.
- Do not promise returns. Goals are discipline references, not guarantees.
- Separate `can trade today` from `has a candidate stock`; both must be true for an active plan.
- Label the output as research and discipline only.
- If the user only provided the screenshot article and no market data, produce a reusable system/checklist rather than naming stocks.
- If outputting a concrete plan, each candidate must have a score/classification and a pass/wait/reject decision.
