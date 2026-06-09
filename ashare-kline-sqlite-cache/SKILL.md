---
name: ashare-kline-sqlite-cache
description: Build and maintain a SQLite cache of full-market A-share daily K-line data plus A-share popularity top 100 and turnover top 200 snapshots. Use when the user asks to fetch, initialize, update, schedule, inspect, or repair A-share daily OHLCV/K-line data for the whole A market, especially tasks requiring same-day syncs from 15:30 through 23:59:59 China time, one-time historical backfill, rich Eastmoney-style fields, SQLite storage, retaining the latest 126 trading days, today's ranking snapshots, or separate turnover ranking snapshots.
---

# A-share K-line SQLite Cache

Use this skill to maintain a local SQLite database of full-market A-share daily K-line data, popularity top 100 snapshots, and turnover top 200 snapshots for research workflows. The bundled script handles one-time historical K-line initialization, daily incremental updates, field normalization, failure logging, K-line retention during historical initialization, and ranking-snapshot replacement for the requested trade date only.

## Quick Start

Run from the repository root:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --mode auto
```

Default output:

```text
runs/ashare-kline-sqlite-cache/ashare_kline.sqlite
```

Default K-line fallback uses mootdx, TickFlow, and BaoStock. If a fresh environment is missing them, install before full-market runs:

```powershell
pip install mootdx tickflow baostock
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

Repair only K-line gaps for an already initialized trade date:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --repair-missing `
  --trade-date 2026-06-05 `
  --repair-chunk-size 150 `
  --skip-popularity
```

The default daily guard allows same-day runs from 15:30 through 23:59:59 Asia/Shanghai. Use `--allow-before-close` only for tests, non-trading-day repairs, or explicit user requests.

## Workflow

1. Confirm the intended trade date. If the user says "today", use the current Asia/Shanghai date and prefer running after 15:30.
2. Run `sync_ashare_kline.py`.
   - `--mode auto`: use `init` when the database is empty, otherwise use `daily`.
   - `--mode init`: fetch enough calendar days to seed at least 126 trading days, then prune.
   - `--mode daily`: fetch only the recent window for all A-share symbols and upsert.
   - `--seed-kline-csv`: import local K-line rows first, then fetch only missing symbols or each symbol's date gap after its latest cached K-line date.
   - `--universe-source official`: use CSI All Share / 中证全指 (`000985`) constituents for `stock_universe`. This is the default.
   - The CSI All Share universe refreshes only on day 1 of each month by default. Other daily runs use cached `stock_universe` rows tagged `official_source='CSI000985'`; pass `--refresh-universe` to force refresh.
3. Check the console summary for `stock_count`, `rows_upserted`, `failures`, `latest_dates`, and `database`.
4. If failures are non-zero, inspect `fetch_failures` in SQLite before relying on a complete market snapshot.
5. Apply K-line retention pruning only during historical initialization (`mode=init`). Daily scheduled runs must not delete historical `daily_kline` dates.
6. Fetch popularity and turnover ranking only for today's trade date during/after the allowed same-day window; do not backfill historical ranking snapshots.
   Replacement and failure cleanup only delete rows for the requested `trade_date`; existing historical ranking snapshots are left untouched.

## Failed Run Repair

When a full-market run hangs, times out, or leaves partial same-day coverage, do not immediately rerun the whole market at high concurrency.

1. Confirm there is no stale Python sync process still writing the database. If `sync_runs.finished_at` has null rows, treat them as audit clues and verify the process list before starting another writer.
2. Check the requested trade date coverage against `stock_universe`, the latest K-line date summary, and `popularity_top100`/`turnover_top200` counts for the same trade date.
3. If popularity already has a valid snapshot, repair K-lines with `--repair-missing`; repair batches force `--symbols-only` and preserve existing ranking snapshots by using `--skip-popularity --skip-turnover-top200`.
4. Use bounded batches first. A typical repair command is:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --repair-missing `
  --trade-date 2026-06-05 `
  --repair-chunk-size 150 `
  --repair-max-batches 4 `
  --max-workers 4 `
  --request-timeout 12 `
  --request-attempts 2 `
  --request-delay 0.05 `
  --request-jitter 0.1
```

5. If bounded batches improve coverage, rerun without `--repair-max-batches` or with a higher limit. If a source repeatedly fails, switch source order only for diagnosis, for example `--kline-sources eastmoney`, `--kline-sources baostock`, or `--kline-sources tencent`.
6. Report final coverage as `cached_count / universe_count`, missing prefix distribution, latest K-line date summary, popularity/turnover row counts, and whether remaining gaps are public-endpoint failures. Do not fabricate rows for remaining gaps.

`--repair-missing` requires an existing `stock_universe`; run `--mode init` or a normal `--mode daily` first if the database is empty. The repair wrapper writes one normal `sync_runs` row per batch so failures can still be inspected in `fetch_failures`.

## Missing Grid Repair

Use `repair_missing_kline_grid.py` when the cache needs a two-dimensional completeness check across current `stock_universe` symbols and existing `daily_kline.trade_date` values. The script reports missing cells by symbol and by date. With `--repair`, it fetches each missing symbol over its first-to-last missing date range, filters the fetched rows back to the exact missing dates, and upserts only those rows into `daily_kline`.

Query gaps without network writes:

```powershell
python ashare-kline-sqlite-cache/scripts/repair_missing_kline_grid.py `
  --date-from 2026-06-01 `
  --date-to 2026-06-09 `
  --dry-run `
  --sample-limit 20
```

Run a bounded repair first:

```powershell
python ashare-kline-sqlite-cache/scripts/repair_missing_kline_grid.py `
  --date-from 2026-06-01 `
  --date-to 2026-06-09 `
  --repair `
  --max-symbols 30 `
  --max-workers 4 `
  --request-timeout 15 `
  --request-attempts 3 `
  --request-delay 0.12 `
  --request-jitter 0.18
```

Then remove `--max-symbols` for the full selected date range if the bounded repair improves coverage. Use `--trade-date YYYY-MM-DD` for one-day repair, or `--symbols 000001,600000` to constrain the repair to known symbols. Report the before/after `missing_grid_rows`, `symbols_with_missing_count`, `dates_with_missing_count`, source counts, and any failure sample. Do not treat remaining gaps as filled unless rows exist in `daily_kline`.

## Data Fields

The script stores the richest stable Eastmoney daily K-line fields exposed by the public endpoint:

```text
code, trade_date, name, exchange,
open, close, high, low, volume, amount,
amplitude, pct_chg, change_amount, turnover,
source, fetched_at, raw_line
```

It also stores a latest market snapshot/universe table with fields such as latest price, percentage change, volume, amount, amplitude, high, low, open, previous close, volume ratio, turnover, PE, PB, total market value (`total_mv`), circulating market value (`circ_mv`), speed, 5-minute change, 60-day change, YTD change, and raw JSON when available.
Official CSI All Share universe fields include `board` (index name), `listing_date` (constituent file date), `industry`, `region`, and `official_source='CSI000985'` when available. Official-universe runs also refresh market snapshot fields from market-data sources so `total_mv` and `circ_mv` stay maintained in `stock_universe`; if the snapshot source is unavailable, existing market values are retained rather than replaced with empty values.

The script stores two separate ranking tables by trade date. Both are fetched only for the requested day after the close and are not backfilled historically by default:

```text
popularity_top100:
trade_date, rank, code, name, exchange,
hot_value, rank_change, latest_price, pct_chg,
source, fetched_at, raw_json

turnover_top200:
trade_date, rank, code, name, exchange,
amount, volume, turnover_ratio, latest_price, pct_chg,
source, fetched_at, raw_json
```

Data source priority is built for resilience: use CSI All Share (`000985`) constituents for the universe, Tencent first for K-line speed, then fall back to mootdx/TDX TCP K-lines, Eastmoney, TickFlow free daily K-lines, BaoStock, Sina daily history, NetEase historical CSV, and AkShare daily history when earlier sources return empty or fail. Tushare Pro is available only as an explicit K-line source when `TUSHARE_TOKEN` or `TS_TOKEN` is set. Use Eastmoney app ranking for popularity top 100 with optional AkShare fallback. Pull turnover top 200 separately from Sina Market Center `sort=amount` into `turnover_top200` only for same-day snapshots; historical `trade_date`s are skipped. Use `--universe-source market` only when the user explicitly accepts market-data-source stock lists instead of CSI All Share constituents.

## Multi-Source Auto Switching

Keep source switching automatic by default:

- K-line default: `--kline-sources auto`, equivalent to `tencent,mootdx,eastmoney,tickflow,baostock,sina,netease,akshare`.
- K-line source strategy default: `--kline-source-strategy rotate`, which rotates each symbol's first K-line source across non-serial sources to spread public-endpoint pressure. Use `--kline-source-strategy fallback` to preserve the listed source order for every symbol during diagnosis.
- Popularity default: `--popularity-sources auto`, equivalent to `eastmoney,akshare`; `--popularity-limit` defaults to `100`.
- Universe default: `--universe-source official`, using cached CSI All Share (`CSI000985`) constituents except on the monthly refresh day.
- Source circuit breaker default: `--source-fail-threshold 3`; after a K-line source has three consecutive request failures in one run, later symbol fetches skip it and go directly to the next configured source. Successful requests reset that source's failure streak. Already in-flight concurrent requests may still finish.
- mootdx source: uses TDX TCP daily K-lines for unadjusted requests only. Adjusted requests skip mootdx, and BSE coverage should be judged from run-time source counts and failures rather than assumed.
- TickFlow source: uses `TickFlow.free()` for unadjusted historical daily K-lines by default, or `TickFlow(api_key=$env:TICKFLOW_API_KEY)` when the environment variable is set. Adjusted requests skip TickFlow.
- Optional Tushare source: pass `--kline-sources tushare,...` only when a valid `TUSHARE_TOKEN` or `TS_TOKEN` is configured. It uses unadjusted `pro.daily` rows; adjusted K-line requests skip Tushare rather than silently returning unadjusted data.
- BaoStock remains in the fallback chain but is avoided as a rotated first source by default because its login/session flow is serialized.

Override source order only when diagnosing vendor outages:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --kline-sources eastmoney,tencent,mootdx,tickflow,baostock,sina,netease,akshare `
  --kline-source-strategy fallback `
  --popularity-sources akshare,eastmoney
```

Every normalized K-line row stores its actual source in `daily_kline.source`; popularity rows store their actual source in `popularity_top100.source`; turnover rows store theirs in `turnover_top200.source`.
Ranking tables are same-day only; if `--trade-date` is historical, no ranking fetch occurs and no existing historical rows are touched.
Progress logs also show K-line source counts, fallback count, and average successful source latency so slow or failing vendors are visible during a long run.
If a source is disabled by the circuit breaker, progress logs include `disabled_sources=...`, `sync_runs.notes` records `kline_source_breaker`, and the JSON summary includes the breaker threshold, per-source request failure counts, failure streaks, and disabled source list.

## Public Endpoint Stability

Public market-data endpoints can return timeouts, empty responses, or rate-limit style failures during full-market runs. Keep the default conservative network policy unless diagnosing runtime:

- `--max-workers` defaults to `4` to reduce request bursts.
- `--request-attempts` defaults to `4`.
- `--retry-base-sleep` and `--retry-max-sleep` control exponential backoff after failed HTTP requests.
- `--request-delay` and `--request-jitter` add a shared cross-thread delay between public endpoint requests.
- `--source-fail-threshold` defaults to `3` so consecutively timing-out K-line sources are skipped for the rest of the run instead of being retried for every symbol; use `0` only when explicitly diagnosing all sources.

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

## Official Universe Source

Use CSI All Share / 中证全指 (`000985`) constituents as the default full-market universe, but do not fetch them on every daily run. Refresh the official universe on the 1st day of each month, or when `--refresh-universe` is passed. On other days, use cached rows in `stock_universe` where `official_source='CSI000985'`.

The script calls AkShare's `index_stock_cons_csindex(symbol="000985")` wrapper for the latest constituent file from CSI. The normalized rows keep the constituent index name in `board`, the constituent file date in `listing_date`, exchange inferred from CSI fields and code prefixes, and raw source content in `raw_json`. Official and cached-official universe rows are enriched with market snapshot fields from AkShare, Eastmoney, or Sina, including `total_mv` and `circ_mv`. If a cached database lacks `CSI000985` rows, the next default official run should refresh the universe.

## SQLite Tables

- `stock_universe`: latest full-market symbol list and rich spot fields.
- `daily_kline`: normalized daily K-line rows keyed by `(code, trade_date)`.
- `popularity_top100`: popularity top 100 snapshots keyed by `(trade_date, rank)`; sync replaces only the requested trade date.
- `turnover_top200`: turnover top 200 snapshots keyed by `(trade_date, rank)`; sync replaces only the requested trade date.
- `sync_runs`: run metadata, mode, counts, retained window, and latest-date summary.
- `fetch_failures`: per-symbol failures for the run.

Use parameterized SQL when querying or extending the script. Do not parse SQLite output with ad hoc string slicing.

## Deletion Rules

Daily scheduled jobs must only clear or delete rows for the requested `trade_date`.

- Allowed in `daily`: replacing current-day `popularity_top100`/`turnover_top200` rows, or clearing rows for that fetch date when either snapshot fetch fails.
- Allowed in `init`: historical K-line backfill and retention pruning to the latest 126 trading dates.
- Not allowed in `daily`: deleting older `daily_kline` dates, deleting older `popularity_top100` or `turnover_top200` dates, or running broad cleanup statements without a `trade_date` predicate.

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

Run daily sync without refreshing turnover:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --skip-turnover-top200
```

Repair missing K-line rows for one trade date while preserving existing ranking rows:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --repair-missing `
  --trade-date 2026-06-05 `
  --repair-chunk-size 150
```

For long full-market runs, keep progress output frequent:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --kline-source-strategy rotate `
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

Use Tushare as an explicit token-backed fallback:

```powershell
pip install tushare
$env:TUSHARE_TOKEN = "your-token"
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py `
  --mode daily `
  --kline-sources tencent,mootdx,eastmoney,tickflow,baostock,tushare,akshare
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
4. Confirm `turnover_top200` has no duplicate ranks for the requested `trade_date`, and normally exactly 200 rows for that date after a successful live sync.
5. Confirm recent dates have broad symbol coverage; a large `fetch_failures` count means the market cache is incomplete.
6. After `--repair-missing`, confirm the final `cached_count`, `universe_count`, remaining missing prefix distribution, and `remaining_missing_sample` from the JSON summary.
7. State clearly whether the data came from live network fetches or only from self-test/sample mode.

## Guardrails

- Do not invent K-line rows, prices, volumes, or trade dates.
- Do not carry forward yesterday's ranking snapshots as today's rankings. If any ranking endpoint fails, clear only the requested `trade_date` rows for that table and report the failure.
- Do not treat the cache as investment advice; it is a research data store only.
- Keep database files under `runs/ashare-kline-sqlite-cache/` unless the user specifies another path.
- If public endpoints fail or rate-limit, report the failure count and retry later rather than filling gaps manually.
