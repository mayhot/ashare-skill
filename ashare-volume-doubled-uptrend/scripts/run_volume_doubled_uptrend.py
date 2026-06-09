import argparse
import json
import math
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
SKILL_NAME = "ashare-volume-doubled-uptrend"
DEFAULT_MARKET_CACHE_DB = ROOT / "runs" / "ashare-kline-sqlite-cache" / "ashare_kline.sqlite"
DEFAULT_MIN_MARKET_CAP_YUAN = 20_000_000_000
MARKET_CAP_COLUMNS = (
    "total_mv",
    "market_cap",
    "total_market_cap",
    "market_value",
    "mv",
)


def add_local_deps() -> None:
    candidates = [
        Path.cwd() / ".deps",
        ROOT / ".deps",
        Path(__file__).resolve().parents[3] / ".deps",
    ]
    for path in candidates:
        if path.exists():
            sys.path.insert(0, str(path))


add_local_deps()

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Install with: python -m pip install --target .deps pandas"
    ) from exc

try:
    import baostock as bs
except ImportError:
    bs = None


EASTMONEY_LIST_URL = (
    "http://push2.eastmoney.com/api/qt/clist/get?"
    "pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&"
    "fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&"
    "fields=f12,f14,f2,f3,f5,f6,f8,f20"
)
SINA_LIST_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num=80&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=page"
)
EASTMONEY_KLINE_URL = (
    "http://push2his.eastmoney.com/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
    "fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg={begin}&end={end}"
)
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"


def skill_run_root(args: argparse.Namespace) -> Path:
    return Path(args.runs_dir) / SKILL_NAME


def report_dir(args: argparse.Namespace) -> Path:
    trade_date = args.trade_date or date.today().isoformat()
    return skill_run_root(args) / trade_date


def cache_dir(args: argparse.Namespace) -> Path:
    return Path(args.cache_dir) if args.cache_dir else skill_run_root(args) / "kline-cache"


def cache_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    path = cache_dir(args)
    return path / "daily_kline_6m.sqlite", path / "daily_kline_6m.meta.json"


def legacy_cache_csv_path(args: argparse.Namespace) -> Path:
    return cache_dir(args) / "daily_kline_6m.csv"


def failed_codes_path(args: argparse.Namespace) -> Path:
    return cache_dir(args) / "failed_kline_codes.csv"


def market_cache_db_path(args: argparse.Namespace) -> Path:
    path = Path(args.market_cache_db)
    return path if path.is_absolute() else ROOT / path


def normalize_code(code: object) -> str:
    text = str(code).strip()
    if "." in text and text.split(".")[-1].isdigit():
        text = text.split(".")[-1]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def secid(code: str) -> str:
    code = normalize_code(code)
    market = "1" if code.startswith(("6", "9")) else "0"
    return f"{market}.{code}"


def is_bse_code(code: str) -> bool:
    code = normalize_code(code)
    return code.startswith(("4", "8", "920"))


def baostock_code(code: str) -> str:
    code = normalize_code(code)
    if is_bse_code(code):
        return ""
    return ("sh." if code.startswith(("6", "9")) else "sz.") + code


def url_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_market_cache_stock_list(args: argparse.Namespace, limit: int | None = None) -> tuple[list[dict], str] | None:
    if args.ignore_market_cache:
        return None
    db_path = market_cache_db_path(args)
    if not db_path.exists():
        return None
    with sqlite3.connect(str(db_path.resolve())) as conn:
        conn.row_factory = sqlite3.Row
        if not sqlite_table_exists(conn, "stock_universe"):
            return None
        sql = """
            SELECT code, name, latest_price, pct_chg, volume, amount, turnover, total_mv
            FROM stock_universe
            WHERE code IS NOT NULL AND code != ''
            ORDER BY amount DESC
        """
        rows = conn.execute(sql).fetchall()
    stock_rows: list[dict] = []
    seen: set[str] = set()
    for item in rows:
        code = normalize_code(item["code"])
        name = str(item["name"] or "").strip()
        if not code or code in seen:
            continue
        if "ST" in name.upper() or "退" in name:
            continue
        seen.add(code)
        stock_rows.append(
            {
                "code": code,
                "name": name,
                "latest_price": to_float(item["latest_price"]),
                "latest_pct_chg": to_float(item["pct_chg"]),
                "latest_volume": to_float(item["volume"]),
                "latest_amount": to_float(item["amount"]),
                "turnover": to_float(item["turnover"]),
                "total_mv": to_float(item["total_mv"]),
            }
        )
        if limit and len(stock_rows) >= limit:
            break
    if not stock_rows:
        return None
    return stock_rows, "ashare-kline-sqlite-cache SQLite stock_universe"


def fetch_stock_list(args: argparse.Namespace, limit: int | None = None) -> tuple[list[dict], str]:
    cached = fetch_market_cache_stock_list(args, limit)
    if cached:
        return cached
    if args.no_network:
        raise RuntimeError("network disabled and local SQLite stock_universe unavailable")
    try:
        rows = fetch_eastmoney_stock_list(limit)
        if rows:
            return rows, "东方财富全A列表"
    except Exception:
        pass
    rows = fetch_sina_stock_list(limit)
    return rows, "新浪全A列表"


def fetch_eastmoney_stock_list(limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 100):
        payload = url_json(EASTMONEY_LIST_URL.format(page=page))
        diff = ((payload.get("data") or {}).get("diff") or [])
        if not diff:
            break
        for item in diff:
            code = normalize_code(item.get("f12", ""))
            name = str(item.get("f14", "")).strip()
            if not code or code in seen:
                continue
            if "ST" in name.upper() or "退" in name:
                continue
            seen.add(code)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "latest_price": to_float(item.get("f2")),
                    "latest_pct_chg": to_float(item.get("f3")),
                    "latest_volume": to_float(item.get("f5")),
                    "latest_amount": to_float(item.get("f6")),
                    "turnover": to_float(item.get("f8")),
                    "total_mv": to_float(item.get("f20")),
                }
            )
            if limit and len(rows) >= limit:
                return rows
        time.sleep(0.05)
    return rows


def fetch_sina_stock_list(limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 100):
        payload = None
        last_error = None
        for attempt in range(6):
            try:
                payload = url_json(SINA_LIST_URL.format(page=page), timeout=30)
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.5 + attempt * 0.5)
        if payload is None:
            raise RuntimeError(f"Sina list page {page} failed after retries: {last_error}")
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            code = normalize_code(item.get("code", ""))
            name = str(item.get("name", "")).strip()
            if not code or code in seen:
                continue
            if "ST" in name.upper() or "退" in name:
                continue
            seen.add(code)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "latest_price": to_float(item.get("trade")),
                    "latest_pct_chg": to_float(item.get("changepercent")),
                    "latest_volume": to_float(item.get("volume")),
                    "latest_amount": to_float(item.get("amount")),
                    "turnover": to_float(item.get("turnoverratio")),
                    "total_mv": math.nan,
                }
            )
            if limit and len(rows) >= limit:
                return rows
        time.sleep(0.05)
    return rows


def fetch_kline(code: str, end_date: str, lookback_days: int = 430, timeout: int = 8) -> "pd.DataFrame":
    try:
        frame = fetch_tencent_kline(code, end_date, lookback_days, timeout=timeout)
        if not frame.empty:
            return frame
    except Exception:
        pass
    return fetch_eastmoney_kline(code, end_date, lookback_days, timeout=timeout)


def fetch_eastmoney_kline(code: str, end_date: str, lookback_days: int = 430, timeout: int = 8) -> "pd.DataFrame":
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    begin = (end_dt - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")
    payload = url_json(EASTMONEY_KLINE_URL.format(secid=secid(code), begin=begin, end=end), timeout=timeout)
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        rows.append(
            {
                "code": normalize_code(code),
                "date": parts[0],
                "open": to_float(parts[1]),
                "close": to_float(parts[2]),
                "high": to_float(parts[3]),
                "low": to_float(parts[4]),
                "volume": to_float(parts[5]),
                "amount": to_float(parts[6]),
            }
        )
    return pd.DataFrame(rows)


def fetch_tencent_kline(code: str, end_date: str, lookback_days: int = 430, timeout: int = 8) -> "pd.DataFrame":
    code = normalize_code(code)
    if is_bse_code(code):
        prefix = "bj"
    else:
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
    symbol = prefix + code
    datalen = max(120, min(360, int(lookback_days / 1.4)))
    param = urllib.parse.quote(f"{symbol},day,,,{datalen},qfq", safe="")
    payload = url_json(TENCENT_KLINE_URL.format(param=param), timeout=timeout)
    stock_data = ((payload.get("data") or {}).get(symbol) or {})
    klines = stock_data.get("qfqday") or stock_data.get("day") or []
    rows = []
    for item in klines:
        if len(item) < 6:
            continue
        kline_date = item[0]
        if kline_date > end_date:
            continue
        rows.append(
            {
                "code": normalize_code(code),
                "date": kline_date,
                "open": to_float(item[1]),
                "close": to_float(item[2]),
                "high": to_float(item[3]),
                "low": to_float(item[4]),
                "volume": to_float(item[5]),
                "amount": math.nan,
            }
        )
    return pd.DataFrame(rows)


def fetch_baostock_kline_logged_in(code: str, end_date: str, lookback_days: int = 430) -> "pd.DataFrame":
    if bs is None:
        return pd.DataFrame()
    bs_code = baostock_code(code)
    if not bs_code:
        return pd.DataFrame()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    begin = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    query = bs.query_history_k_data_plus(
        bs_code,
        "date,code,open,high,low,close,volume,amount",
        start_date=begin,
        end_date=end_date,
        frequency="d",
        adjustflag="2",
    )
    rows = []
    while query.error_code == "0" and query.next():
        item = query.get_row_data()
        rows.append(
            {
                "code": normalize_code(item[1]),
                "date": item[0],
                "open": to_float(item[2]),
                "high": to_float(item[3]),
                "low": to_float(item[4]),
                "close": to_float(item[5]),
                "volume": to_float(item[6]),
                "amount": to_float(item[7]),
            }
        )
    return pd.DataFrame(rows)


def to_float(value: object) -> float:
    try:
        if value in (None, "-", ""):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def valid_market_cap(value: object, threshold: float) -> bool:
    market_cap = to_float(value)
    return not math.isnan(market_cap) and market_cap >= threshold


def market_cap_from_row(row: dict) -> float:
    for col in MARKET_CAP_COLUMNS:
        if col in row:
            value = to_float(row.get(col))
            if not math.isnan(value):
                return value
    return math.nan


def format_market_cap_threshold(value: float) -> str:
    if value <= 0:
        return "disabled"
    return f"{value / 100_000_000:.0f} yi CNY"


def infer_market_cap_scale(values: list[float], threshold: float) -> tuple[float, str]:
    valid_values = [value for value in values if not math.isnan(value)]
    if threshold <= 0 or not valid_values:
        return 1.0, "yuan"
    if any(value >= threshold for value in valid_values):
        return 1.0, "yuan"
    if any(value * 10_000 >= threshold for value in valid_values):
        return 10_000.0, "10k CNY normalized to yuan"
    return 1.0, "yuan"


def filter_stock_rows_by_market_cap(stock_rows: list[dict], args: argparse.Namespace) -> tuple[list[dict], dict]:
    threshold = float(args.min_market_cap_yuan or 0)
    if threshold <= 0:
        return stock_rows, {
            "market_cap_filter_yuan": threshold,
            "market_cap_filter_text": "disabled",
            "market_cap_input_count": len(stock_rows),
            "market_cap_kept_count": len(stock_rows),
            "market_cap_removed_small_count": 0,
            "market_cap_removed_missing_count": 0,
            "market_cap_source": "disabled",
        }

    kept: list[dict] = []
    removed_small = 0
    removed_missing = 0
    raw_market_caps = [market_cap_from_row(row) for row in stock_rows]
    market_cap_scale, market_cap_unit = infer_market_cap_scale(raw_market_caps, threshold)
    for row in stock_rows:
        market_cap = market_cap_from_row(row)
        if math.isnan(market_cap):
            removed_missing += 1
            continue
        if market_cap * market_cap_scale < threshold:
            removed_small += 1
            continue
        kept.append(row)

    return kept, {
        "market_cap_filter_yuan": threshold,
        "market_cap_filter_text": format_market_cap_threshold(threshold),
        "market_cap_input_count": len(stock_rows),
        "market_cap_kept_count": len(kept),
        "market_cap_removed_small_count": removed_small,
        "market_cap_removed_missing_count": removed_missing,
        "market_cap_source": f"stock_list ({market_cap_unit})",
        "market_cap_value_scale": market_cap_scale,
    }


def filter_dataframe_by_market_cap(df: "pd.DataFrame", args: argparse.Namespace) -> tuple["pd.DataFrame", dict]:
    threshold = float(args.min_market_cap_yuan or 0)
    if threshold <= 0:
        return df, {
            "market_cap_filter_yuan": threshold,
            "market_cap_filter_text": "disabled",
            "market_cap_input_count": int(df["code"].nunique()) if "code" in df.columns else 0,
            "market_cap_kept_count": int(df["code"].nunique()) if "code" in df.columns else 0,
            "market_cap_removed_small_count": 0,
            "market_cap_removed_missing_count": 0,
            "market_cap_source": "disabled",
        }

    cap_col = next((col for col in MARKET_CAP_COLUMNS if col in df.columns), None)
    if not cap_col:
        raise SystemExit(
            "--kline-csv requires a market cap column when --min-market-cap-yuan is enabled. "
            "Use one of: total_mv, market_cap, total_market_cap, market_value, mv; "
            "or set --min-market-cap-yuan 0 to disable the filter."
        )

    market_caps = (
        df[["code", cap_col]]
        .dropna(subset=[cap_col])
        .groupby("code")[cap_col]
        .last()
        .map(to_float)
    )
    market_cap_scale, market_cap_unit = infer_market_cap_scale(list(market_caps.values), threshold)
    all_codes = set(df["code"].dropna().astype(str).unique())
    kept_codes = {
        code
        for code, value in market_caps.items()
        if not math.isnan(value) and value * market_cap_scale >= threshold
    }
    codes_with_cap = set(market_caps.index.astype(str))
    removed_missing = len(all_codes - codes_with_cap)
    removed_small = len(codes_with_cap - kept_codes)
    filtered = df[df["code"].astype(str).isin(kept_codes)].copy()

    return filtered, {
        "market_cap_filter_yuan": threshold,
        "market_cap_filter_text": format_market_cap_threshold(threshold),
        "market_cap_input_count": len(all_codes),
        "market_cap_kept_count": len(kept_codes),
        "market_cap_removed_small_count": removed_small,
        "market_cap_removed_missing_count": removed_missing,
        "market_cap_source": f"csv:{cap_col} ({market_cap_unit})",
        "market_cap_value_scale": market_cap_scale,
    }


def load_kline_csv(path: Path) -> "pd.DataFrame":
    df = pd.read_csv(path)
    df.columns = [str(col).strip().lower() for col in df.columns]
    aliases = {
        "股票代码": "code",
        "代码": "code",
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "名称": "name",
        "股票名称": "name",
    }
    df = df.rename(columns={col: aliases.get(col, col) for col in df.columns})
    required = {"code", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"kline csv missing required columns: {', '.join(sorted(missing))}")
    df["code"] = df["code"].map(normalize_code)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume", "amount", *MARKET_CAP_COLUMNS]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def normalize_kline_frame(df: "pd.DataFrame") -> "pd.DataFrame":
    if df.empty:
        return df
    df = df.copy()
    df["code"] = df["code"].map(normalize_code)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["name", "amount"]:
        if col not in df.columns:
            df[col] = "" if col == "name" else math.nan
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = df.sort_values(["code", "date"]).drop_duplicates(["code", "date"], keep="last")
    return df


def trim_cache_window(df: "pd.DataFrame", trade_date: str, calendar_days: int) -> "pd.DataFrame":
    if df.empty:
        return df
    cutoff = (datetime.strptime(trade_date, "%Y-%m-%d").date() - timedelta(days=calendar_days)).isoformat()
    return df[df["date"] >= cutoff].copy()


def complete_cache_codes(df: "pd.DataFrame", trade_date: str) -> set[str]:
    if df.empty:
        return set()
    complete: set[str] = set()
    grouped = df.groupby("code")
    for code, group in grouped:
        if len(group) > 0 and str(group["date"].max()) >= trade_date:
            complete.add(str(code))
    return complete


def cache_status_by_code(df: "pd.DataFrame", trade_date: str) -> dict[str, dict]:
    status: dict[str, dict] = {}
    if df.empty:
        return status
    for code, group in df.groupby("code"):
        latest = str(group["date"].max())
        row_count = int(len(group))
        status[str(code)] = {
            "row_count": row_count,
            "latest_date": latest,
            "complete": row_count > 0 and latest >= trade_date,
        }
    return status


def write_failed_kline_codes(df: "pd.DataFrame", stock_rows: list[dict], args: argparse.Namespace) -> tuple[Path, int]:
    path = failed_codes_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    status = cache_status_by_code(df, args.trade_date)
    rows = []
    for row in stock_rows:
        code = row["code"]
        item = status.get(code, {})
        row_count = int(item.get("row_count", 0))
        latest = str(item.get("latest_date", ""))
        if row_count > 0 and latest >= args.trade_date:
            continue
        if row_count > 0:
            reason = "latest_kline_before_trade_date"
        else:
            reason = "no_kline_returned_by_available_sources"
        rows.append(
            {
                "code": code,
                "name": row.get("name", code),
                "cached_rows": row_count,
                "latest_date": latest,
                "reason": reason,
            }
        )
    pd.DataFrame(rows, columns=["code", "name", "cached_rows", "latest_date", "reason"]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )
    return path, len(rows)


def ensure_sqlite_cache(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path.resolve())) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kline (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                name TEXT,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                amount REAL,
                PRIMARY KEY (code, date)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON kline(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON kline(code, date)")


def upsert_sqlite_kline(df: "pd.DataFrame", args: argparse.Namespace) -> None:
    data_path, _meta_path = cache_paths(args)
    ensure_sqlite_cache(data_path)
    df = normalize_kline_frame(df)
    if df.empty:
        return
    rows = []
    for item in df.itertuples(index=False):
        rows.append(
            (
                getattr(item, "code"),
                getattr(item, "date"),
                getattr(item, "name", ""),
                float(getattr(item, "open")),
                float(getattr(item, "high")),
                float(getattr(item, "low")),
                float(getattr(item, "close")),
                float(getattr(item, "volume")),
                to_float(getattr(item, "amount", math.nan)),
            )
        )
    with sqlite3.connect(str(data_path.resolve())) as conn:
        conn.executemany(
            """
            INSERT INTO kline (code, date, name, open, high, low, close, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, date) DO UPDATE SET
                name = excluded.name,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                amount = excluded.amount
            """,
            rows,
        )


def migrate_legacy_csv_cache(args: argparse.Namespace) -> bool:
    data_path, _meta_path = cache_paths(args)
    legacy_path = legacy_cache_csv_path(args)
    if data_path.exists() or not legacy_path.exists():
        ensure_sqlite_cache(data_path)
        return False
    df = normalize_kline_frame(pd.read_csv(legacy_path, dtype={"code": str}))
    ensure_sqlite_cache(data_path)
    upsert_sqlite_kline(df, args)
    return True


def trim_sqlite_cache(args: argparse.Namespace) -> None:
    data_path, _meta_path = cache_paths(args)
    ensure_sqlite_cache(data_path)
    cutoff = (datetime.strptime(args.trade_date, "%Y-%m-%d").date() - timedelta(days=args.cache_calendar_days)).isoformat()
    with sqlite3.connect(str(data_path.resolve())) as conn:
        conn.execute("DELETE FROM kline WHERE date < ?", (cutoff,))


def load_sqlite_kline(args: argparse.Namespace, codes: set[str] | None = None) -> "pd.DataFrame":
    data_path, _meta_path = cache_paths(args)
    ensure_sqlite_cache(data_path)
    cutoff = (datetime.strptime(args.trade_date, "%Y-%m-%d").date() - timedelta(days=args.cache_calendar_days)).isoformat()
    columns = ["code", "date", "name", "open", "high", "low", "close", "volume", "amount"]
    with sqlite3.connect(str(data_path.resolve())) as conn:
        if codes:
            code_list = sorted(codes)
            placeholders = ",".join("?" for _ in code_list)
            query = f"SELECT {', '.join(columns)} FROM kline WHERE date >= ? AND code IN ({placeholders})"
            df = pd.read_sql_query(query, conn, params=[cutoff, *code_list])
        else:
            query = f"SELECT {', '.join(columns)} FROM kline WHERE date >= ?"
            df = pd.read_sql_query(query, conn, params=[cutoff])
    return normalize_kline_frame(df)


def load_market_cache_kline(args: argparse.Namespace, codes: set[str] | None = None) -> "pd.DataFrame":
    if args.ignore_market_cache:
        return pd.DataFrame()
    db_path = market_cache_db_path(args)
    if not db_path.exists():
        return pd.DataFrame()
    cutoff = (datetime.strptime(args.trade_date, "%Y-%m-%d").date() - timedelta(days=args.cache_calendar_days)).isoformat()
    columns = ["code", "trade_date AS date", "name", "open", "high", "low", "close", "volume", "amount"]
    with sqlite3.connect(str(db_path.resolve())) as conn:
        if not sqlite_table_exists(conn, "daily_kline"):
            return pd.DataFrame()
        if codes:
            code_list = sorted(codes)
            placeholders = ",".join("?" for _ in code_list)
            query = (
                f"SELECT {', '.join(columns)} FROM daily_kline "
                f"WHERE trade_date >= ? AND trade_date <= ? AND code IN ({placeholders})"
            )
            df = pd.read_sql_query(query, conn, params=[cutoff, args.trade_date, *code_list])
        else:
            query = f"SELECT {', '.join(columns)} FROM daily_kline WHERE trade_date >= ? AND trade_date <= ?"
            df = pd.read_sql_query(query, conn, params=[cutoff, args.trade_date])
    return normalize_kline_frame(df)


def sqlite_cache_summary(args: argparse.Namespace) -> dict:
    data_path, _meta_path = cache_paths(args)
    ensure_sqlite_cache(data_path)
    with sqlite3.connect(str(data_path.resolve())) as conn:
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) FROM kline"
        ).fetchone()
    return {
        "row_count": int(row[0] or 0),
        "cached_stock_count": int(row[1] or 0),
        "earliest_date": row[2] or "",
        "latest_date": row[3] or "",
    }


def load_cached_kline(args: argparse.Namespace, codes: set[str] | None = None) -> "pd.DataFrame":
    migrate_legacy_csv_cache(args)
    trim_sqlite_cache(args)
    return load_sqlite_kline(args, codes)


def save_cached_kline(df: "pd.DataFrame", stock_rows: list[dict], args: argparse.Namespace, mode: str, failures: int) -> tuple[Path, Path]:
    data_path, meta_path = cache_paths(args)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    df = normalize_kline_frame(df)
    upsert_sqlite_kline(df, args)
    trim_sqlite_cache(args)
    cached = load_sqlite_kline(args, {row["code"] for row in stock_rows})
    failed_path, unresolved_count = write_failed_kline_codes(cached, stock_rows, args)
    summary = sqlite_cache_summary(args)
    meta = {
        "skill": SKILL_NAME,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": args.trade_date,
        "mode": mode,
        "source": "东方财富日K接口",
        "stock_count": len(stock_rows),
        "cached_stock_count": summary["cached_stock_count"],
        "complete_stock_count": len(complete_cache_codes(cached, args.trade_date)),
        "unresolved_stock_count": unresolved_count,
        "row_count": summary["row_count"],
        "earliest_date": summary["earliest_date"],
        "latest_date": summary["latest_date"],
        "failures": failures,
        "failed_codes_path": str(failed_path),
        "cache_calendar_days": args.cache_calendar_days,
        "cache_backend": "sqlite",
        "legacy_csv_path": str(legacy_cache_csv_path(args)),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return data_path, meta_path


def fetch_kline_frames(stock_rows: list[dict], args: argparse.Namespace, lookback_days: int) -> tuple[list["pd.DataFrame"], int]:
    frames: list[pd.DataFrame] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        future_map = {
            pool.submit(fetch_kline, row["code"], args.trade_date, lookback_days, args.request_timeout): row["code"]
            for row in stock_rows
        }
        for future in as_completed(future_map):
            try:
                frame = future.result()
                code = future_map[future]
                name = next((row["name"] for row in stock_rows if row["code"] == code), code)
                if not frame.empty:
                    frame["name"] = name
                    frames.append(frame)
            except Exception:
                failures += 1
    return frames, failures


def fetch_baostock_supplement(stock_rows: list[dict], args: argparse.Namespace) -> tuple[list["pd.DataFrame"], int]:
    if bs is None or args.no_baostock_fallback or not stock_rows:
        return [], 0
    frames: list[pd.DataFrame] = []
    failures = 0
    login = bs.login()
    if getattr(login, "error_code", "1") != "0":
        return [], len(stock_rows)
    try:
        for idx, row in enumerate(stock_rows, start=1):
            try:
                frame = fetch_baostock_kline_logged_in(row["code"], args.trade_date, args.initial_lookback_days)
                if not frame.empty:
                    frame["name"] = row.get("name", row["code"])
                    frames.append(frame)
                else:
                    failures += 1
            except Exception:
                failures += 1
            if idx % max(1, args.baostock_batch_log) == 0:
                print(f"baostock supplement: tried {idx}/{len(stock_rows)}, frames {len(frames)}, failures {failures}", flush=True)
    finally:
        bs.logout()
    return frames, failures


def batched(items: list[dict], size: int) -> list[list[dict]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def build_or_update_kline_cache(stock_rows: list[dict], args: argparse.Namespace, list_source: str) -> tuple["pd.DataFrame", dict]:
    names = {row["code"]: row["name"] for row in stock_rows}
    data_path, meta_path = cache_paths(args)
    stock_codes = set(names)
    cached = load_cached_kline(args, stock_codes)
    market_cached = load_market_cache_kline(args, stock_codes)
    market_cache_rows = len(market_cached)
    if not market_cached.empty:
        market_cached["name"] = market_cached["code"].map(names).fillna(market_cached.get("name", ""))
        save_cached_kline(market_cached, stock_rows, args, mode="market_cache_seed", failures=0)
        cached = load_cached_kline(args, stock_codes)
    stock_count = len(stock_rows)
    mode = "incremental"
    failures = 0
    if args.refresh_cache or cached.empty:
        mode = "initial_full_fetch" if cached.empty else "resume_full_fetch"
        complete_codes = complete_cache_codes(cached, args.trade_date)
        pending_rows = [row for row in stock_rows if row["code"] not in complete_codes]
        merged = cached
        if not args.no_network:
            for batch_no, batch in enumerate(batched(pending_rows, args.batch_size), start=1):
                frames, batch_failures = fetch_kline_frames(batch, args, args.initial_lookback_days)
                failures += batch_failures
                if frames:
                    fetched = pd.concat(frames, ignore_index=True)
                    merged = pd.concat([merged, fetched], ignore_index=True) if not merged.empty else fetched
                    merged = normalize_kline_frame(merged)
                    if not merged.empty:
                        merged["name"] = merged["code"].map(names).fillna(merged.get("name", ""))
                    save_cached_kline(
                        fetched,
                        stock_rows,
                        args,
                        mode=f"{mode}_batch_{batch_no}",
                        failures=failures,
                    )
                print(
                    f"cache batch {batch_no}: fetched {len(batch)} symbols, "
                    f"cached {int(merged['code'].nunique()) if not merged.empty else 0}/{stock_count}, "
                    f"failures {failures}",
                    flush=True,
                )
        if merged.empty:
            raise SystemExit("No kline data available. Check ashare-kline-sqlite-cache, network access, or use --kline-csv.")
        unresolved_after_primary = [
            row for row in stock_rows if row["code"] not in complete_cache_codes(normalize_kline_frame(merged), args.trade_date)
        ]
        if unresolved_after_primary and not args.no_network and not args.no_baostock_fallback:
            print(f"baostock supplement: {len(unresolved_after_primary)} unresolved symbols", flush=True)
            supplement_frames, supplement_failures = fetch_baostock_supplement(unresolved_after_primary, args)
            failures += supplement_failures
            if supplement_frames:
                supplement = pd.concat(supplement_frames, ignore_index=True)
                merged = pd.concat([merged, supplement], ignore_index=True)
                merged = normalize_kline_frame(merged)
                if not merged.empty:
                    merged["name"] = merged["code"].map(names).fillna(merged.get("name", ""))
                save_cached_kline(
                    supplement,
                    stock_rows,
                    args,
                    mode=f"{mode}_baostock_supplement",
                    failures=failures,
                )
    else:
        if args.no_network:
            frames = []
            failures = 0
        else:
            frames, failures = fetch_kline_frames(stock_rows, args, args.incremental_lookback_days)
        if frames:
            fetched = pd.concat(frames, ignore_index=True)
            save_cached_kline(fetched, stock_rows, args, mode=mode, failures=failures)
            merged = load_cached_kline(args, stock_codes)
        else:
            merged = cached

    merged = normalize_kline_frame(merged)
    if not merged.empty:
        merged["name"] = merged["code"].map(names).fillna(merged.get("name", ""))
    save_cached_kline(pd.DataFrame(), stock_rows, args, mode=mode, failures=failures)
    source = (
        f"{list_source}+ashare-kline-sqlite-cache SQLite优先+腾讯/东方财富/BaoStock日K缓存；缓存 `{data_path}`；元数据 `{meta_path}`；"
        f"更新模式 {mode}；K线抓取失败 {failures} 只"
    )
    return merged, {
        "source": source,
        "cache_path": str(data_path),
        "cache_meta_path": str(meta_path),
        "market_cache_path": str(market_cache_db_path(args)),
        "market_cache_seed_rows": market_cache_rows,
        "failed_codes_path": str(failed_codes_path(args)),
        "cache_update_mode": mode,
        "kline_failures": failures,
    }


def volume_base(series: "pd.Series", idx: int, mode: str) -> float:
    if mode == "prev":
        return float(series.iloc[idx - 1])
    if mode == "ma5":
        return float(series.iloc[max(0, idx - 5) : idx].mean())
    if mode == "ma20":
        return float(series.iloc[max(0, idx - 20) : idx].mean())
    raise ValueError(f"unsupported volume base: {mode}")


def trend_check(df: "pd.DataFrame", lookback: int, min_return_pct: float) -> dict:
    if len(df) < 90:
        return {"pass": False, "reason": "上市时间不足或日K少于90根"}

    work = df.copy()
    work["ma20"] = work["close"].rolling(20).mean()
    work["ma60"] = work["close"].rolling(60).mean()
    window = work.tail(min(lookback, len(work))).copy()
    if len(window) < 90 or pd.isna(work["ma60"].iloc[-1]):
        return {"pass": False, "reason": "6个月趋势窗口不足"}

    last_close = float(work["close"].iloc[-1])
    first_close = float(window["close"].iloc[0])
    ma20 = float(work["ma20"].iloc[-1])
    ma60 = float(work["ma60"].iloc[-1])
    ma60_prev = float(work["ma60"].iloc[-21]) if len(work) > 80 and not pd.isna(work["ma60"].iloc[-21]) else math.nan
    six_month_return_pct = (last_close / first_close - 1) * 100 if first_close else math.nan

    recent = window.tail(63)
    prior = window.iloc[: max(0, len(window) - 63)]
    higher_high = bool(len(prior) > 0 and recent["high"].max() >= prior["high"].max())

    checks = {
        "6个月涨幅达标": six_month_return_pct >= min_return_pct,
        "收盘在60日线上": last_close > ma60,
        "20日线在60日线上": ma20 > ma60,
        "60日线向上": not math.isnan(ma60_prev) and ma60 > ma60_prev,
        "阶段高点抬升": higher_high,
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {
        "pass": passed >= 4 and last_close > ma60,
        "reason": "、".join(name for name, ok in checks.items() if not ok) or "趋势达标",
        "checks": checks,
        "passed": passed,
        "six_month_return_pct": six_month_return_pct,
        "ma20": ma20,
        "ma60": ma60,
        "last_close": last_close,
    }


def find_confirmed_event(df: "pd.DataFrame", recent_days: int, volume_base_mode: str, hold_by: str) -> tuple[dict | None, list[dict]]:
    events: list[dict] = []
    n = len(df)
    start = max(1, n - recent_days)
    end = n - 1
    for idx in range(start, end):
        prev_close = float(df["close"].iloc[idx - 1])
        spike_close = float(df["close"].iloc[idx])
        spike_volume = float(df["volume"].iloc[idx])
        base = volume_base(df["volume"], idx, volume_base_mode)
        if not base or math.isnan(base) or base <= 0:
            continue
        multiple = spike_volume / base
        gain = spike_close - prev_close
        if multiple < 2 or gain <= 0:
            continue

        hold_line = prev_close + gain * 0.5
        next_row = df.iloc[idx + 1]
        hold_value = float(next_row[hold_by])
        passed = hold_value >= hold_line
        event = {
            "event_date": str(df["date"].iloc[idx]),
            "next_date": str(next_row["date"]),
            "volume_multiple": multiple,
            "spike_gain_pct": gain / prev_close * 100 if prev_close else math.nan,
            "prev_close": prev_close,
            "spike_close": spike_close,
            "hold_line": hold_line,
            "hold_by": hold_by,
            "next_hold_value": hold_value,
            "hold_margin_pct": (hold_value / hold_line - 1) * 100 if hold_line else math.nan,
            "passed": passed,
        }
        events.append(event)

    latest_idx = n - 1
    if latest_idx >= start:
        prev_close = float(df["close"].iloc[latest_idx - 1])
        spike_close = float(df["close"].iloc[latest_idx])
        spike_volume = float(df["volume"].iloc[latest_idx])
        base = volume_base(df["volume"], latest_idx, volume_base_mode)
        gain = spike_close - prev_close
        if base and not math.isnan(base) and base > 0 and spike_volume / base >= 2 and gain > 0:
            events.append(
                {
                    "event_date": str(df["date"].iloc[latest_idx]),
                    "volume_multiple": spike_volume / base,
                    "spike_gain_pct": gain / prev_close * 100 if prev_close else math.nan,
                    "prev_close": prev_close,
                    "spike_close": spike_close,
                    "passed": None,
                    "pending": True,
                }
            )

    passed_events = [event for event in events if event["passed"]]
    if not passed_events:
        return None, events
    passed_events.sort(key=lambda item: (item["volume_multiple"], item["hold_margin_pct"]), reverse=True)
    return passed_events[0], events


def screen_group(
    code: str,
    name: str,
    df: "pd.DataFrame",
    args: argparse.Namespace,
) -> tuple[dict | None, dict]:
    df = df.sort_values("date").dropna(subset=["open", "high", "low", "close", "volume"])
    df = df[(df["close"] > 0) & (df["volume"] > 0)]
    if args.trade_date:
        df = df[df["date"] <= args.trade_date]
    latest_date = str(df["date"].iloc[-1]) if len(df) else ""
    if len(df) < 90:
        return None, {"reason": "上市时间不足或日K不足", "latest_date": latest_date}

    trend = trend_check(df, args.lookback_days, args.min_6m_return_pct)
    if not trend["pass"]:
        return None, {"reason": f"趋势不足：{trend['reason']}", "latest_date": latest_date}

    event, all_events = find_confirmed_event(df, args.recent_days, args.volume_base, args.hold_by)
    if not event:
        reason = "近5日无放量上涨事件"
        if any(item.get("pending") for item in all_events):
            reason = "最近一日放量待次日确认"
        elif all_events:
            reason = "放量上涨后次日未守住半幅"
        return None, {"reason": reason, "latest_date": latest_date, "events": all_events}

    score = (
        trend["passed"] * 10
        + min(max(trend["six_month_return_pct"], 0), 80) * 0.35
        + min(event["volume_multiple"], 5) * 8
        + min(max(event["hold_margin_pct"], 0), 10) * 2
    )
    row = {
        "code": code,
        "name": name,
        "latest_date": latest_date,
        "latest_close": trend["last_close"],
        "six_month_return_pct": trend["six_month_return_pct"],
        "trend_passed": trend["passed"],
        "trend_checks": trend["checks"],
        "ma20": trend["ma20"],
        "ma60": trend["ma60"],
        "score": score,
        **event,
    }
    return row, {"reason": "passed", "latest_date": latest_date}


def screen_dataframe(df: "pd.DataFrame", args: argparse.Namespace, names: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    names = names or {}
    results: list[dict] = []
    reject_reasons: dict[str, int] = {}
    latest_dates: dict[str, int] = {}
    for code, group in df.groupby("code"):
        name = names.get(code)
        if not name and "name" in group.columns:
            values = group["name"].dropna().astype(str)
            name = values.iloc[-1] if len(values) else code
        row, meta = screen_group(code, name or code, group, args)
        latest = meta.get("latest_date") or ""
        latest_dates[latest] = latest_dates.get(latest, 0) + 1
        if row:
            results.append(row)
        else:
            reason = meta.get("reason", "未通过")
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
    results.sort(key=lambda item: item["score"], reverse=True)
    return results, {"reject_reasons": reject_reasons, "latest_dates": latest_dates}


def build_report(results: list[dict], meta: dict, args: argparse.Namespace) -> str:
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trade_date = args.trade_date or date.today().isoformat()
    latest_dates = sorted(meta.get("latest_dates", {}).items(), key=lambda kv: kv[1], reverse=True)
    representative_latest = latest_dates[0][0] if latest_dates else ""
    source = meta.get("source", "")
    scanned = meta.get("scanned_count", 0)
    shown = results[: args.max_results]
    market_cap_filter = (
        f">= {meta.get('market_cap_filter_text', format_market_cap_threshold(float(args.min_market_cap_yuan or 0)))}; "
        f"source {meta.get('market_cap_source', 'unknown')}; "
        f"kept {meta.get('market_cap_kept_count', scanned)}/{meta.get('market_cap_input_count', scanned)}, "
        f"removed below threshold {meta.get('market_cap_removed_small_count', 0)}, "
        f"removed missing market cap {meta.get('market_cap_removed_missing_count', 0)}"
    )

    lines = [
        "# 全A上升趋势放量守涨筛选结果",
        "",
        f"筛选日期：{trade_date}",
        f"执行技能：{SKILL_NAME}",
        f"运行时间：{run_time}",
        "结果类型：研究观察池，不是最终买入名单",
        "",
        "## 数据说明",
        f"- 数据来源：{source}",
        f"- 缓存说明：首次运行全量拉取近6个月日K并写入 `{meta.get('cache_path', '无')}`；后续运行默认只增量更新最近/当日日K。当前模式：{meta.get('cache_update_mode', '离线/未知')}。",
        f"- 失败清单：`{meta.get('failed_codes_path', '无')}`；缓存未覆盖或最新K线未到筛选日的代码会写入该文件。",
        f"- 扫描范围：{scanned} 只标的；合格 {len(results)} 只；报告展示前 {len(shown)} 只。",
        f"- 最新K线日期：代表日期 {representative_latest or '未知'}；如与筛选日期不一致，表示数据可能不是当日完整收盘结果。",
        f"- 趋势口径：近约 {args.lookback_days} 个交易日，至少 4 项趋势条件达标，且最新收盘价在60日线上。",
        f"- 放量口径：近 {args.recent_days} 个交易日内，成交量相对 `{args.volume_base}` 翻倍及以上，且放量日收盘上涨。",
        f"- 守涨口径：放量次日 `{args.hold_by}` 不低于“前收 + 放量日涨幅一半”。",
        "",
        "## 一、筛选结论",
    ]
    lines.insert(14, f"- Market cap filter: {market_cap_filter}.")
    if results:
        top_names = "、".join(f"{row['name']}({row['code']})" for row in shown[:10])
        lines.append(f"- 合格观察池：{top_names}")
    else:
        lines.append("- 合格观察池：本次没有发现完全满足条件的标的。")

    reject_reasons = meta.get("reject_reasons", {})
    pending_count = int(reject_reasons.get("最近一日放量待次日确认", 0))
    if reject_reasons:
        reason_text = "；".join(f"{key} {value} 只" for key, value in sorted(reject_reasons.items(), key=lambda kv: kv[1], reverse=True)[:6])
        lines.append(f"- 主要未通过原因：{reason_text}")
    lines.append(f"- 待次日确认：{pending_count} 只。")

    lines.extend(
        [
            "",
            "## 二、核心表格",
            "| 排名 | 标的 | 代码 | 最新收盘 | 最新K线 | 6个月涨幅 | 趋势条件 | 放量日 | 量能倍数 | 放量日涨幅 | 半幅防线 | 次日表现 | 守涨余量 | 评分 | 观察状态 |",
            "|---:|---|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for rank, row in enumerate(shown, start=1):
        lines.append(
            "| {rank} | {name} | {code} | {latest_close:.2f} | {latest_date} | {ret} | {trend}/5 | {event_date} | {vol} | {gain} | {hold_line:.2f} | {next_value:.2f} | {margin} | {score:.1f} | {status} |".format(
                rank=rank,
                name=row["name"],
                code=row["code"],
                latest_close=row["latest_close"],
                latest_date=row["latest_date"],
                ret=fmt_pct(row["six_month_return_pct"]),
                trend=row["trend_passed"],
                event_date=row["event_date"],
                vol=f"{row['volume_multiple']:.2f}x",
                gain=fmt_pct(row["spike_gain_pct"]),
                hold_line=row["hold_line"],
                next_value=row["next_hold_value"],
                margin=fmt_pct(row["hold_margin_pct"]),
                score=row["score"],
                status="合格观察",
            )
        )

    lines.extend(["", "## 三、逐个点评"])
    if not shown:
        lines.append("本次没有可点评的合格标的。")
    for row in shown[:20]:
        checks = "、".join(name for name, ok in row["trend_checks"].items() if ok)
        invalidation = f"若收盘跌破60日线，或跌破放量日半幅防线 {row['hold_line']:.2f} 后无法快速收回，则降级观察。"
        lines.extend(
            [
                f"### {row['name']}（{row['code']}）",
                f"- 趋势结构：近6个月涨幅 {fmt_pct(row['six_month_return_pct'])}，趋势条件 {row['trend_passed']}/5 达标（{checks}）。",
                f"- 放量与承接：{row['event_date']} 成交量达到基准的 {row['volume_multiple']:.2f} 倍，收盘涨幅 {fmt_pct(row['spike_gain_pct'])}；次日 {row['hold_by']} 为 {row['next_hold_value']:.2f}，相对半幅防线余量 {fmt_pct(row['hold_margin_pct'])}。",
                f"- 支撑/失效：20日线约 {row['ma20']:.2f}，60日线约 {row['ma60']:.2f}。{invalidation}",
            ]
        )

    lines.extend(
        [
            "",
            "## 四、数据限制与风险提示",
            "- 本筛选只验证趋势和量价结构，不验证财报、公告、行业景气或资金席位。",
            "- 放量守涨是观察条件，不等于后续一定延续；若市场环境转弱、板块退潮或个股放量滞涨，应重新评估。",
            "- 若使用联网接口，结果依赖接口可用性和收盘数据刷新；若使用本地 CSV，结果依赖用户提供数据的完整性和复权口径。",
            "",
            "以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。",
            "",
        ]
    )
    return "\n".join(lines)


def fmt_pct(value: float) -> str:
    if value is None or math.isnan(float(value)):
        return "NA"
    return f"{float(value):.2f}%"


def save_report(report: str, args: argparse.Namespace) -> Path:
    output_dir = report_dir(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = args.output_name or f"{args.trade_date}.md"
    output_path = output_dir / filename
    output_path.write_text(report, encoding="utf-8")
    return output_path


def run_network_scan(args: argparse.Namespace) -> tuple[list[dict], dict]:
    stock_rows, list_source = fetch_stock_list(args, limit=args.limit)
    if args.symbols:
        wanted = {normalize_code(code) for code in args.symbols.split(",") if code.strip()}
        stock_rows = [row for row in stock_rows if row["code"] in wanted]
    stock_rows, market_cap_meta = filter_stock_rows_by_market_cap(stock_rows, args)
    if not stock_rows:
        empty = pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "volume"])
        results, meta = screen_dataframe(empty, args)
        meta.update(market_cap_meta)
        meta["source"] = f"{list_source}; no symbols passed market cap filter"
        meta["cache_path"] = str(cache_paths(args)[0])
        meta["failed_codes_path"] = str(failed_codes_path(args))
        meta["cache_update_mode"] = "skipped_no_market_cap_eligible_symbols"
        meta["scanned_count"] = 0
        return results, meta
    df, cache_meta = build_or_update_kline_cache(stock_rows, args, list_source)
    eligible_codes = {row["code"] for row in stock_rows}
    if not df.empty:
        df = df[df["code"].isin(eligible_codes)].copy()
    names = {row["code"]: row["name"] for row in stock_rows}
    results, meta = screen_dataframe(df, args, names=names)
    meta.update(cache_meta)
    meta.update(market_cap_meta)
    meta["scanned_count"] = len(stock_rows)
    return results, meta


def run_csv_scan(args: argparse.Namespace) -> tuple[list[dict], dict]:
    df = load_kline_csv(Path(args.kline_csv))
    if args.symbols:
        wanted = {normalize_code(code) for code in args.symbols.split(",") if code.strip()}
        df = df[df["code"].isin(wanted)]
    df, market_cap_meta = filter_dataframe_by_market_cap(df, args)
    results, meta = screen_dataframe(df, args)
    meta.update(market_cap_meta)
    meta["source"] = f"本地CSV离线数据：{args.kline_csv}"
    default_failed_path = failed_codes_path(args)
    meta["cache_path"] = args.kline_csv
    meta["failed_codes_path"] = str(default_failed_path) if default_failed_path.exists() else "无"
    meta["cache_update_mode"] = "offline_csv"
    meta["scanned_count"] = int(df["code"].nunique())
    return results, meta


def make_self_test_frame() -> "pd.DataFrame":
    rows = []
    start = date(2025, 11, 1)
    for code, name, trend, should_hold in [
        ("000001", "通过样本", True, True),
        ("000002", "守涨失败", True, False),
        ("000003", "趋势失败", False, True),
    ]:
        close = 10.0
        prev = close
        for i in range(150):
            day = start + timedelta(days=i)
            drift = 0.035 if trend else -0.01
            close = close * (1 + drift / 10)
            volume = 1000 + i * 2
            if i == 146:
                prev = close
                close = close * 1.04
                volume = volume * 2.4
            if i == 147:
                if should_hold:
                    close = prev + (close - prev) * 0.75
                else:
                    close = prev + (close - prev) * 0.25
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "date": day.isoformat(),
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": volume,
                }
            )
    return pd.DataFrame(rows)


def self_test(args: argparse.Namespace) -> None:
    args.ignore_market_cache = True
    args.trade_date = "2026-03-30"
    args.min_6m_return_pct = 3
    df = make_self_test_frame()
    results, _meta = screen_dataframe(df, args)
    codes = {row["code"] for row in results}
    assert "000001" in codes, "passing sample should pass"
    assert "000002" not in codes, "hold-failure sample should fail"
    assert "000003" not in codes, "trend-failure sample should fail"
    args.min_market_cap_yuan = DEFAULT_MIN_MARKET_CAP_YUAN
    filtered_rows, market_cap_meta = filter_stock_rows_by_market_cap(
        [
            {"code": "000001", "name": "large", "total_mv": 25_000_000_000},
            {"code": "000002", "name": "small", "total_mv": 19_000_000_000},
            {"code": "000003", "name": "missing", "total_mv": math.nan},
        ],
        args,
    )
    assert [row["code"] for row in filtered_rows] == ["000001"], "market cap filter should keep only >= 20bn yuan"
    assert market_cap_meta["market_cap_removed_small_count"] == 1, "small market cap sample should be removed"
    assert market_cap_meta["market_cap_removed_missing_count"] == 1, "missing market cap sample should be removed"
    filtered_rows_10k, market_cap_meta_10k = filter_stock_rows_by_market_cap(
        [
            {"code": "000001", "name": "large_10k_cny", "total_mv": 2_500_000},
            {"code": "000002", "name": "small_10k_cny", "total_mv": 1_900_000},
        ],
        args,
    )
    assert [row["code"] for row in filtered_rows_10k] == ["000001"], "10k-CNY market cap values should be normalized"
    assert market_cap_meta_10k["market_cap_value_scale"] == 10_000.0, "10k-CNY scale should be reported"
    with TemporaryDirectory() as temp_dir:
        args.runs_dir = temp_dir
        args.cache_dir = None
        args.cache_calendar_days = 430
        stock_rows = [
            {"code": "000001", "name": "通过样本"},
            {"code": "000002", "name": "守涨失败"},
            {"code": "000003", "name": "趋势失败"},
        ]
        data_path, meta_path = save_cached_kline(df, stock_rows, args, mode="self_test", failures=0)
        cached = load_cached_kline(args)
        assert data_path.exists(), "sqlite cache should be saved"
        assert data_path.suffix == ".sqlite", "network cache should use sqlite backend"
        assert meta_path.exists(), "cache metadata should be saved"
        assert len(cached) == len(df), "cache reload should preserve rows"
        filtered_cached = load_cached_kline(args, {"000001"})
        assert set(filtered_cached["code"].unique()) == {"000001"}, "sqlite cache should support code-scoped reads"
    with TemporaryDirectory() as temp_dir:
        args.runs_dir = temp_dir
        args.cache_dir = None
        args.cache_calendar_days = 430
        legacy_path = legacy_cache_csv_path(args)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(legacy_path, index=False, encoding="utf-8-sig")
        migrated = load_cached_kline(args, {"000001"})
        assert cache_paths(args)[0].exists(), "legacy csv should migrate to sqlite"
        assert set(migrated["code"].unique()) == {"000001"}, "migrated cache should support code-scoped reads"
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen A-shares for 6m uptrend + recent doubled volume + next-day half-gain hold.")
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--kline-csv")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--symbols", help="comma-separated stock codes")
    parser.add_argument("--limit", type=int, help="limit full-market list for development")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=100, help="persist kline cache after each batch during full/resume fetch")
    parser.add_argument("--request-timeout", type=int, default=8, help="single HTTP request timeout in seconds")
    parser.add_argument("--no-baostock-fallback", action="store_true", help="disable BaoStock third-source supplement for unresolved symbols")
    parser.add_argument("--baostock-batch-log", type=int, default=50, help="log interval for BaoStock supplement attempts")
    parser.add_argument("--cache-dir", help="default: runs/ashare-volume-doubled-uptrend/kline-cache")
    parser.add_argument(
        "--market-cache-db",
        default=str(DEFAULT_MARKET_CACHE_DB),
        help="SQLite cache from ashare-kline-sqlite-cache; used before public APIs.",
    )
    parser.add_argument("--ignore-market-cache", action="store_true", help="Skip ashare-kline-sqlite-cache SQLite reads.")
    parser.add_argument("--refresh-cache", action="store_true", help="force one-time full 6-month kline fetch")
    parser.add_argument("--initial-lookback-days", type=int, default=430, help="calendar days to fetch when cache is empty or refreshed")
    parser.add_argument("--incremental-lookback-days", type=int, default=12, help="calendar days to fetch on normal daily runs")
    parser.add_argument("--cache-calendar-days", type=int, default=430, help="calendar days retained in the shared kline cache")
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--recent-days", type=int, default=5)
    parser.add_argument("--volume-base", choices=["prev", "ma5", "ma20"], default="prev")
    parser.add_argument("--hold-by", choices=["close", "low"], default="close")
    parser.add_argument("--min-6m-return-pct", type=float, default=8.0)
    parser.add_argument(
        "--min-market-cap-yuan",
        type=float,
        default=DEFAULT_MIN_MARKET_CAP_YUAN,
        help="minimum total market cap in yuan; default excludes companies below 20bn yuan; set 0 to disable",
    )
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--output-name", help="optional report filename inside the trade-date run directory")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test(args)
        return

    if args.kline_csv:
        results, meta = run_csv_scan(args)
    else:
        results, meta = run_network_scan(args)

    report = build_report(results, meta, args)
    output_path = save_report(report, args)
    print(f"saved: {output_path}")
    print(f"qualified: {len(results)}")


if __name__ == "__main__":
    main()
