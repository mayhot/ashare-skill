---
name: ashare-recommendation-returns
description: Track and summarize post-recommendation returns for the daily output of the local A-share skills ashare-trend-buy and ashare-ai-slowbull. Use when the user asks to calculate recommended stock performance through a given date, write return CSV files into each source skill's run date directory, process historical date folders day by day, or produce 5/10/20 trading-day return summaries for those recommendation results.
---

# A-Share Recommendation Return Tracking

Use this skill to calculate how the recommended stocks from `ashare-trend-buy` and `ashare-ai-slowbull` performed after each daily screening run. Treat this as research-performance tracking, not investment advice.

## Quick Start

Run the bundled script from the repository root:

```powershell
python ashare-recommendation-returns/scripts/calc_recommendation_returns.py --repo-root . --as-of 2026-05-22
```

The script processes these source run folders:

```text
runs/ashare-trend-buy/YYYY-MM-DD/
runs/ashare-ai-slowbull/YYYY-MM-DD/
```

For each source date folder it writes:

```text
data/recommendation-returns.csv
data/recommendation-returns-summary.csv
```

It also writes consolidated audit files under:

```text
runs/ashare-recommendation-returns/YYYY-MM-DD/
```

## Default Recommendation Definition

By default, count only A/B grade rows as recommendations:

- `ashare-trend-buy`: read `data/scored-candidates.csv` and keep rows where `tier` is `A` or `B`.
- `ashare-ai-slowbull`: read `data/candidates.csv` and keep rows where `grade` is `A` or `B`.
- If the structured CSV is missing, parse the Markdown report table and keep rows whose tier/grade cell is `A` or `B`.

If the user wants C-grade tracking too, pass:

```powershell
python ashare-recommendation-returns/scripts/calc_recommendation_returns.py --repo-root . --include-grades A,B,C
```

## Return Calculation Rules

Use each source row's own recommendation base price when available:

- `close` for `ashare-trend-buy`
- `trade` for `ashare-ai-slowbull`

Use the source row's `date` field as the base price date when available; otherwise use the run folder date. Fetch forward-adjusted daily K-line data from Tencent to find the latest close on or before `--as-of`.

Calculate:

```text
return_pct = (asof_close / base_price - 1) * 100
```

Also calculate 5/10/20 trading-day horizon returns when enough daily bars exist after the base date. Mark horizon rows as `pending` until the horizon is reached.

## Outputs

`recommendation-returns.csv` is daily row-level tracking. It must contain at least:

```text
date,stock_name,code,daily_price,return_since_buy_pct,buy_date,buy_price,
source_skill,run_date,grade,score,elapsed_trading_days,status
```

Each recommended stock can have multiple rows, one row per available trading day from the buy/base date through `--as-of`.

`recommendation-returns-summary.csv` is the per-date summary. It includes `asof`, `5d`, `10d`, and `20d` rows with count, average return, median return, win rate, best stock, and worst stock.

## Operating Notes

- Use `--start-date` and `--end-date` to process only part of history.
- Use `--source-skill ashare-trend-buy` or `--source-skill ashare-ai-slowbull` to process one skill.
- Use `--dry-run` to inspect extraction and calculations without writing CSV files.
- Use `--no-fetch` for offline validation. This only uses local base prices and marks forward returns as unavailable unless the as-of date equals the local price date.
- Keep generated CSV files under the original source date folders so later review can start from the recommendation day.

## Quality Checks

Before reporting completion:

1. Confirm the script found the intended date folders.
2. Confirm at least one recommendation row was extracted when the source report contains A/B rows.
3. Confirm `recommendation-returns.csv` and `recommendation-returns-summary.csv` were written in each processed source date folder unless `--dry-run` was used.
4. If network price fetches failed, report the affected codes and statuses instead of silently treating missing data as zero return.
