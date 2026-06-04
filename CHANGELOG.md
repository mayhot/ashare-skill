# Changelog

## 2026-06-04

- runs: Added the 2026-06-03 `ashare-index-inclusion-watch`, `ashare-kline-sqlite-cache`, and `ashare-volume-doubled-uptrend` run artifacts.
- skills: Added repository-wide agent guidelines in `AGENTS.md`.
- skills: Added `ashare-index-inclusion-watch` for mainstream index inclusion cross-screening against turnover and popularity rankings.
- skills: Added `ashare-kline-sqlite-cache` with a SQLite daily K-line and popularity snapshot sync script.
- notes: Prepared changes for split commits on `runs` and `skill`; `main` was already ahead of `origin/main`.
- skills: Updated `ashare-volume-doubled-uptrend` to exclude companies below 20bn yuan total market cap by default.
- skills: Migrated the shared K-line cache from a single CSV file to SQLite with `(code,date)` upserts, bounded cache trimming, code-scoped reads, and one-time legacy CSV migration.
- skills: Updated cache documentation and ignored SQLite cache artifacts under `runs/`.
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
