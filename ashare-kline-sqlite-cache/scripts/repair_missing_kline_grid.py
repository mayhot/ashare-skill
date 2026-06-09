import argparse
import importlib.util
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path
from typing import Any


# Data fetching intentionally delegates to sync_ashare_kline.py so this repair
# path uses the same source order, retries, throttling, normalization, and upsert
# contract documented by the skill.
SCRIPT_PATH = Path(__file__).resolve()
SYNC_PATH = SCRIPT_PATH.with_name("sync_ashare_kline.py")
ROOT = SCRIPT_PATH.parents[2]
DEFAULT_DB = ROOT / "runs" / "ashare-kline-sqlite-cache" / "ashare_kline.sqlite"


def load_sync_module() -> Any:
    spec = importlib.util.spec_from_file_location("sync_ashare_kline", SYNC_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SYNC_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load_sync_module()


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def yyyymmdd(value: str) -> str:
    return value.replace("-", "")


def selected_symbols(value: str | None) -> set[str] | None:
    if not value:
        return None
    result = {sync.normalize_code(item) for item in value.split(",") if sync.normalize_code(item)}
    return result or None


def sql_filters(args: argparse.Namespace) -> tuple[str, list[Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if args.date_from:
        filters.append("trade_date >= ?")
        params.append(args.date_from)
    if args.date_to:
        filters.append("trade_date <= ?")
        params.append(args.date_to)
    if args.trade_date:
        filters.append("trade_date = ?")
        params.append(args.trade_date)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    return where, params


def symbol_filter_sql(symbols: set[str] | None, prefix: str = "u") -> tuple[str, list[Any]]:
    if not symbols:
        return "", []
    placeholders = ",".join("?" for _ in symbols)
    return f" AND {prefix}.code IN ({placeholders})", sorted(symbols)


def missing_summary(conn: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    date_where, date_params = sql_filters(args)
    symbols = selected_symbols(args.symbols)
    universe_filter, universe_params = symbol_filter_sql(symbols, "u")
    sample_limit = max(1, args.sample_limit)

    stock_universe_count = conn.execute(
        f"SELECT COUNT(1) FROM stock_universe u WHERE 1=1{universe_filter}",
        universe_params,
    ).fetchone()[0]
    trade_date_count = conn.execute(
        f"SELECT COUNT(1) FROM (SELECT DISTINCT trade_date FROM daily_kline{date_where})",
        date_params,
    ).fetchone()[0]
    date_range = conn.execute(
        f"SELECT MIN(trade_date), MAX(trade_date) FROM (SELECT DISTINCT trade_date FROM daily_kline{date_where})",
        date_params,
    ).fetchone()
    existing_rows = conn.execute(
        f"""
        SELECT COUNT(1)
        FROM daily_kline k
        JOIN stock_universe u ON u.code = k.code
        WHERE 1=1{universe_filter}
          AND k.trade_date IN (SELECT DISTINCT trade_date FROM daily_kline{date_where})
        """,
        universe_params + date_params,
    ).fetchone()[0]
    expected_rows = stock_universe_count * trade_date_count
    missing_rows = max(0, expected_rows - existing_rows)

    common_cte = f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM daily_kline{date_where}
        ), expected AS (
            SELECT u.code, u.name, u.exchange, d.trade_date
            FROM stock_universe u
            CROSS JOIN dates d
            WHERE 1=1{universe_filter}
        ), missing AS (
            SELECT e.code, e.name, e.exchange, e.trade_date
            FROM expected e
            LEFT JOIN daily_kline k
              ON k.code = e.code AND k.trade_date = e.trade_date
            WHERE k.code IS NULL
        )
    """
    params = date_params + universe_params
    symbols_with_missing = conn.execute(
        common_cte + " SELECT COUNT(1) FROM (SELECT code FROM missing GROUP BY code)",
        params,
    ).fetchone()[0]
    dates_with_missing = conn.execute(
        common_cte + " SELECT COUNT(1) FROM (SELECT trade_date FROM missing GROUP BY trade_date)",
        params,
    ).fetchone()[0]
    top_missing_by_symbol = conn.execute(
        common_cte
        + """
        SELECT code, name, exchange, COUNT(1) AS missing_days,
               MIN(trade_date) AS first_missing_date,
               MAX(trade_date) AS last_missing_date
        FROM missing
        GROUP BY code, name, exchange
        ORDER BY missing_days DESC, code
        LIMIT ?
        """,
        params + [sample_limit],
    ).fetchall()
    missing_by_date = conn.execute(
        common_cte
        + """
        SELECT trade_date, COUNT(1) AS missing_symbols
        FROM missing
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        params + [sample_limit],
    ).fetchall()
    return {
        "stock_universe_count": stock_universe_count,
        "trade_date_count": trade_date_count,
        "date_range": list(date_range),
        "existing_grid_rows": existing_rows,
        "expected_grid_rows": expected_rows,
        "missing_grid_rows": missing_rows,
        "symbols_with_missing_count": symbols_with_missing,
        "dates_with_missing_count": dates_with_missing,
        "top_missing_by_symbol": top_missing_by_symbol,
        "latest_missing_by_date": missing_by_date,
    }


def missing_symbol_ranges(conn: sqlite3.Connection, args: argparse.Namespace) -> list[dict[str, Any]]:
    date_where, date_params = sql_filters(args)
    symbols = selected_symbols(args.symbols)
    universe_filter, universe_params = symbol_filter_sql(symbols, "u")
    limit_sql = " LIMIT ?" if args.max_symbols and args.max_symbols > 0 else ""
    limit_params = [args.max_symbols] if args.max_symbols and args.max_symbols > 0 else []
    rows = conn.execute(
        f"""
        WITH dates AS (
            SELECT DISTINCT trade_date FROM daily_kline{date_where}
        ), expected AS (
            SELECT u.code, u.name, u.exchange, u.secid, d.trade_date
            FROM stock_universe u
            CROSS JOIN dates d
            WHERE 1=1{universe_filter}
        ), missing AS (
            SELECT e.code, e.name, e.exchange, e.secid, e.trade_date
            FROM expected e
            LEFT JOIN daily_kline k
              ON k.code = e.code AND k.trade_date = e.trade_date
            WHERE k.code IS NULL
        )
        SELECT code, name, exchange, secid, COUNT(1) AS missing_days,
               MIN(trade_date) AS begin_date,
               MAX(trade_date) AS end_date
        FROM missing
        GROUP BY code, name, exchange, secid
        ORDER BY missing_days DESC, code
        {limit_sql}
        """,
        date_params + universe_params + limit_params,
    ).fetchall()
    return [
        {
            "code": row[0],
            "name": row[1] or "",
            "exchange": row[2] or sync.exchange_for_code(row[0]),
            "secid": row[3] or sync.secid_for_code(row[0]),
            "missing_days": int(row[4] or 0),
            "begin_date": row[5],
            "end_date": row[6],
        }
        for row in rows
    ]


def fetch_one(stock: dict[str, Any], args: argparse.Namespace, source_breaker: Any) -> dict[str, Any]:
    sources = sync.parse_sources(args.kline_sources, sync.DEFAULT_KLINE_SOURCES, sync.KLINE_SOURCE_SET)
    stock_sources = sync.rotated_sources_for_code(
        stock["code"],
        sources,
        args.kline_source_strategy,
        sync.ROTATE_PRIMARY_AVOID_SOURCES,
    )
    started = time.time()
    code, rows, source, seconds = sync.fetch_kline_rows(
        stock,
        yyyymmdd(stock["begin_date"]),
        yyyymmdd(stock["end_date"]),
        args.adjust,
        args.request_timeout,
        stock_sources,
        args.request_attempts,
        args.retry_base_sleep,
        args.retry_max_sleep,
        args.request_delay,
        args.request_jitter,
        source_breaker,
    )
    wanted_dates = stock["missing_dates"]
    filtered_rows = [row for row in rows if row.get("trade_date") in wanted_dates]
    return {
        "code": code,
        "rows": filtered_rows,
        "raw_rows": len(rows),
        "source": source,
        "source_seconds": seconds,
        "elapsed": time.time() - started,
    }


def attach_missing_dates(conn: sqlite3.Connection, stocks: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if not stocks:
        return
    date_where, date_params = sql_filters(args)
    codes = [stock["code"] for stock in stocks]
    by_code: dict[str, set[str]] = {code: set() for code in codes}
    for offset in range(0, len(codes), 900):
        chunk = codes[offset : offset + 900]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            WITH dates AS (
                SELECT DISTINCT trade_date FROM daily_kline{date_where}
            ), expected AS (
                SELECT u.code, d.trade_date
                FROM stock_universe u
                CROSS JOIN dates d
                WHERE u.code IN ({placeholders})
            )
            SELECT e.code, e.trade_date
            FROM expected e
            LEFT JOIN daily_kline k
              ON k.code = e.code AND k.trade_date = e.trade_date
            WHERE k.code IS NULL
            ORDER BY e.code, e.trade_date
            """,
            date_params + chunk,
        ).fetchall()
        for code, trade_date in rows:
            by_code[str(code)].add(str(trade_date))
    for stock in stocks:
        stock["missing_dates"] = by_code.get(stock["code"], set())


def repair_missing(conn: sqlite3.Connection, stocks: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    attach_missing_dates(conn, stocks, args)
    stocks = [stock for stock in stocks if stock.get("missing_dates")]
    if args.dry_run or not args.repair:
        return {
            "repair_enabled": False,
            "planned_symbols": len(stocks),
            "planned_missing_pairs": sum(len(stock["missing_dates"]) for stock in stocks),
        }
    sync.check_database_writable(conn)

    source_breaker = sync.SourceCircuitBreaker(args.source_fail_threshold)
    rows_pending: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    raw_rows = 0
    rows_upserted = 0
    fetched_symbols = 0
    started = time.time()
    last_log = started
    max_workers = max(1, args.max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, stock, args, source_breaker): stock for stock in stocks}
        for idx, future in enumerate(as_completed(futures), start=1):
            stock = futures[future]
            try:
                result = future.result()
                fetched_symbols += 1
                raw_rows += int(result["raw_rows"])
                source = str(result["source"])
                source_counts[source] = source_counts.get(source, 0) + 1
                rows_pending.extend(result["rows"])
                if len(rows_pending) >= args.batch_rows:
                    rows_upserted += sync.upsert_kline_rows(conn, rows_pending)
                    rows_pending.clear()
            except Exception as exc:
                failures.append(
                    {
                        "code": stock["code"],
                        "name": stock.get("name") or "",
                        "missing_days": stock.get("missing_days"),
                        "begin_date": stock.get("begin_date"),
                        "end_date": stock.get("end_date"),
                        "reason": str(exc)[:500],
                    }
                )
            now = time.time()
            if idx % args.progress_every == 0 or now - last_log >= args.progress_seconds:
                last_log = now
                sync.log(
                    "grid repair progress: "
                    f"done={idx}/{len(stocks)} fetched={fetched_symbols} "
                    f"pending_rows={len(rows_pending)} failures={len(failures)} "
                    f"sources={sync.format_count_map(source_counts)} "
                    f"elapsed={sync.format_duration(now - started)}"
                )

    inserted_tail = sync.upsert_kline_rows(conn, rows_pending)
    rows_upserted += inserted_tail
    return {
        "repair_enabled": True,
        "planned_symbols": len(stocks),
        "planned_missing_pairs": sum(len(stock["missing_dates"]) for stock in stocks),
        "rows_upserted": rows_upserted,
        "raw_rows_fetched": raw_rows,
        "failures": len(failures),
        "failure_sample": failures[: args.sample_limit],
        "source_counts": source_counts,
        "source_breaker": source_breaker.snapshot(),
        "elapsed_seconds": round(time.time() - started, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query stock_universe x trade_date K-line gaps and optionally repair missing daily_kline rows."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--trade-date", type=parse_date, help="repair/query one YYYY-MM-DD trade date")
    parser.add_argument("--date-from", type=parse_date, help="first trade date to include")
    parser.add_argument("--date-to", type=parse_date, help="last trade date to include")
    parser.add_argument("--symbols", help="comma-separated stock codes to include")
    parser.add_argument("--max-symbols", type=int, default=0, help="limit symbols for bounded repair tests; 0 means all")
    parser.add_argument("--sample-limit", type=int, default=30)
    parser.add_argument("--repair", action="store_true", help="fetch and upsert missing K-line rows")
    parser.add_argument("--dry-run", action="store_true", help="query gaps and show repair plan without network fetches")
    parser.add_argument("--adjust", choices=sorted(sync.ADJUST_FLAGS), default="none")
    parser.add_argument("--kline-sources", default="auto")
    parser.add_argument("--kline-source-strategy", choices=["rotate", "fallback"], default="rotate")
    parser.add_argument("--request-timeout", type=int, default=15)
    parser.add_argument("--request-attempts", type=int, default=4)
    parser.add_argument("--retry-base-sleep", type=float, default=0.8)
    parser.add_argument("--retry-max-sleep", type=float, default=10.0)
    parser.add_argument("--source-fail-threshold", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.12)
    parser.add_argument("--request-jitter", type=float, default=0.18)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--progress-seconds", type=int, default=15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    with closing(sqlite3.connect(db_path)) as conn:
        sync.ensure_schema(conn)
        before = missing_summary(conn, args)
        stocks = missing_symbol_ranges(conn, args)
        repair = repair_missing(conn, stocks, args)
        after = missing_summary(conn, args) if args.repair and not args.dry_run else None
    print(
        json.dumps(
            {
                "database": str(db_path),
                "filters": {
                    "trade_date": args.trade_date,
                    "date_from": args.date_from,
                    "date_to": args.date_to,
                    "symbols": sorted(selected_symbols(args.symbols) or []),
                    "max_symbols": args.max_symbols,
                },
                "before": before,
                "repair": repair,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
