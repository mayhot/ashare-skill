---
name: ashare-kline-sqlite-cache
description: Build and maintain a SQLite cache of full-market A-share daily K-line data plus A-share popularity top 100 snapshots. Use when the user asks to fetch, initialize, update, schedule, inspect, or repair A-share daily OHLCV/K-line data for the whole A market, especially tasks requiring daily post-close syncs after 17:00 China time, one-time historical backfill, rich Eastmoney-style fields, SQLite storage, retaining the latest 126 trading days, or fetching today's popularity/hot-stock ranking without historical backfill.
---

# A-share K-line SQLite Cache

Use this skill to maintain a local SQLite database of full-market A-share daily K-line data and popularity top 100 snapshots for research workflows. The bundled script handles one-time historical K-line initialization, daily incremental updates, field normalization, failure logging, K-line retention during historical initialization, and popularity ranking replacement for the requested trade date only.

## Quick Start

Run from the repository root:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode auto
```

Default output:

```text
runs/ashare-kline-sqlite-cache/ashare_kline.sqlite
```

For the first full historical pull:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode init
```

For the normal daily post-close job:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode daily
```

The default daily guard only allows same-day runs after 17:00 Asia/Shanghai. Use `--allow-before-close` only for tests, non-trading-day repairs, or explicit user requests.

## Workflow

1. Confirm the intended trade date. If the user says "today", use the current Asia/Shanghai date and prefer running after 17:00.
2. Run `sync_ashare_kline.py`.
   - `--mode auto`: use `init` when the database is empty, otherwise use `daily`.
   - `--mode init`: fetch enough calendar days to seed at least 126 trading days, then prune.
   - `--mode daily`: fetch only the recent window for all A-share symbols and upsert.
3. Check the console summary for `stock_count`, `rows_upserted`, `failures`, `latest_dates`, and `database`.
4. If failures are non-zero, inspect `fetch_failures` in SQLite before relying on a complete market snapshot.
5. Apply K-line retention pruning only during historical initialization (`mode=init`). Daily scheduled runs must not delete historical `daily_kline` dates.
6. Fetch popularity ranking only for the requested `trade_date`; do not backfill historical popularity rankings.
   Replacement and failure cleanup only delete rows for the requested `trade_date`; existing historical popularity rows are left untouched.

## Data Fields

The script stores the richest stable Eastmoney daily K-line fields exposed by the public endpoint:

```text
code, trade_date, name, exchange,
open, close, high, low, volume, amount,
amplitude, pct_chg, change_amount, turnover,
source, fetched_at, raw_line
```

It also stores a latest market snapshot/universe table with fields such as latest price, percentage change, volume, amount, amplitude, high, low, open, previous close, volume ratio, turnover, PE, PB, total market value, circulating market value, speed, 5-minute change, 60-day change, YTD change, and raw JSON when available.

The popularity table stores top 100 snapshots by trade date. The script fetches only the requested day and does not backfill historical popularity data:

```text
trade_date, rank, code, name, exchange,
hot_value, rank_change, latest_price, pct_chg,
source, fetched_at, raw_json
```

Data source priority is built for resilience: use Eastmoney first for richer K-line fields, fall back to Tencent daily K-line when Eastmoney returns empty or fails, use Eastmoney app ranking for popularity top 100, and fall back to Sina for the stock universe when the richer universe endpoint is unavailable. Pass `--prefer-akshare` only when the local environment has AkShare installed and the user explicitly wants to try it first.

## SQLite Tables

- `stock_universe`: latest full-market symbol list and rich spot fields.
- `daily_kline`: normalized daily K-line rows keyed by `(code, trade_date)`.
- `popularity_top100`: popularity top 100 snapshots keyed by `(trade_date, rank)`; sync replaces only the requested trade date.
- `sync_runs`: run metadata, mode, counts, retained window, and latest-date summary.
- `fetch_failures`: per-symbol failures for the run.

Use parameterized SQL when querying or extending the script. Do not parse SQLite output with ad hoc string slicing.

## Deletion Rules

Daily scheduled jobs must only clear or delete rows for the requested `trade_date`.

- Allowed in `daily`: replacing current-day `popularity_top100` rows, or clearing current-day popularity rows when that fetch fails.
- Allowed in `init`: historical K-line backfill and retention pruning to the latest 126 trading dates.
- Not allowed in `daily`: deleting older `daily_kline` dates, deleting older `popularity_top100` dates, or running broad cleanup statements without a `trade_date` predicate.

## Common Commands

Initialize or repair history for all A shares:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode init `
  --retain-trading-days 126
```

Run a daily sync for a specific date:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --trade-date 2026-06-04
```

Run a small development sample:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --limit 20 `
  --allow-before-close
```

Run a fixed-symbol development sample without fetching the full market universe:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --symbols 000001,600000 `
  --symbols-only `
  --popularity-limit 5 `
  --allow-before-close
```

Run K-line only without refreshing popularity:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --skip-popularity
```

Use a custom database path:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --db runs/ashare-kline-sqlite-cache/dev.sqlite `
  --mode auto
```

## Scheduling

Prefer scheduling the script at or after 17:00 China time on trading days. On Windows Task Scheduler, use:

```powershell
python D:\Code\q-skills\ashare-skill\ashare-kline-sqlite-cache\scripts\sync_ashare_kline.py --mode auto
```

Set the working directory to:

```text
D:\Code\q-skills\ashare-skill
```

For cron-like environments:

```cron
5 17 * * 1-5 cd /path/to/ashare-skill && python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode auto
```

Still keep the script's time guard enabled; it prevents accidental same-day pre-close cache pollution.

## Validation

Before finishing a task with this skill:

1. Run the self-test after script edits:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --self-test
```

2. Confirm `daily_kline` has no more than 126 distinct `trade_date` values after `mode=init`; do not require this check after `mode=daily`, because daily jobs must not prune older dates.
3. Confirm `popularity_top100` has no duplicate ranks for the requested `trade_date`, and normally exactly 100 rows for that date after a successful live sync.
4. Confirm recent dates have broad symbol coverage; a large `fetch_failures` count means the market cache is incomplete.
5. State clearly whether the data came from live network fetches or only from self-test/sample mode.

## Guardrails

- Do not invent K-line rows, prices, volumes, or trade dates.
- Do not carry forward yesterday's popularity ranking as today's ranking. If the popularity endpoint fails, clear only the requested `trade_date` rows and report the failure.
- Do not treat the cache as investment advice; it is a research data store only.
- Keep database files under `runs/ashare-kline-sqlite-cache/` unless the user specifies another path.
- If public endpoints fail or rate-limit, report the failure count and retry later rather than filling gaps manually.
