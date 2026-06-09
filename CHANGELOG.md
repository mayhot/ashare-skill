# Changelog

## 2026-06-09

- skills: Updated `ashare-volume-doubled-uptrend` market-cap filtering to detect central-cache `total_mv` values stored in 10k-CNY units and normalize them to yuan before applying the default 20bn-yuan threshold.

- skills: Updated `ashare-trend-buy` report tables so turnover, popularity, and combined result sections explicitly use `股票名称` and `股票代码` columns.
- skills: Added compatibility migrations for `ashare-kline-sqlite-cache` turnover and popularity ranking tables so old SQLite caches gain `code` and `name` fields.
- skills: Updated `ashare-kline-sqlite-cache` to migrate and maintain `stock_universe.total_mv`/`circ_mv` during official CSI universe syncs, preserving existing market values when snapshot sources are unavailable.
- skills: Updated `ashare-trend-buy` to fill missing candidate names and market fields across ranking sources so heat-list reports do not emit blank stock names or zeroed quote metrics when same-code turnover data is available.
- skills: Fixed `ashare-ai-slowbull` SQLite turnover-cache reads to recover Sina `mktcap` metadata from `raw_json` so market-cap scoring and reports do not show zero values.
- skills: Changed `ashare-kline-sqlite-cache` popularity snapshots from top 200 to top 100, renamed the SQLite table to `popularity_top100`, and removed old `popularity_top200` compatibility.
- skills: Updated market-data-consuming skills to prefer `runs/ashare-kline-sqlite-cache/ashare_kline.sqlite` for turnover/popularity rankings, stock universe, daily K-lines, and recommendation return prices before falling back to public APIs.
- runs: Added the 2026-06-08 `ashare-volume-doubled-uptrend` run artifact.
- skills: Added TickFlow as a default `ashare-kline-sqlite-cache` K-line fallback source using free historical daily K-lines, including Beijing exchange symbol support.
- skills: Added `ashare-kline-sqlite-cache/scripts/repair_missing_kline_grid.py` to query `stock_universe x daily_kline.trade_date` gaps and optionally backfill exact missing K-line cells.
- skills: Changed `ashare-kline-sqlite-cache` default `stock_universe` official source from SSE/SZSE/BSE exchange lists to CSI All Share / 中证全指 (`000985`) constituents tagged as `CSI000985`.
- skills: Added BaoStock as a default `ashare-kline-sqlite-cache` K-line fallback source and optional token-backed Tushare Pro daily K-line support.
- skills: Added `ashare-kline-sqlite-cache --kline-source-strategy rotate|fallback` so full-market K-line syncs can distribute first-source requests across vendors while preserving per-symbol fallback coverage.
- skills: Added mootdx/TDX TCP daily K-line support to `ashare-kline-sqlite-cache` as a default rotated source for unadjusted K-line fetches.
- skills: Changed `ashare-kline-sqlite-cache` popularity snapshots to fetch the post-close top 100 by default and store them in `popularity_top100`.
- skills: Added `ashare-kline-sqlite-cache` separate turnover top 200 extraction from Sina Market Center (`sort=amount`) and dedicated `turnover_top200` persistence to SQLite.
- skills: Changed `ashare-kline-sqlite-cache` ranking sync to only refresh popularity/turnover top 200 snapshots for current-trade-date runs in/after the same-day window; historical `--trade-date` calls no longer backfill, and replacements are scoped to that date only.
- skills: Updated `ashare-kline-sqlite-cache` documentation with the expanded K-line source order and Tushare token usage notes.

## 2026-06-08

- runs: Added the 2026-06-08 `ashare-ai-slowbull` and `ashare-trend-buy` run artifacts.
- skills: Added K-line source circuit breaking to `ashare-kline-sqlite-cache` so repeatedly failing market-data sources are skipped for the rest of a run, and expanded fallback sources to Tencent, Eastmoney, Sina, NetEase, and AkShare.
- skills: Added `ashare-kline-sqlite-cache --repair-missing` to repair per-date K-line gaps in bounded `--symbols-only` batches while preserving existing popularity snapshots.
- skills: Added K-line coverage, missing-prefix, popularity-count, unfinished-run, and SQLite writability preflight checks to the K-line cache repair workflow.
- skills: Updated `ashare-kline-sqlite-cache` documentation with the failed-run repair playbook and validation expectations.
- skills: Preserved cached `stock_universe` metadata during `--symbols-only` repair runs instead of replacing names and official-source fields with bare code rows.

## 2026-06-05

- skills: Added repository-wide SQLite database ignore rules so cache databases and WAL/SHM sidecars stay out of commits.
- skills: Optimized `ashare-kline-sqlite-cache` full-market K-line sync by making Tencent the default first K-line source, fetching only per-symbol missing date gaps after seed import, and reporting source counts plus average source latency in progress logs.
- skills: Added `ashare-trend-buy` runtime progress output to stderr for candidate loading, K-line fetch progress, pool scoring, and report writing.

## 2026-06-04

- runs: Added the 2026-06-03 `ashare-index-inclusion-watch`, `ashare-kline-sqlite-cache`, and `ashare-volume-doubled-uptrend` run artifacts.
- skills: Added repository-wide agent guidelines in `AGENTS.md`.
- skills: Added `ashare-index-inclusion-watch` for mainstream index inclusion cross-screening against turnover and popularity rankings.
- skills: Added `ashare-kline-sqlite-cache` with a SQLite daily K-line and popularity snapshot sync script.
- notes: Prepared changes for split commits on `runs` and `skill`; `main` was already ahead of `origin/main`.
- skills: Updated `ashare-volume-doubled-uptrend` to exclude companies below 20bn yuan total market cap by default.
- skills: Migrated the shared K-line cache from a single CSV file to SQLite with `(code,date)` upserts, bounded cache trimming, code-scoped reads, and one-time legacy CSV migration.
- skills: Updated cache documentation and ignored SQLite cache artifacts under `runs/`.
- skills: Hardened `ashare-kline-sqlite-cache` public endpoint calls with shared request pacing, configurable retry attempts, exponential backoff, and a lower default K-line fetch concurrency.
- skills: Updated `ashare-kline-sqlite-cache` same-day guard to allow default runs from 15:30 through 23:59:59 Asia/Shanghai.
- skills: Hardened `ashare-trend-buy` public API calls with configurable retries, exponential backoff, jittered K-line pacing, and a lower default K-line fetch concurrency.
- notes: Validated with `--self-test` and `compileall`; existing `runs/` outputs were not committed.

## 2026-06-03

- skills: Added `ashare-volume-doubled-uptrend` for full A-share screening of 6-month uptrends with recent doubled-volume up days and next-day half-gain hold confirmation.
- skills: Updated `ashare-volume-doubled-uptrend` to keep a shared 6-month daily-K cache under its runs root and use daily incremental K-line refreshes after the initial full fetch.
- skills: Made `ashare-volume-doubled-uptrend` cache refresh resumable with batch persistence and shorter per-request timeouts.
- skills: Added failed-code reporting, short-listing-history cache completion, and BaoStock third-source K-line supplement to `ashare-volume-doubled-uptrend`.

## 2026-06-02

- runs: Added the 2026-06-02 `ashare-ai-slowbull` and `ashare-trend-buy` run outputs.
- runs: Refreshed historical backtest reports for `ashare-ai-slowbull` and `ashare-trend-buy`, including the aggregate slowbull backtest report through 2026-06-01.
- skills: Updated `ashare-trend-buy` skill documentation and `run_trend_buy.py`.
- skills: Added the root README with project structure, skill overview, quick-start commands, data conventions, and disclaimer.
- notes: `main` is ahead of `origin/main`; no remote pull or push was performed.

## 2026-06-01

- runs: Added the latest generated A-share run outputs on the `runs` branch.
- runs: Restored the missing 2026-05-29 `ashare-ai-slowbull` and `ashare-trend-buy` run reports from commit `6edf6e9` into the `runs` branch.
- skills: Added the `commit-code` skill and updated it to require a changelog before committing.
- skills: Recorded the 2026-05-29 run-report restoration in the changelog.
- notes: Validated `commit-code` with the skill validator. `main` remains ahead of `origin/main`; no remote pull or push was performed.
