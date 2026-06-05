---
name: ashare-kline-sqlite-cache
description: Build and maintain a SQLite cache of full-market A-share daily K-line data plus A-share popularity top 100 snapshots. Use when the user asks to fetch, initialize, update, schedule, inspect, or repair A-share daily OHLCV/K-line data for the whole A market, especially tasks requiring same-day syncs from 15:30 through 23:59:59 China time, one-time historical backfill, rich Eastmoney-style fields, SQLite storage, retaining the latest 126 trading days, or fetching today's popularity/hot-stock ranking without historical backfill.
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

Seed historical K-line rows from an existing CSV before fetching missing data:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode init `
  --seed-kline-csv runs/ashare-volume-doubled-uptrend/kline-cache/daily_kline_6m.csv
```

For the normal daily post-close job:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode daily
```

The default daily guard allows same-day runs from 15:30 through 23:59:59 Asia/Shanghai. Use `--allow-before-close` only for tests, non-trading-day repairs, or explicit user requests.

## Workflow

1. Confirm the intended trade date. If the user says "today", use the current Asia/Shanghai date and prefer running after 15:30.
2. Run `sync_ashare_kline.py`.
   - `--mode auto`: use `init` when the database is empty, otherwise use `daily`.
   - `--mode init`: fetch enough calendar days to seed at least 126 trading days, then prune.
   - `--mode daily`: fetch only the recent window for all A-share symbols and upsert.
   - `--seed-kline-csv`: import local K-line rows first, then fetch only missing symbols or each symbol's date gap after its latest cached K-line date.
   - `--universe-source official`: use official SSE/SZSE/BSE stock lists for the full-market universe. This is the default.
   - Official universe refreshes only on day 1 of each month by default. Other daily runs use the cached `stock_universe`; pass `--refresh-universe` to force refresh.
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
Official universe fields include `board`, `listing_date`, `industry`, `region`, and `official_source` when available.

The popularity table stores top 100 snapshots by trade date. The script fetches only the requested day and does not backfill historical popularity data:

```text
trade_date, rank, code, name, exchange,
hot_value, rank_change, latest_price, pct_chg,
source, fetched_at, raw_json
```

Data source priority is built for resilience: use official exchange lists for the universe, Tencent first for K-line speed, fall back to Eastmoney when Tencent returns empty or fails, and use Eastmoney app ranking for popularity top 100 with optional AkShare fallback. Use `--universe-source market` only when the user explicitly accepts market-data-source stock lists instead of official exchange lists.

## Multi-Source Auto Switching

Keep source switching automatic by default:

- K-line default: `--kline-sources auto`, equivalent to `tencent,eastmoney`.
- Popularity default: `--popularity-sources auto`, equivalent to `eastmoney,akshare`.
- Universe default: `--universe-source official`, using cached official exchange lists except on the monthly refresh day.

Override source order only when diagnosing vendor outages:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --kline-sources eastmoney,tencent `
  --popularity-sources akshare,eastmoney
```

Every normalized K-line row stores its actual source in `daily_kline.source`; popularity rows store their actual source in `popularity_top100.source`.
Progress logs also show K-line source counts, fallback count, and average successful source latency so slow or failing vendors are visible during a long run.

## Public Endpoint Stability

Public market-data endpoints can return timeouts, empty responses, or rate-limit style failures during full-market runs. Keep the default conservative network policy unless diagnosing runtime:

- `--max-workers` defaults to `4` to reduce request bursts.
- `--request-attempts` defaults to `4`.
- `--retry-base-sleep` and `--retry-max-sleep` control exponential backoff after failed HTTP requests.
- `--request-delay` and `--request-jitter` add a shared cross-thread delay between public endpoint requests.

If failures remain high, reduce concurrency and increase pacing before retrying:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --max-workers 2 `
  --request-timeout 30 `
  --request-attempts 5 `
  --request-delay 0.25 `
  --request-jitter 0.35 `
  --retry-base-sleep 1 `
  --retry-max-sleep 20
```

## Official Universe Sources

Use the three official exchange lists as the default full-market universe, but do not fetch them on every daily run. Refresh the official universe on the 1st day of each month, or when `--refresh-universe` is passed. On other days, use the cached official rows in `stock_universe`.

- SSE: main-board A shares and STAR Market, from the Shanghai Stock Exchange stock list.
- SZSE: A-share list, from the Shenzhen Stock Exchange stock list.
- BSE: listed-company stock list, from the Beijing Stock Exchange list.

The script calls these via AkShare's exchange-list wrappers so the normalized output can be merged into `stock_universe`. Exclude B shares by only requesting SSE main-board A shares, SSE STAR Market, SZSE A-share list, and BSE listed shares.

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
  --seed-kline-csv runs/ashare-volume-doubled-uptrend/kline-cache/daily_kline_6m.csv `
  --universe-source official `
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

For long full-market runs, keep progress output frequent:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --progress-every 50 `
  --progress-seconds 10
```

Run with extra endpoint pacing when rate-limit or timeout failures appear:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --max-workers 2 `
  --request-delay 0.25 `
  --request-jitter 0.35 `
  --request-timeout 30
```

Use a custom database path:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --db runs/ashare-kline-sqlite-cache/dev.sqlite `
  --mode auto
```

## Scheduling

Prefer scheduling the script at or after 15:30 China time on trading days. On Windows Task Scheduler, use:

```powershell
python D:\Code\q-skills\ashare-skill\ashare-kline-sqlite-cache\scripts\sync_ashare_kline.py --mode auto
```

Set the working directory to:

```text
D:\Code\q-skills\ashare-skill
```

For cron-like environments:

```cron
30 15 * * 1-5 cd /path/to/ashare-skill && python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode auto
```

Still keep the script's time guard enabled; it prevents accidental same-day cache writes before 15:30.

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
