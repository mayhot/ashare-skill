import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SKILL_NAME = "ashare-kline-sqlite-cache"
DEFAULT_DB = ROOT / "runs" / SKILL_NAME / "ashare_kline.sqlite"
CHINA_TZ = timezone(timedelta(hours=8))

EASTMONEY_LIST_FIELDS = [
    "f12",  # code
    "f14",  # name
    "f2",  # latest price
    "f3",  # pct chg
    "f4",  # change amount
    "f5",  # volume
    "f6",  # amount
    "f7",  # amplitude
    "f15",  # high
    "f16",  # low
    "f17",  # open
    "f18",  # previous close
    "f10",  # volume ratio
    "f8",  # turnover
    "f9",  # PE dynamic
    "f23",  # PB
    "f20",  # total market value
    "f21",  # circulating market value
    "f22",  # speed
    "f11",  # five minute change
    "f24",  # 60 day change
    "f25",  # YTD change
]
EASTMONEY_LIST_URL = (
    "http://push2.eastmoney.com/api/qt/clist/get?"
    "pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&"
    "fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81&"
    "fields={fields}"
)
EASTMONEY_KLINE_URL = (
    "http://push2his.eastmoney.com/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
    "fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&"
    "klt=101&fqt={fqt}&beg={begin}&end={end}"
)
SINA_LIST_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num=80&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=page"
)
TENCENT_KLINE_URL = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
EASTMONEY_POPULARITY_URLS = [
    "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
    "http://emappdata.eastmoney.com/stockrank/getAllCurrentList",
]
ADJUST_FLAGS = {"none": "0", "qfq": "1", "hfq": "2"}


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


def now_china() -> datetime:
    return datetime.now(CHINA_TZ)


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        left, right = text.split(".", 1)
        text = left if left.isdigit() else right
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ""


def exchange_for_code(code: str) -> str:
    code = normalize_code(code)
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8", "920")):
        return "BJ"
    return "SZ"


def secid_for_code(code: str) -> str:
    code = normalize_code(code)
    # Eastmoney uses 1 for Shanghai and 0 for Shenzhen/Beijing-style symbols.
    market = "1" if exchange_for_code(code) == "SH" else "0"
    return f"{market}.{code}"


def qq_symbol_for_code(code: str) -> str:
    code = normalize_code(code)
    exchange = exchange_for_code(code)
    if exchange == "SH":
        return f"sh{code}"
    if exchange == "BJ":
        return f"bj{code}"
    return f"sz{code}"


def to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def request_json(url: str, timeout: int) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 + attempt)
    raise last_error or RuntimeError("request failed")


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://quote.eastmoney.com/",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 + attempt)
    raise last_error or RuntimeError("request failed")


def fetch_stock_universe(
    limit: int | None,
    timeout: int,
    prefer_akshare: bool,
) -> tuple[list[dict[str, Any]], str]:
    if prefer_akshare:
        try:
            rows = fetch_stock_universe_akshare(limit)
            if rows:
                return rows, "akshare.stock_zh_a_spot_em"
        except Exception as exc:
            print(f"akshare universe unavailable, falling back to Eastmoney: {exc}")
    try:
        rows = fetch_stock_universe_eastmoney(limit, timeout)
        if rows:
            return rows, "eastmoney.clist"
    except Exception as exc:
        print(f"Eastmoney universe unavailable, falling back to Sina: {exc}")
    rows = fetch_stock_universe_sina(limit, timeout)
    return rows, "sina.market_center"


def fetch_stock_universe_akshare(limit: int | None) -> list[dict[str, Any]]:
    import akshare as ak  # type: ignore

    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        return []
    column_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "latest_price",
        "涨跌幅": "pct_chg",
        "涨跌额": "change_amount",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "previous_close",
        "量比": "volume_ratio",
        "换手率": "turnover",
        "市盈率-动态": "pe_dynamic",
        "市净率": "pb",
        "总市值": "total_mv",
        "流通市值": "circ_mv",
        "涨速": "speed",
        "5分钟涨跌": "five_minute_chg",
        "60日涨跌幅": "sixty_day_chg",
        "年初至今涨跌幅": "ytd_chg",
    }
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict("records"):
        code = normalize_code(raw.get("代码"))
        if not code:
            continue
        row = {column_map.get(str(key), str(key)): value for key, value in raw.items()}
        row["code"] = code
        row["name"] = str(row.get("name") or "").strip()
        row["exchange"] = exchange_for_code(code)
        row["secid"] = secid_for_code(code)
        row["raw_json"] = json.dumps(raw, ensure_ascii=False, default=str)
        rows.append(row)
        if limit and len(rows) >= limit:
            break
    return rows


def fetch_stock_universe_eastmoney(limit: int | None, timeout: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    fields = ",".join(EASTMONEY_LIST_FIELDS)
    for page in range(1, 120):
        payload = request_json(EASTMONEY_LIST_URL.format(page=page, fields=fields), timeout)
        diff = ((payload.get("data") or {}).get("diff") or [])
        if not diff:
            break
        for item in diff:
            code = normalize_code(item.get("f12"))
            if not code or code in seen:
                continue
            seen.add(code)
            row = {
                "code": code,
                "name": str(item.get("f14") or "").strip(),
                "exchange": exchange_for_code(code),
                "secid": secid_for_code(code),
                "latest_price": to_float(item.get("f2")),
                "pct_chg": to_float(item.get("f3")),
                "change_amount": to_float(item.get("f4")),
                "volume": to_float(item.get("f5")),
                "amount": to_float(item.get("f6")),
                "amplitude": to_float(item.get("f7")),
                "high": to_float(item.get("f15")),
                "low": to_float(item.get("f16")),
                "open": to_float(item.get("f17")),
                "previous_close": to_float(item.get("f18")),
                "volume_ratio": to_float(item.get("f10")),
                "turnover": to_float(item.get("f8")),
                "pe_dynamic": to_float(item.get("f9")),
                "pb": to_float(item.get("f23")),
                "total_mv": to_float(item.get("f20")),
                "circ_mv": to_float(item.get("f21")),
                "speed": to_float(item.get("f22")),
                "five_minute_chg": to_float(item.get("f11")),
                "sixty_day_chg": to_float(item.get("f24")),
                "ytd_chg": to_float(item.get("f25")),
                "raw_json": json.dumps(item, ensure_ascii=False, default=str),
            }
            rows.append(row)
            if limit and len(rows) >= limit:
                return rows
        time.sleep(0.05)
    return rows


def fetch_stock_universe_sina(limit: int | None, timeout: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 120):
        payload = request_json(SINA_LIST_URL.format(page=page), timeout)
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            code = normalize_code(item.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            row = {
                "code": code,
                "name": str(item.get("name") or "").strip(),
                "exchange": exchange_for_code(code),
                "secid": secid_for_code(code),
                "latest_price": to_float(item.get("trade")),
                "pct_chg": to_float(item.get("changepercent")),
                "change_amount": to_float(item.get("pricechange")),
                "volume": to_float(item.get("volume")),
                "amount": to_float(item.get("amount")),
                "amplitude": None,
                "high": to_float(item.get("high")),
                "low": to_float(item.get("low")),
                "open": to_float(item.get("open")),
                "previous_close": to_float(item.get("settlement")),
                "volume_ratio": None,
                "turnover": to_float(item.get("turnoverratio")),
                "pe_dynamic": to_float(item.get("per")),
                "pb": to_float(item.get("pb")),
                "total_mv": to_float(item.get("mktcap")),
                "circ_mv": to_float(item.get("nmc")),
                "speed": None,
                "five_minute_chg": None,
                "sixty_day_chg": None,
                "ytd_chg": None,
                "raw_json": json.dumps(item, ensure_ascii=False, default=str),
            }
            rows.append(row)
            if limit and len(rows) >= limit:
                return rows
        time.sleep(0.05)
    return rows


def fetch_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
) -> tuple[str, list[dict[str, Any]]]:
    try:
        code, rows = fetch_eastmoney_kline_rows(stock, begin, end, adjust, timeout)
        if rows:
            return code, rows
    except Exception:
        pass
    return fetch_tencent_kline_rows(stock, begin, end, adjust, timeout)


def fetch_eastmoney_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
) -> tuple[str, list[dict[str, Any]]]:
    code = stock["code"]
    url = EASTMONEY_KLINE_URL.format(
        secid=stock.get("secid") or secid_for_code(code),
        begin=begin,
        end=end,
        fqt=ADJUST_FLAGS[adjust],
    )
    payload = request_json(url, timeout)
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": parts[0],
                "name": stock.get("name") or data.get("name") or "",
                "exchange": stock.get("exchange") or exchange_for_code(code),
                "open": to_float(parts[1]),
                "close": to_float(parts[2]),
                "high": to_float(parts[3]),
                "low": to_float(parts[4]),
                "volume": to_float(parts[5]),
                "amount": to_float(parts[6]),
                "amplitude": to_float(parts[7]),
                "pct_chg": to_float(parts[8]),
                "change_amount": to_float(parts[9]),
                "turnover": to_float(parts[10]),
                "source": f"eastmoney.kline.adjust={adjust}",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_line": line,
            }
        )
    return code, rows


def fetch_tencent_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
) -> tuple[str, list[dict[str, Any]]]:
    code = stock["code"]
    symbol = qq_symbol_for_code(code)
    begin_date = f"{begin[:4]}-{begin[4:6]}-{begin[6:]}"
    end_date = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    begin_dt = datetime.strptime(begin_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    datalen = max(30, min(800, int((end_dt - begin_dt).days * 1.6) + 20))
    klines: list[Any] = []
    actual_adjust = adjust
    candidates = [adjust] if adjust != "none" else ["none", "qfq"]
    for candidate in candidates:
        adjust_part = "" if candidate == "none" else f",{candidate}"
        param = urllib.parse.quote(f"{symbol},day,,,{datalen}{adjust_part}", safe="")
        payload = request_json(TENCENT_KLINE_URL.format(param=param), timeout)
        stock_data = ((payload.get("data") or {}).get(symbol) or {})
        key = f"{candidate}day" if candidate != "none" else "day"
        klines = stock_data.get(key) or stock_data.get("day") or []
        if klines:
            actual_adjust = candidate
            break
    rows: list[dict[str, Any]] = []
    for item in klines:
        if len(item) < 6:
            continue
        trade_date = str(item[0])
        if trade_date < begin_date or trade_date > end_date:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": trade_date,
                "name": stock.get("name") or "",
                "exchange": stock.get("exchange") or exchange_for_code(code),
                "open": to_float(item[1]),
                "close": to_float(item[2]),
                "high": to_float(item[3]),
                "low": to_float(item[4]),
                "volume": to_float(item[5]),
                "amount": to_float(item[6]) if len(item) > 6 else None,
                "amplitude": None,
                "pct_chg": None,
                "change_amount": None,
                "turnover": None,
                "source": f"tencent.fqkline.adjust={actual_adjust}",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_line": json.dumps(item, ensure_ascii=False),
            }
        )
    return code, rows


def fetch_popularity_top100(
    trade_date: str,
    timeout: int,
    limit: int,
    prefer_akshare: bool,
) -> tuple[list[dict[str, Any]], str]:
    if prefer_akshare:
        try:
            rows = fetch_popularity_top100_akshare(trade_date, limit)
            if rows:
                return rows, "akshare.stock_hot_rank_em"
        except Exception as exc:
            print(f"akshare popularity unavailable, falling back to Eastmoney app rank: {exc}")
    rows = fetch_popularity_top100_eastmoney(trade_date, timeout, limit)
    return rows, "eastmoney.stockrank.getAllCurrentList"


def fetch_popularity_top100_akshare(trade_date: str, limit: int) -> list[dict[str, Any]]:
    import akshare as ak  # type: ignore

    df = ak.stock_hot_rank_em()
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for rank, raw in enumerate(df.head(limit).to_dict("records"), start=1):
        code = normalize_code(
            raw.get("代码")
            or raw.get("code")
            or raw.get("证券代码")
            or raw.get("股票代码")
        )
        if not code:
            continue
        name = (
            raw.get("名称")
            or raw.get("股票名称")
            or raw.get("name")
            or raw.get("证券简称")
            or ""
        )
        rows.append(
            {
                "trade_date": trade_date,
                "rank": int(to_float(raw.get("排名") or raw.get("rank") or rank) or rank),
                "code": code,
                "name": str(name).strip(),
                "exchange": exchange_for_code(code),
                "hot_value": to_float(raw.get("人气值") or raw.get("热度") or raw.get("hot_value")),
                "rank_change": to_float(raw.get("排名较昨日变动") or raw.get("rank_change")),
                "latest_price": to_float(raw.get("最新价") or raw.get("latest_price")),
                "pct_chg": to_float(raw.get("涨跌幅") or raw.get("pct_chg")),
                "source": "akshare.stock_hot_rank_em",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            }
        )
    rows.sort(key=lambda item: item["rank"])
    return rows[:limit]


def fetch_popularity_top100_eastmoney(
    trade_date: str,
    timeout: int,
    limit: int,
) -> list[dict[str, Any]]:
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": limit,
    }
    last_error: Exception | None = None
    for url in EASTMONEY_POPULARITY_URLS:
        try:
            response = post_json(url, payload, timeout)
            items = extract_popularity_items(response)
            rows = normalize_popularity_items(items, trade_date, limit, "eastmoney.stockrank.getAllCurrentList")
            if rows:
                return rows
        except Exception as exc:
            last_error = exc
    raise last_error or RuntimeError("empty popularity response")


def extract_popularity_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "rank", "rankList", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    for key in ("list", "rank", "rankList", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def normalize_popularity_items(
    items: list[Any],
    trade_date: str,
    limit: int,
    source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fallback_rank, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        code = normalize_popularity_code(item)
        if not code or code in seen:
            continue
        seen.add(code)
        rank = int(
            to_float(
                item.get("rk")
                or item.get("rank")
                or item.get("Rank")
                or item.get("rankNum")
                or fallback_rank
            )
            or fallback_rank
        )
        rows.append(
            {
                "trade_date": trade_date,
                "rank": rank,
                "code": code,
                "name": str(
                    item.get("name")
                    or item.get("n")
                    or item.get("stockName")
                    or item.get("securityName")
                    or ""
                ).strip(),
                "exchange": exchange_for_code(code),
                "hot_value": to_float(item.get("hot") or item.get("heat") or item.get("pv") or item.get("score")),
                "rank_change": to_float(item.get("rankChange") or item.get("change") or item.get("rc")),
                "latest_price": to_float(item.get("price") or item.get("latestPrice") or item.get("zxj")),
                "pct_chg": to_float(item.get("zdf") or item.get("pctChg") or item.get("changePercent")),
                "source": source,
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_json": json.dumps(item, ensure_ascii=False, default=str),
            }
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda item: item["rank"])
    for rank, row in enumerate(rows[:limit], start=1):
        row["rank"] = rank
    return rows[:limit]


def normalize_popularity_code(item: dict[str, Any]) -> str:
    raw = (
        item.get("code")
        or item.get("Code")
        or item.get("securityCode")
        or item.get("stockCode")
        or item.get("sc")
        or item.get("SecurityCode")
    )
    if isinstance(raw, str) and len(raw) >= 8:
        prefix = raw[:2].upper()
        suffix = raw[-6:]
        if prefix in {"SH", "SZ", "BJ"} and suffix.isdigit():
            return suffix
    return normalize_code(raw)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_universe (
            code TEXT PRIMARY KEY,
            name TEXT,
            exchange TEXT,
            secid TEXT,
            latest_price REAL,
            pct_chg REAL,
            change_amount REAL,
            volume REAL,
            amount REAL,
            amplitude REAL,
            high REAL,
            low REAL,
            open REAL,
            previous_close REAL,
            volume_ratio REAL,
            turnover REAL,
            pe_dynamic REAL,
            pb REAL,
            total_mv REAL,
            circ_mv REAL,
            speed REAL,
            five_minute_chg REAL,
            sixty_day_chg REAL,
            ytd_chg REAL,
            raw_json TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_kline (
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            name TEXT,
            exchange TEXT,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            amplitude REAL,
            pct_chg REAL,
            change_amount REAL,
            turnover REAL,
            source TEXT,
            fetched_at TEXT NOT NULL,
            raw_line TEXT,
            PRIMARY KEY (code, trade_date)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_kline_date ON daily_kline(trade_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_kline_code ON daily_kline(code)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS popularity_top100 (
            trade_date TEXT NOT NULL,
            rank INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            exchange TEXT,
            hot_value REAL,
            rank_change REAL,
            latest_price REAL,
            pct_chg REAL,
            source TEXT,
            fetched_at TEXT NOT NULL,
            raw_json TEXT,
            PRIMARY KEY (trade_date, rank)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_popularity_top100_code ON popularity_top100(code)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            requested_trade_date TEXT,
            mode TEXT,
            adjust TEXT,
            stock_count INTEGER DEFAULT 0,
            rows_upserted INTEGER DEFAULT 0,
            failures INTEGER DEFAULT 0,
            retained_trade_days INTEGER DEFAULT 0,
            cutoff_trade_date TEXT,
            data_source TEXT,
            latest_dates_json TEXT,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fetch_failures (
            run_id INTEGER,
            code TEXT,
            name TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )


def start_run(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    cur = conn.execute(
        """
        INSERT INTO sync_runs (started_at, requested_trade_date, mode, adjust, retained_trade_days)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
            args.trade_date,
            args.mode,
            args.adjust,
            args.retain_trading_days,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    stock_count: int,
    rows_upserted: int,
    failures: int,
    cutoff_trade_date: str | None,
    data_source: str,
    latest_dates: list[dict[str, Any]],
    notes: str,
) -> None:
    conn.execute(
        """
        UPDATE sync_runs
        SET finished_at = ?,
            stock_count = ?,
            rows_upserted = ?,
            failures = ?,
            cutoff_trade_date = ?,
            data_source = ?,
            latest_dates_json = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
            stock_count,
            rows_upserted,
            failures,
            cutoff_trade_date,
            data_source,
            json.dumps(latest_dates, ensure_ascii=False),
            notes,
            run_id,
        ),
    )
    conn.commit()


def upsert_stock_universe(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    updated_at = now_china().strftime("%Y-%m-%d %H:%M:%S%z")
    columns = [
        "code",
        "name",
        "exchange",
        "secid",
        "latest_price",
        "pct_chg",
        "change_amount",
        "volume",
        "amount",
        "amplitude",
        "high",
        "low",
        "open",
        "previous_close",
        "volume_ratio",
        "turnover",
        "pe_dynamic",
        "pb",
        "total_mv",
        "circ_mv",
        "speed",
        "five_minute_chg",
        "sixty_day_chg",
        "ytd_chg",
        "raw_json",
        "updated_at",
    ]
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{col}=excluded.{col}" for col in columns if col != "code")
    values = []
    for row in rows:
        values.append(tuple(row.get(col) if col != "updated_at" else updated_at for col in columns))
    conn.executemany(
        f"""
        INSERT INTO stock_universe ({",".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(code) DO UPDATE SET {updates}
        """,
        values,
    )
    conn.commit()


def upsert_kline_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    columns = [
        "code",
        "trade_date",
        "name",
        "exchange",
        "open",
        "close",
        "high",
        "low",
        "volume",
        "amount",
        "amplitude",
        "pct_chg",
        "change_amount",
        "turnover",
        "source",
        "fetched_at",
        "raw_line",
    ]
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{col}=excluded.{col}" for col in columns if col not in ("code", "trade_date"))
    values = [tuple(row.get(col) for col in columns) for row in rows]
    conn.executemany(
        f"""
        INSERT INTO daily_kline ({",".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(code, trade_date) DO UPDATE SET {updates}
        """,
        values,
    )
    conn.commit()
    return len(rows)


def replace_popularity_top100(conn: sqlite3.Connection, trade_date: str, rows: list[dict[str, Any]]) -> int:
    conn.execute("DELETE FROM popularity_top100 WHERE trade_date = ?", (trade_date,))
    if not rows:
        conn.commit()
        return 0
    columns = [
        "trade_date",
        "rank",
        "code",
        "name",
        "exchange",
        "hot_value",
        "rank_change",
        "latest_price",
        "pct_chg",
        "source",
        "fetched_at",
        "raw_json",
    ]
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{col}=excluded.{col}" for col in columns if col not in ("trade_date", "rank"))
    conn.executemany(
        f"""
        INSERT INTO popularity_top100 ({",".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(trade_date, rank) DO UPDATE SET {updates}
        """,
        [tuple(row.get(col) for col in columns) for row in rows],
    )
    conn.commit()
    return len(rows)


def add_failures(conn: sqlite3.Connection, run_id: int, failures: list[tuple[str, str, str]]) -> None:
    if not failures:
        return
    created_at = now_china().strftime("%Y-%m-%d %H:%M:%S%z")
    conn.executemany(
        "INSERT INTO fetch_failures (run_id, code, name, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        [(run_id, code, name, reason, created_at) for code, name, reason in failures],
    )
    conn.commit()


def prune_to_latest_trade_days(conn: sqlite3.Connection, retain: int) -> str | None:
    dates = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT trade_date FROM daily_kline ORDER BY trade_date DESC"
        ).fetchall()
    ]
    if len(dates) <= retain:
        return dates[-1] if dates else None
    keep = set(dates[:retain])
    placeholders = ",".join("?" for _ in keep)
    conn.execute(f"DELETE FROM daily_kline WHERE trade_date NOT IN ({placeholders})", tuple(keep))
    conn.commit()
    return min(keep)


def apply_kline_retention(conn: sqlite3.Connection, mode: str, retain: int) -> tuple[str | None, bool]:
    if mode != "init":
        return None, False
    return prune_to_latest_trade_days(conn, retain), True


def latest_date_summary(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT trade_date, COUNT(*) AS row_count, COUNT(DISTINCT code) AS code_count
        FROM daily_kline
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"trade_date": row[0], "row_count": int(row[1]), "code_count": int(row[2])}
        for row in rows
    ]


def distinct_trade_day_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM daily_kline").fetchone()
    return int(row[0] or 0)


def database_is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM daily_kline").fetchone()
    return int(row[0] or 0) == 0


def resolve_mode(conn: sqlite3.Connection, requested_mode: str) -> str:
    if requested_mode != "auto":
        return requested_mode
    return "init" if database_is_empty(conn) else "daily"


def stock_rows_from_symbols(symbols: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_code in symbols.split(","):
        code = normalize_code(raw_code)
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "name": code,
                "exchange": exchange_for_code(code),
                "secid": secid_for_code(code),
                "raw_json": "{}",
            }
        )
    return rows


def date_window(trade_date: str, mode: str, args: argparse.Namespace) -> tuple[str, str]:
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d").date()
    days = args.initial_lookback_days if mode == "init" else args.incremental_lookback_days
    begin = (end_dt - timedelta(days=days)).strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")
    return begin, end


def enforce_time_guard(args: argparse.Namespace) -> None:
    if args.allow_before_close:
        return
    current = now_china()
    if args.trade_date == current.date().isoformat() and current.hour < args.min_run_hour:
        raise SystemExit(
            f"Refusing same-day sync before {args.min_run_hour}:00 Asia/Shanghai. "
            "Run after the close or pass --allow-before-close for explicit testing."
        )


def sync(args: argparse.Namespace) -> dict[str, Any]:
    enforce_time_guard(args)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        ensure_schema(conn)
        actual_mode = resolve_mode(conn, args.mode)
        args.mode = actual_mode
        run_id = start_run(conn, args)
        begin, end = date_window(args.trade_date, actual_mode, args)

        print(f"database: {db_path}")
        print(f"mode: {actual_mode}; window: {begin}-{end}; adjust: {args.adjust}")
        if args.symbols_only:
            if not args.symbols:
                raise SystemExit("--symbols-only requires --symbols")
            stocks = stock_rows_from_symbols(args.symbols)
            universe_source = "symbols_only"
        else:
            try:
                stocks, universe_source = fetch_stock_universe(args.limit, args.request_timeout, args.prefer_akshare)
            except Exception as exc:
                if not args.symbols:
                    raise
                stocks = stock_rows_from_symbols(args.symbols)
                universe_source = f"symbols_fallback:{exc}"
        if args.symbols:
            wanted = {normalize_code(code) for code in args.symbols.split(",") if normalize_code(code)}
            stocks = [row for row in stocks if row["code"] in wanted]
        if not stocks:
            raise SystemExit("No A-share symbols found from the selected universe source.")
        upsert_stock_universe(conn, stocks)
        print(f"stock_count: {len(stocks)} ({universe_source})")

        popularity_count = 0
        popularity_source = "skipped"
        popularity_error = ""
        if not args.skip_popularity:
            try:
                popularity_rows, popularity_source = fetch_popularity_top100(
                    args.trade_date,
                    args.request_timeout,
                    args.popularity_limit,
                    args.prefer_akshare,
                )
                popularity_count = replace_popularity_top100(conn, args.trade_date, popularity_rows)
                print(f"popularity_count: {popularity_count} ({popularity_source})")
            except Exception as exc:
                popularity_error = str(exc)
                replace_popularity_top100(conn, args.trade_date, [])
                print(f"popularity unavailable: {popularity_error}")

        rows_upserted = 0
        failures: list[tuple[str, str, str]] = []
        pending: list[dict[str, Any]] = []
        completed = 0
        started = time.time()
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {
                executor.submit(
                    fetch_kline_rows,
                    stock,
                    begin,
                    end,
                    args.adjust,
                    args.request_timeout,
                ): stock
                for stock in stocks
            }
            for future in as_completed(futures):
                stock = futures[future]
                completed += 1
                try:
                    _code, rows = future.result()
                    if rows:
                        pending.extend(rows)
                    else:
                        failures.append((stock["code"], stock.get("name") or "", "empty kline response"))
                except Exception as exc:
                    failures.append((stock["code"], stock.get("name") or "", str(exc)))
                if len(pending) >= args.batch_rows:
                    rows_upserted += upsert_kline_rows(conn, pending)
                    pending = []
                if completed == len(stocks) or completed % args.progress_every == 0:
                    elapsed = time.time() - started
                    print(
                        f"progress: {completed}/{len(stocks)} symbols, "
                        f"rows_upserted={rows_upserted + len(pending)}, "
                        f"failures={len(failures)}, elapsed={elapsed:.1f}s"
                    )
        rows_upserted += upsert_kline_rows(conn, pending)
        add_failures(conn, run_id, failures)
        cutoff, retention_applied = apply_kline_retention(conn, actual_mode, args.retain_trading_days)
        latest_dates = latest_date_summary(conn)
        trade_days = distinct_trade_day_count(conn)
        notes = (
            f"retained_distinct_trade_days={trade_days}; "
            f"retention_applied={retention_applied}; "
            f"popularity_count={popularity_count}; "
            f"popularity_source={popularity_source}"
        )
        if popularity_error:
            notes += f"; popularity_error={popularity_error}"
        finish_run(
            conn,
            run_id,
            stock_count=len(stocks),
            rows_upserted=rows_upserted,
            failures=len(failures),
            cutoff_trade_date=cutoff,
            data_source=universe_source,
            latest_dates=latest_dates,
            notes=notes,
        )
        return {
            "database": str(db_path),
            "run_id": run_id,
            "mode": actual_mode,
            "stock_count": len(stocks),
            "rows_upserted": rows_upserted,
            "failures": len(failures),
            "popularity_count": popularity_count,
            "popularity_source": popularity_source,
            "popularity_error": popularity_error,
            "retained_trade_days": trade_days,
            "retention_applied": retention_applied,
            "cutoff_trade_date": cutoff,
            "latest_dates": latest_dates,
        }


def self_test() -> None:
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.sqlite"
        with closing(sqlite3.connect(db)) as conn:
            ensure_schema(conn)
            stocks = [
                {
                    "code": "000001",
                    "name": "sample",
                    "exchange": "SZ",
                    "secid": "0.000001",
                    "raw_json": "{}",
                }
            ]
            upsert_stock_universe(conn, stocks)
            start = date(2025, 1, 1)
            rows = []
            for idx in range(130):
                day = start + timedelta(days=idx)
                rows.append(
                    {
                        "code": "000001",
                        "trade_date": day.isoformat(),
                        "name": "sample",
                        "exchange": "SZ",
                        "open": 10 + idx,
                        "close": 10.5 + idx,
                        "high": 11 + idx,
                        "low": 9.5 + idx,
                        "volume": 1000 + idx,
                        "amount": 10000 + idx,
                        "amplitude": 1.0,
                        "pct_chg": 0.5,
                        "change_amount": 0.1,
                        "turnover": 2.0,
                        "source": "self-test",
                        "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                        "raw_line": "",
                    }
                )
            assert upsert_kline_rows(conn, rows) == 130
            cutoff, applied = apply_kline_retention(conn, "daily", 126)
            assert cutoff is None
            assert applied is False
            assert distinct_trade_day_count(conn) == 130
            cutoff = prune_to_latest_trade_days(conn, 126)
            assert distinct_trade_day_count(conn) == 126
            assert cutoff == (start + timedelta(days=4)).isoformat()
            assert latest_date_summary(conn, 1)[0]["trade_date"] == (start + timedelta(days=129)).isoformat()
            popularity_rows = [
                {
                    "trade_date": "2026-06-04",
                    "rank": 1,
                    "code": "000001",
                    "name": "sample",
                    "exchange": "SZ",
                    "hot_value": 100.0,
                    "rank_change": 0,
                    "latest_price": 10.5,
                    "pct_chg": 1.2,
                    "source": "self-test",
                    "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                    "raw_json": "{}",
                }
            ]
            assert replace_popularity_top100(conn, "2026-06-04", popularity_rows) == 1
            assert conn.execute("SELECT COUNT(*) FROM popularity_top100").fetchone()[0] == 1
            assert replace_popularity_top100(conn, "2026-06-05", []) == 0
            assert conn.execute("SELECT COUNT(*) FROM popularity_top100").fetchone()[0] == 1
            assert replace_popularity_top100(conn, "2026-06-04", []) == 0
            assert conn.execute("SELECT COUNT(*) FROM popularity_top100").fetchone()[0] == 0
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch full-market A-share daily K-line data into SQLite and retain latest trade days."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--trade-date", default=now_china().date().isoformat())
    parser.add_argument("--mode", choices=["auto", "init", "daily"], default="auto")
    parser.add_argument("--adjust", choices=sorted(ADJUST_FLAGS), default="none")
    parser.add_argument("--retain-trading-days", type=int, default=126)
    parser.add_argument("--initial-lookback-days", type=int, default=240)
    parser.add_argument("--incremental-lookback-days", type=int, default=12)
    parser.add_argument("--min-run-hour", type=int, default=17)
    parser.add_argument("--allow-before-close", action="store_true")
    parser.add_argument("--request-timeout", type=int, default=15)
    parser.add_argument("--prefer-akshare", action="store_true", help="try akshare.stock_zh_a_spot_em before built-in endpoints")
    parser.add_argument("--skip-popularity", action="store_true", help="skip current-day popularity top 100 sync")
    parser.add_argument("--popularity-limit", type=int, default=100, help="number of popularity rows to keep for the current trade date")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--progress-every", type=int, default=200)
    parser.add_argument("--limit", type=int, help="limit symbols for development runs")
    parser.add_argument("--symbols", help="comma-separated 6-digit stock codes")
    parser.add_argument("--symbols-only", action="store_true", help="use --symbols directly and skip full-market universe fetch")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return
    summary = sync(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
