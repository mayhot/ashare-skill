---
name: ashare-index-inclusion-watch
description: Screen the latest A-share mainstream index inclusion additions against latest-close turnover amount top 100 and stock popularity top 100 lists. Use when the user asks for 本轮主流指数调入成分股, 指数纳入/调入名单, 沪深300/中证500/上证50/科创50/创业板指等指数调样, excluding 中证1000 and 中证2000, then cross-checking against 成交额前100, 人气榜前100, 热股榜, or similar A-share liquidity and popularity ranking tasks.
---

# A股指数调入筛选

Use this skill to produce a research-only watchlist from the most recent mainstream A-share index constituent adjustment: index additions first, then intersections with latest-close turnover amount top 100 and popularity top 100.

Do not invent index adjustment lists, turnover rankings, popularity rankings, dates, or stock names. These inputs are time-sensitive; always verify with current sources or clearly state the missing data.

## Workflow

1. Confirm the run date, latest completed A-share trading day, and whether the market has closed. If the current day is not closed, use the latest completed trading day for 成交额 and 人气榜.
2. Find the latest published constituent adjustment round for mainstream A-share indices. Treat "本轮" as the most recent periodic or announced adjustment with a clear announcement/effective date.
3. Use the default index scope unless the user provides a specific list:
   - Include: 沪深300, 中证500, 中证A500, 上证50, 上证180, 科创50, 创业板指, 深证成指, 深证100, 创业板50.
   - Exclude: 中证1000, 中证2000. Do not include their additions even if they appear in the same公告 or data table.
   - If an included index has no latest adjustment or no additions in the latest round, report it as `无调入` or `未找到可靠公告`.
4. Build a deduplicated 调入成分股 universe keyed by 6-digit stock code. Keep every source index for each stock, because one stock may be added to multiple indices.
5. Query latest-close A-share 成交额前100. Use成交额/amount, not换手率, 成交量, or主力净流入. Record rank, amount, trade date, and source.
6. Query latest available A-share 人气榜前100. Prefer a named popularity/ranking source such as 东方财富人气榜, 同花顺热股榜, 雪球热股, or the user-specified source. Record rank, list timestamp/date, and source.
7. Join by stock code and output:
   - 调入股 ∩ 成交额前100
   - 调入股 ∩ 人气榜前100
   - 调入股 ∩ 成交额前100 ∩ 人气榜前100
8. Save the final Markdown report when working in this repository:

```text
runs/ashare-index-inclusion-watch/YYYY-MM-DD/YYYY-MM-DD.md
```

## Data Source Discipline

Use primary or clearly attributable sources:

- Index changes: prefer official index company/exchange announcements and constituent adjustment files, such as 中证指数有限公司, 上海证券交易所, 深圳证券交易所, 国证指数, or official index factsheets/downloads.
- Turnover amount: use a market data source that exposes full A-share ranking by latest trading day, such as 东方财富, 同花顺/iFinD, Wind, Choice, AkShare/Tushare-backed data, or a user-provided CSV.
- Popularity: use a source with an explicit top list/rank and timestamp. Because popularity榜口径 differs by vendor, name the source in every output.

If sources disagree:

- Prefer official index公告 for index additions.
- For turnover, prefer the source with latest complete close data and explicit成交额字段.
- For popularity, do not merge different vendor rankings unless the user asks. Choose one source, state it, and keep ranks from that source only.

If联网不可用 or a required source cannot be verified, do not guess. Ask for source files/links or report the exact missing input.

## Normalization Rules

- Normalize stock codes to 6 digits. Preserve exchange suffix only when needed for disambiguation, for example `600000.SH` or `000001.SZ`.
- Exclude B shares, Hong Kong stocks, ETFs, REITs, funds, indices, bonds, and suspended/non-stock rows.
- Keep stock name as reported by the latest market data source; if index公告 uses an older name, optionally note the alias.
- Deduplicate 调入股 by code; aggregate `调入指数` as a comma-separated list.
- For 成交额前100, retain only rank 1-100 after filtering to A-share stocks.
- For 人气榜前100, retain only rank 1-100 from the chosen popularity source.
- Do not treat "即将调入" and "已生效调入" as the same unless the report explicitly separates announcement date and effective date.

## Required Report

Use this Markdown shape:

```markdown
# A股主流指数调入交叉筛选
运行时间：
基准交易日：
指数调整轮次：
结果类型：研究观察池，不构成个性化投资建议

## 数据说明
- 指数调入来源：
- 指数范围：
- 明确排除：
- 成交额榜来源：
- 人气榜来源：
- 主要限制：

## 一、结果总览
| 分类 | 数量 | 说明 |
|---|---:|---|
| 本轮主流指数调入股去重 |  |  |
| 命中成交额前100 |  |  |
| 命中人气榜前100 |  |  |
| 同时命中成交额与人气榜 |  |  |

## 二、同时命中成交额前100与人气榜前100
| 代码 | 名称 | 调入指数 | 成交额排名 | 成交额 | 人气排名 | 调整公告日 | 生效日 | 备注 |
|---|---|---|---:|---:|---:|---|---|---|

## 三、命中成交额前100的调入股
| 代码 | 名称 | 调入指数 | 成交额排名 | 成交额 | 是否也在人气榜 | 调整公告日 | 生效日 |
|---|---|---|---:|---:|---|---|---|

## 四、命中人气榜前100的调入股
| 代码 | 名称 | 调入指数 | 人气排名 | 是否也在成交额榜 | 调整公告日 | 生效日 |
|---|---|---|---:|---|---|---|

## 五、完整调入名单
| 代码 | 名称 | 调入指数 | 调整公告日 | 生效日 | 成交额前100 | 人气榜前100 |
|---|---|---|---|---|---|---|

## 六、观察要点与风险
- 

以上为研究观察池，不构成个性化投资建议；实际交易需结合自身风险承受能力、最新行情和独立判断。
```

## Interpretation Guardrails

- Do not call a stock a buy candidate solely because it is added to an index or appears in a ranking.
- Explain index inclusion as a possible passive fund/rebalance attention factor, not guaranteed inflow.
- Treat成交额前100 as liquidity/attention evidence, not strength by itself.
- Treat人气榜前100 as crowd attention evidence, not fundamental validation.
- Highlight names that only appear in popularity but lack turnover confirmation as higher noise.
- For stocks that appear in both turnover and popularity intersections, describe them as "关注度与流动性同时较高的调入股".

## Validation

Before finishing:

1. Confirm 中证1000 and 中证2000 additions are absent from all result tables.
2. Confirm every listed stock is an actual 调入成分股 from the chosen latest adjustment round.
3. Confirm 成交额排名 and 人气排名 are both top 100 when marked `是`.
4. Confirm all dates are explicit: run time, benchmark trade date, announcement date, and effective date when available.
5. Confirm every data source is named with link or file path when possible.
6. Confirm the final answer and saved Markdown report contain the same core tables.
