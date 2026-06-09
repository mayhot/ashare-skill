import csv
import argparse
import json
import math
import random
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKET_CACHE_DB = ROOT / "runs" / "ashare-kline-sqlite-cache" / "ashare_kline.sqlite"
RUN_DIR = None
RUNS_ROOT = None
SOURCE_TOP200 = None
SCREENING_DATE = None
NO_NETWORK = False
MARKET_CACHE_DB = DEFAULT_MARKET_CACHE_DB
IGNORE_MARKET_CACHE = False
CANDIDATE_SOURCE_LABEL = None
HOT_SOURCE_LABEL = None
KLINE_SOURCE_LABEL = "东方财富日K接口"
KLINE_BACKEND = "eastmoney"
TURNOVER_TOP_N = 200
HOT_TOP_N = 100
REQUEST_RETRIES = 4
REQUEST_BACKOFF = 1.0
REQUEST_JITTER = 0.35
KLINE_REQUEST_DELAY = 0.35


KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php/"
    "CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=300"
)
TOP_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num=80&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=page"
)
EASTMONEY_TOP_URL = (
    "http://push2.eastmoney.com/api/qt/clist/get?"
    "pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f6&"
    "fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&"
    "fields=f12,f14,f2,f3,f6,f8,f20"
)
EASTMONEY_KLINE_URL = (
    "http://push2his.eastmoney.com/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
    "fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=20250101&end={end_date}"
)
TENCENT_KLINE_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
    "param={symbol},day,,,300,qfq"
)
HOT_RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
EASTMONEY_QUOTE_URL = "http://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_QUOTE_URL = "http://hq.sinajs.cn/list={symbols}"


THEMES = {
    "000725": "玻璃基板/显示面板",
    "300476": "PCB/AI服务器",
    "603986": "半导体/存储芯片",
    "300502": "CPO/光模块",
    "300308": "CPO/光模块",
    "688008": "半导体/存储接口",
    "300394": "CPO/光器件",
    "600584": "半导体/先进封装",
    "002384": "PCB/AI硬件",
    "688981": "半导体/晶圆代工",
    "300274": "储能/逆变器",
    "002281": "光通信/CPO",
    "688256": "AI芯片/国产算力",
    "000988": "光通信/激光设备",
    "688012": "半导体设备",
    "002475": "消费电子/连接器",
    "002371": "半导体设备",
    "601138": "AI服务器",
    "300136": "消费电子/射频",
    "002156": "半导体/先进封装",
    "002050": "机器人/热管理",
    "300750": "动力电池/储能",
    "688041": "AI芯片/国产算力",
    "002463": "PCB/AI服务器",
    "002407": "电池材料/氟化工",
    "600522": "光通信/海缆",
    "600487": "光通信/海缆",
    "688525": "存储模组",
    "300408": "电子陶瓷/元器件",
    "001309": "存储模组",
    "002837": "液冷/温控",
    "002185": "半导体/封测",
    "600183": "覆铜板/电子材料",
    "000063": "通信设备/AI网络",
    "603501": "半导体/CIS",
    "000977": "AI服务器",
    "688347": "半导体/晶圆代工",
    "688521": "半导体/IP",
    "688072": "半导体设备",
    "002916": "PCB/封装基板",
    "600111": "稀土/材料",
    "601689": "机器人/汽车零部件",
    "002049": "半导体/特种IC",
    "600460": "半导体/功率IDM",
    "002436": "PCB/封装基板",
    "688027": "量子科技/信息安全",
    "600498": "光通信/通信设备",
    "002851": "电源/电控",
    "688361": "半导体设备",
    "603993": "有色金属/钼铜",
    "688629": "高速连接器/AI硬件",
    "603083": "CPO/光模块",
    "000021": "存储/先进制造",
    "000100": "显示面板/AI硬件",
    "603920": "PCB/AI硬件",
    "600673": "电子材料/电池材料",
    "002273": "光学/消费电子",
    "688313": "光芯片/CPO",
    "002222": "光学晶体/激光",
    "600601": "PCB/AI硬件",
    "300620": "光器件/CPO",
    "300346": "半导体材料",
}


MAIN_THEME_KEYS = (
    "PCB",
    "CPO",
    "光通信",
    "光模块",
    "光器件",
    "光芯片",
    "半导体",
    "存储",
    "AI",
    "服务器",
    "高速连接器",
    "玻璃基板",
    "显示面板",
    "机器人",
    "液冷",
    "电池",
    "电源",
    "电控",
    "量子科技",
)
PRIMARY_THEME_KEYS = (
    "PCB",
    "CPO",
    "光通信",
    "光模块",
    "光器件",
    "光芯片",
    "半导体",
    "存储",
    "AI",
    "服务器",
    "高速连接器",
    "玻璃基板",
    "液冷",
)
FRONT_ROW_AMOUNT_YI = 50
FRONT_ROW_RANK = 80


def retry_delay(attempt: int) -> float:
    base = max(0.0, REQUEST_BACKOFF) * (2 ** attempt)
    jitter = random.uniform(0.0, max(0.0, REQUEST_JITTER))
    return base + jitter


def sleep_before_kline_request() -> None:
    delay = max(0.0, KLINE_REQUEST_DELAY)
    if delay:
        time.sleep(delay + random.uniform(0.0, max(0.0, REQUEST_JITTER)))


def progress(message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


def fetch_json(url: str):
    if NO_NETWORK:
        raise RuntimeError("network disabled by --no-network")
    attempts = max(1, int(REQUEST_RETRIES))
    last_exc = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "http://quote.eastmoney.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(retry_delay(attempt))
    raise last_exc


def fetch_json_post(url: str, payload: dict):
    if NO_NETWORK:
        raise RuntimeError("network disabled by --no-network")
    data = json.dumps(payload).encode("utf-8")
    attempts = max(1, int(REQUEST_RETRIES))
    last_exc = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": "https://guba.eastmoney.com/rank/",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(retry_delay(attempt))
    raise last_exc


def fnum(value, default=0.0):
    try:
        if value in ("", None, "-"):
            return default
        value = float(value)
        return default if math.isnan(value) else value
    except Exception:
        return default


def stock_symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def eastmoney_secid(symbol: str) -> str:
    code = symbol[-6:]
    market = "1" if symbol.startswith("sh") else "0"
    return f"{market}.{code}"


def eastmoney_rank_code(sc: str) -> str:
    text = str(sc or "").strip().upper()
    return text[-6:] if len(text) >= 6 else text


def eastmoney_rank_secid(sc: str) -> str:
    text = str(sc or "").strip().upper()
    code = eastmoney_rank_code(text)
    market = "1" if text.startswith("SH") or code.startswith(("6", "9")) else "0"
    return f"{market}.{code}"


def sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def read_cached_turnover_top200() -> list[dict]:
    if IGNORE_MARKET_CACHE or SOURCE_TOP200 is not None or not MARKET_CACHE_DB.exists():
        return []
    with sqlite3.connect(str(MARKET_CACHE_DB.resolve())) as conn:
        conn.row_factory = sqlite3.Row
        if not sqlite_table_exists(conn, "turnover_top200"):
            return []
        rows = conn.execute(
            """
            SELECT t.rank, t.code, t.name, t.amount, t.volume, t.turnover_ratio,
                   t.latest_price, t.pct_chg, t.fetched_at, u.total_mv
            FROM turnover_top200 t
            LEFT JOIN stock_universe u ON u.code = t.code
            WHERE t.trade_date = ?
            ORDER BY t.rank
            LIMIT ?
            """,
            (SCREENING_DATE, TURNOVER_TOP_N),
        ).fetchall()
    if len(rows) < TURNOVER_TOP_N:
        return []
    return [
        {
            "rank": int(row["rank"]),
            "symbol": stock_symbol(str(row["code"])),
            "code": str(row["code"]),
            "name": row["name"] or "",
            "trade": fnum(row["latest_price"]),
            "changepercent": fnum(row["pct_chg"]),
            "turnoverratio": fnum(row["turnover_ratio"]),
            "amount_yi": fnum(row["amount"]) / 100000000,
            "mktcap_yi": fnum(row["total_mv"]) / 100000000,
            "ticktime": row["fetched_at"] or SCREENING_DATE or "",
        }
        for row in rows
    ]


def read_cached_hot_top100() -> list[dict]:
    if IGNORE_MARKET_CACHE or not MARKET_CACHE_DB.exists():
        return []
    with sqlite3.connect(str(MARKET_CACHE_DB.resolve())) as conn:
        conn.row_factory = sqlite3.Row
        if not sqlite_table_exists(conn, "popularity_top100"):
            return []
        rows = conn.execute(
            """
            SELECT p.rank, p.code, p.name, p.latest_price, p.pct_chg,
                   p.fetched_at, u.amount, u.turnover, u.total_mv
            FROM popularity_top100 p
            LEFT JOIN stock_universe u ON u.code = p.code
            WHERE p.trade_date = ?
            ORDER BY p.rank
            LIMIT ?
            """,
            (SCREENING_DATE, HOT_TOP_N),
        ).fetchall()
    if len(rows) < HOT_TOP_N:
        return []
    return [
        {
            "rank": int(row["rank"]),
            "source_rank": int(row["rank"]),
            "hot_rank": int(row["rank"]),
            "turnover_rank": "",
            "rank_label": "人气排名",
            "source_type": "hot_top100",
            "source_title": "人气榜（热榜）前100",
            "symbol": stock_symbol(str(row["code"])),
            "code": str(row["code"]),
            "name": row["name"] or "",
            "trade": fnum(row["latest_price"]),
            "changepercent": fnum(row["pct_chg"]),
            "turnoverratio": fnum(row["turnover"]),
            "amount_yi": fnum(row["amount"]) / 100000000,
            "mktcap_yi": fnum(row["total_mv"]) / 100000000,
            "ticktime": row["fetched_at"] or SCREENING_DATE or "",
        }
        for row in rows
    ]


def read_cached_kline(symbol: str) -> tuple[list[dict], dict] | None:
    if IGNORE_MARKET_CACHE or not MARKET_CACHE_DB.exists():
        return None
    code = symbol[-6:]
    with sqlite3.connect(str(MARKET_CACHE_DB.resolve())) as conn:
        conn.row_factory = sqlite3.Row
        if not sqlite_table_exists(conn, "daily_kline"):
            return None
        rows = conn.execute(
            """
            SELECT trade_date, open, close, high, low, volume, source
            FROM daily_kline
            WHERE code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 300
            """,
            (code, SCREENING_DATE),
        ).fetchall()
    if len(rows) < 60:
        return None
    krows = [
        {
            "date": row["trade_date"],
            "open": fnum(row["open"]),
            "close": fnum(row["close"]),
            "high": fnum(row["high"]),
            "low": fnum(row["low"]),
            "volume": fnum(row["volume"]),
        }
        for row in reversed(rows)
    ]
    return krows, {"source": "ashare-kline-sqlite-cache SQLite daily_kline"}


def fetch_sina_top200():
    rows = []
    seen = set()
    for page in range(1, 5):
        payload = fetch_json(TOP_URL.format(page=page))
        for item in payload:
            symbol = item.get("symbol", "")
            code = item.get("code", "")
            if not symbol or code in seen:
                continue
            if not (symbol.startswith("sh") or symbol.startswith("sz")):
                continue
            seen.add(code)
            rows.append(
                {
                    "rank": len(rows) + 1,
                    "symbol": symbol,
                    "code": code,
                    "name": item.get("name", ""),
                    "trade": fnum(item.get("trade")),
                    "changepercent": fnum(item.get("changepercent")),
                    "turnoverratio": fnum(item.get("turnoverratio")),
                    "amount_yi": fnum(item.get("amount")) / 100000000,
                    "mktcap_yi": fnum(item.get("mktcap")) / 10000,
                    "ticktime": item.get("ticktime", ""),
                }
            )
            if len(rows) >= 200:
                break
        if len(rows) >= 200:
            break
    if not rows or rows[0]["amount_yi"] <= 0 or rows[0]["trade"] <= 0:
        raise RuntimeError("Sina ranking appears invalid: zero turnover or price")
    return rows[:200]


def fetch_eastmoney_top200():
    rows = []
    seen = set()
    for page in range(1, 3):
        payload = fetch_json(EASTMONEY_TOP_URL.format(page=page))
        for item in payload.get("data", {}).get("diff", []):
            code = str(item.get("f12", ""))
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                {
                    "rank": len(rows) + 1,
                    "symbol": stock_symbol(code),
                    "code": code,
                    "name": item.get("f14", ""),
                    "trade": fnum(item.get("f2")),
                    "changepercent": fnum(item.get("f3")),
                    "turnoverratio": fnum(item.get("f8")),
                    "amount_yi": fnum(item.get("f6")) / 100000000,
                    "mktcap_yi": fnum(item.get("f20")) / 100000000,
                    "ticktime": SCREENING_DATE or "",
                }
            )
            if len(rows) >= 200:
                break
        if len(rows) >= 200:
            break
    if not rows or rows[0]["amount_yi"] <= 0 or rows[0]["trade"] <= 0:
        raise RuntimeError("Eastmoney ranking appears invalid: zero turnover or price")
    return rows[:200]


def fetch_eastmoney_quotes_by_secids(secids: list[str]) -> dict[str, dict]:
    if not secids:
        return {}
    params = {
        "ut": "f057cbcbce2a86e2866ab8877db1d059",
        "fltt": "2",
        "invt": "2",
        "fields": "f14,f3,f12,f2,f6,f8,f20",
        "secids": ",".join(secids),
    }
    url = EASTMONEY_QUOTE_URL + "?" + urllib.parse.urlencode(params)
    payload = fetch_json(url)
    quotes = {}
    for item in payload.get("data", {}).get("diff", []):
        code = str(item.get("f12", ""))
        if code:
            quotes[code] = item
    return quotes


def fetch_sina_quotes_by_symbols(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    req = urllib.request.Request(
        SINA_QUOTE_URL.format(symbols=",".join(symbols)),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("gbk", "replace")
    quotes = {}
    for line in [line for line in text.splitlines() if line.strip()]:
        if "hq_str_" not in line:
            continue
        symbol = line.split("hq_str_", 1)[1].split("=", 1)[0]
        code = symbol[-6:]
        data = line.split('="', 1)[1].rsplit('"', 1)[0]
        fields = data.split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        price = fnum(fields[3])
        preclose = fnum(fields[2])
        quotes[code] = {
            "f14": fields[0],
            "f2": price,
            "f3": pct(price, preclose) or 0.0,
            "f6": fnum(fields[9]),
            "f8": 0.0,
            "f20": 0.0,
        }
    return quotes


def fetch_eastmoney_hot100():
    payload = fetch_json_post(
        HOT_RANK_URL,
        {
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "",
            "pageNo": 1,
            "pageSize": HOT_TOP_N,
        },
    )
    items = payload.get("data") or []
    if not items:
        raise RuntimeError("Eastmoney hot rank returned no rows")

    secids = [eastmoney_rank_secid(item.get("sc", "")) for item in items if isinstance(item, dict)]
    try:
        quotes = fetch_eastmoney_quotes_by_secids(secids)
    except Exception:
        symbols = [stock_symbol(eastmoney_rank_code(item.get("sc", ""))) for item in items if isinstance(item, dict)]
        quotes = fetch_sina_quotes_by_symbols(symbols)
    rows = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        sc = str(item.get("sc", ""))
        code = eastmoney_rank_code(sc)
        if not code or code in seen:
            continue
        seen.add(code)
        rank = int(fnum(item.get("rk"), len(rows) + 1))
        quote = quotes.get(code, {})
        rows.append(
            {
                "rank": rank,
                "source_rank": rank,
                "hot_rank": rank,
                "turnover_rank": "",
                "rank_label": "人气排名",
                "source_type": "hot_top100",
                "source_title": "人气榜（热榜）前100",
                "symbol": stock_symbol(code),
                "code": code,
                "name": quote.get("f14") or item.get("name", ""),
                "trade": fnum(quote.get("f2")),
                "changepercent": fnum(quote.get("f3")),
                "turnoverratio": fnum(quote.get("f8")),
                "amount_yi": fnum(quote.get("f6")) / 100000000,
                "mktcap_yi": fnum(quote.get("f20")) / 100000000,
                "ticktime": SCREENING_DATE or "",
            }
        )
        if len(rows) >= HOT_TOP_N:
            break
    if not rows:
        raise RuntimeError("Eastmoney hot rank produced no usable A-share rows")
    return rows


def read_top200():
    global CANDIDATE_SOURCE_LABEL, KLINE_BACKEND, KLINE_SOURCE_LABEL
    cached_rows = read_cached_turnover_top200()
    if cached_rows:
        CANDIDATE_SOURCE_LABEL = "ashare-kline-sqlite-cache SQLite turnover_top200"
        KLINE_SOURCE_LABEL = "ashare-kline-sqlite-cache SQLite daily_kline (local first; network fallback)"
        return cached_rows
    if SOURCE_TOP200 is None:
        try:
            rows = fetch_sina_top200()
            CANDIDATE_SOURCE_LABEL = "新浪实时成交额排名"
            return rows
        except Exception as exc:
            rows = fetch_eastmoney_top200()
            CANDIDATE_SOURCE_LABEL = f"东方财富实时成交额排名（新浪失败：{exc.__class__.__name__}）"
            KLINE_BACKEND = "eastmoney"
            KLINE_SOURCE_LABEL = "东方财富日K接口"
            return rows
    CANDIDATE_SOURCE_LABEL = str(SOURCE_TOP200)
    with SOURCE_TOP200.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    normalized = []
    for row in rows:
        normalized.append(
            {
                "rank": int(fnum(row.get("rank"))),
                "symbol": row.get("symbol", ""),
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "trade": fnum(row.get("trade")),
                "changepercent": fnum(row.get("changepercent")),
                "turnoverratio": fnum(row.get("turnoverratio")),
                "amount_yi": fnum(row.get("amount_yi")),
                "mktcap_yi": fnum(row.get("mktcap_yi")),
                "ticktime": row.get("ticktime", ""),
            }
        )
    return normalized


def mark_source(rows: list[dict], source_type: str, source_title: str, rank_label: str):
    marked = []
    for row in rows:
        copy = dict(row)
        copy.update(
            {
                "source_type": source_type,
                "source_title": source_title,
                "rank_label": rank_label,
                "source_rank": copy.get("rank", ""),
            }
        )
        if source_type == "turnover_top200":
            copy["turnover_rank"] = copy.get("rank", "")
            copy["hot_rank"] = ""
        marked.append(copy)
    return marked


def read_turnover_top200():
    rows = read_top200()[:TURNOVER_TOP_N]
    return mark_source(rows, "turnover_top200", "成交额前200", "成交额排名")


def read_hot_top100():
    global HOT_SOURCE_LABEL
    cached_rows = read_cached_hot_top100()
    if cached_rows:
        HOT_SOURCE_LABEL = "ashare-kline-sqlite-cache SQLite popularity_top100"
        return cached_rows
    HOT_SOURCE_LABEL = "东方财富个股人气榜 getAllCurrentList"
    return fetch_eastmoney_hot100()


def read_candidate_pools():
    pools = []
    try:
        rows = read_turnover_top200()
        pools.append(
            {
                "key": "turnover_top200",
                "title": "成交额前200",
                "source_label": candidate_source_label(),
                "rows": rows,
                "error": "",
            }
        )
    except Exception as exc:
        pools.append(
            {
                "key": "turnover_top200",
                "title": "成交额前200",
                "source_label": "成交额排名",
                "rows": [],
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        )

    try:
        rows = read_hot_top100()
        pools.append(
            {
                "key": "hot_top100",
                "title": "人气榜（热榜）前100",
                "source_label": HOT_SOURCE_LABEL or "东方财富个股人气榜 getAllCurrentList",
                "rows": rows,
                "error": "",
            }
        )
    except Exception as exc:
        pools.append(
            {
                "key": "hot_top100",
                "title": "人气榜（热榜）前100",
                "source_label": "东方财富个股人气榜 getAllCurrentList",
                "rows": [],
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        )

    if not any(pool["rows"] for pool in pools):
        errors = "；".join(f"{pool['title']} {pool['error']}" for pool in pools)
        raise RuntimeError(f"no candidate source available: {errors}")
    return pools


def fetch_kline(symbol: str):
    global KLINE_BACKEND, KLINE_SOURCE_LABEL
    cached = read_cached_kline(symbol)
    if cached:
        KLINE_SOURCE_LABEL = "ashare-kline-sqlite-cache SQLite daily_kline (local first; network fallback)"
        return cached
    if NO_NETWORK:
        raise RuntimeError("network disabled and local SQLite K-line unavailable")
    if KLINE_BACKEND == "eastmoney":
        try:
            return fetch_eastmoney_kline(symbol)
        except Exception as exc:
            KLINE_SOURCE_LABEL = f"腾讯前复权日K接口（东方财富失败：{exc.__class__.__name__}）"
            return fetch_tencent_kline(symbol)
    try:
        return fetch_sina_kline(symbol)
    except Exception as exc:
        KLINE_BACKEND = "eastmoney"
        KLINE_SOURCE_LABEL = f"东方财富日K接口（新浪失败：{exc.__class__.__name__}）"
        try:
            return fetch_eastmoney_kline(symbol)
        except Exception as eastmoney_exc:
            KLINE_SOURCE_LABEL = f"腾讯前复权日K接口（新浪失败：{exc.__class__.__name__}，东方财富失败：{eastmoney_exc.__class__.__name__}）"
            return fetch_tencent_kline(symbol)


def fetch_sina_kline(symbol: str):
    sleep_before_kline_request()
    payload = fetch_json(KLINE_URL.format(symbol=urllib.parse.quote(symbol)))
    rows = []
    for item in payload:
        row = {
            "date": item.get("day") or item.get("date"),
            "open": fnum(item.get("open")),
            "high": fnum(item.get("high")),
            "low": fnum(item.get("low")),
            "close": fnum(item.get("close")),
            "volume": fnum(item.get("volume")),
        }
        if row["date"] and row["close"] > 0:
            rows.append(row)
    if len(rows) < 60:
        raise RuntimeError(f"日K不足: {len(rows)}")
    return rows, payload


def fetch_eastmoney_kline(symbol: str):
    sleep_before_kline_request()
    url = EASTMONEY_KLINE_URL.format(secid=eastmoney_secid(symbol), end_date=SCREENING_DATE.replace("-", ""))
    payload = fetch_json(url)
    klines = payload.get("data", {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        row = {
            "date": parts[0],
            "open": fnum(parts[1]),
            "close": fnum(parts[2]),
            "high": fnum(parts[3]),
            "low": fnum(parts[4]),
            "volume": fnum(parts[5]),
        }
        if row["date"] and row["close"] > 0:
            rows.append(row)
    if len(rows) < 60:
        raise RuntimeError(f"日K不足: {len(rows)}")
    return rows, payload


def fetch_tencent_kline(symbol: str):
    sleep_before_kline_request()
    payload = fetch_json(TENCENT_KLINE_URL.format(symbol=urllib.parse.quote(symbol)))
    stock_data = payload.get("data", {}).get(symbol, {})
    klines = stock_data.get("qfqday") or stock_data.get("day") or []
    rows = []
    for item in klines:
        if len(item) < 6:
            continue
        row = {
            "date": item[0],
            "open": fnum(item[1]),
            "close": fnum(item[2]),
            "high": fnum(item[3]),
            "low": fnum(item[4]),
            "volume": fnum(item[5]),
        }
        if row["date"] and row["close"] > 0:
            rows.append(row)
    if len(rows) < 60:
        raise RuntimeError(f"日K不足: {len(rows)}")
    return rows, payload


def mean(values):
    return sum(values) / len(values) if values else math.nan


def pct(new_value, old_value):
    if not old_value:
        return None
    return (new_value / old_value - 1) * 100


def position_plan(tier, score, ind, row):
    dist20 = ind["dist20_pct"]
    change = row["changepercent"]
    turnover = row["turnoverratio"]
    vol_ratio = ind["vol_ratio"]
    if tier == "A":
        if score >= 93 and dist20 <= 8 and change <= 2 and turnover <= 10 and vol_ratio <= 1.6:
            return "6%-8%观察上限"
        if score >= 88 and dist20 <= 10 and change <= 4 and turnover <= 15 and vol_ratio <= 2.2:
            return "4%-6%观察上限"
        return "3%-5%观察上限"
    if tier == "B":
        return "2%-4%确认后上限"
    if tier == "C":
        return "0%-1%跟踪仓"
    if tier == "过热跟踪":
        return "0%，整理后重评"
    return "0%，剔除/不配置"


def ema(values, span):
    alpha = 2 / (span + 1)
    out = []
    prev = values[0]
    for value in values:
        prev = alpha * value + (1 - alpha) * prev
        out.append(prev)
    return out


def indicators(krows):
    closes = [r["close"] for r in krows]
    highs = [r["high"] for r in krows]
    lows = [r["low"] for r in krows]
    vols = [r["volume"] for r in krows]
    n = len(krows)

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    difs = [a - b for a, b in zip(ema12, ema26)]
    deas = ema(difs, 9)
    bars = [2 * (d - e) for d, e in zip(difs, deas)]

    ks, ds, js = [], [], []
    k = d = 50.0
    for i, close in enumerate(closes):
        lo = min(lows[max(0, i - 8): i + 1])
        hi = max(highs[max(0, i - 8): i + 1])
        rsv = 50.0 if hi == lo else (close - lo) / (hi - lo) * 100
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
        ks.append(k)
        ds.append(d)
        js.append(3 * k - 2 * d)

    dif, dea, bar = difs[-1], deas[-1], bars[-1]
    prev_dif, prev_dea, prev_bar = difs[-2], deas[-2], bars[-2]
    kval, dval, jval = ks[-1], ds[-1], js[-1]
    prev_k, prev_d = ks[-2], ds[-2]

    if dif > dea and prev_dif <= prev_dea:
        macd = "MACD零轴上金叉" if dif > 0 else "MACD零轴下金叉"
    elif dif < dea and prev_dif >= prev_dea:
        macd = "MACD死叉"
    elif dif > dea and bar >= prev_bar:
        macd = "MACD多头延续"
    elif dif > dea:
        macd = "MACD多头但动能收敛"
    elif dif < dea and bar < prev_bar:
        macd = "MACD空头/动能走弱"
    else:
        macd = "MACD中性"

    if kval > dval and prev_k <= prev_d:
        kdj = "KDJ金叉偏热" if jval > 100 else "KDJ金叉"
    elif kval < dval and prev_k >= prev_d:
        kdj = "KDJ高位死叉" if kval > 70 else "KDJ死叉"
    elif jval > 100:
        kdj = "KDJ高位偏热"
    elif kval > dval:
        kdj = "KDJ多头"
    else:
        kdj = "KDJ中性"

    ma = {p: mean(closes[-p:]) for p in (5, 10, 20, 30, 60)}
    vol20 = mean(vols[-20:])
    high20_prior = max(highs[-21:-1])
    low20 = min(lows[-20:])
    ret5 = closes[-1] / closes[-6] - 1 if n > 6 else 0
    ret10 = closes[-1] / closes[-11] - 1 if n > 11 else 0
    dist20 = closes[-1] / ma[20] - 1 if ma[20] else 0

    return {
        "date": krows[-1]["date"],
        "close": closes[-1],
        "ma5": ma[5],
        "ma10": ma[10],
        "ma20": ma[20],
        "ma30": ma[30],
        "ma60": ma[60],
        "vol_ratio": vols[-1] / vol20 if vol20 else 0,
        "ret5_pct": ret5 * 100,
        "ret10_pct": ret10 * 100,
        "dist20_pct": dist20 * 100,
        "high20_prior": high20_prior,
        "low20": low20,
        "macd": macd,
        "dif": dif,
        "dea": dea,
        "hist": bar,
        "kdj": kdj,
        "k": kval,
        "d": dval,
        "j": jval,
    }


def infer_theme(row):
    theme = THEMES.get(row["code"])
    if theme:
        return theme
    name = row["name"]
    if any(word in name for word in ("量子", "国盾")):
        return "量子科技/信息安全"
    if any(word in name for word in ("电路", "PCB", "覆铜板", "生益", "沪电", "深南")):
        return "PCB/AI硬件"
    if any(word in name for word in ("光模块", "光迅", "剑桥", "光库", "仕佳", "中际", "新易盛")):
        return "CPO/光模块"
    if any(word in name for word in ("连接", "华丰", "瑞可达")):
        return "高速连接器/AI硬件"
    if any(word in name for word in ("芯", "微", "晶", "导体", "封")):
        return "半导体"
    if any(word in name for word in ("设备", "中科飞测", "拓荆", "北方华创", "中微")):
        return "半导体设备"
    if any(word in name for word in ("光", "通信", "电路", "科技")):
        return "AI硬件/通信"
    if any(word in name for word in ("液冷", "温控", "英维克")):
        return "液冷/温控"
    if any(word in name for word in ("机器人", "三花", "拓普")):
        return "机器人/汽车零部件"
    if any(word in name for word in ("电池", "锂", "氟")):
        return "电池/材料"
    if any(word in name for word in ("电源", "电控", "麦格米特")):
        return "电源/电控"
    if any(word in name for word in ("钼", "铜", "铝", "稀土", "洛阳")):
        return "有色金属/资源"
    return "综合主题"


def ma20_stabilization_state(ind):
    dist20 = ind["dist20_pct"]
    if -1 <= dist20 <= 5 and ind["vol_ratio"] <= 1.4 and "空头" not in ind["macd"]:
        return "20日线强企稳"
    if -2 <= dist20 <= 10 and ind["vol_ratio"] <= 2.2:
        return "20日线可观察"
    if dist20 > 18:
        return "远离20日线不追"
    return "20日线状态一般"


def score_candidate(row, ind):
    close = ind["close"]
    ma5, ma10, ma20, ma60 = ind["ma5"], ind["ma10"], ind["ma20"], ind["ma60"]
    theme = infer_theme(row)
    main_theme = any(key in theme for key in MAIN_THEME_KEYS)
    primary_theme = any(key in theme for key in PRIMARY_THEME_KEYS)
    source_type = row.get("source_type", "turnover_top200")
    source_rank = int(fnum(row.get("source_rank", row.get("rank", 999)), 999))
    turnover_front = source_type == "turnover_top200" and source_rank <= TURNOVER_TOP_N
    hot_front = source_type == "hot_top100" and source_rank <= HOT_TOP_N
    turnover_active = row["amount_yi"] >= FRONT_ROW_AMOUNT_YI
    front_row = main_theme and (turnover_front or hot_front or (source_rank <= FRONT_ROW_RANK and turnover_active))
    trend_stock = ma20 > ma60 and ma10 >= ma20 * 0.98
    ma20_state = ma20_stabilization_state(ind)
    ma20_stabilizing = trend_stock and ma20_state in ("20日线强企稳", "20日线可观察") and ind["ret5_pct"] > -8

    trend = 0
    trend += 3 if close > ma5 else 0
    trend += 3 if close > ma10 else 0
    trend += 4 if close > ma20 else 0
    trend += 4 if ma5 > ma10 > ma20 else 0
    trend += 3 if ma20 > ma60 else 0

    breakout = close >= ind["high20_prior"] * 0.995
    near_support = abs(ind["dist20_pct"]) <= 8 or abs(close / ma10 - 1) <= 0.06
    setup = 0
    setup += 5 if breakout else 0
    setup += 4 if near_support else 0
    setup += 2 if ma20_stabilizing else 0
    setup += 2 if ind["ret5_pct"] > -3 else 0
    setup += 2 if ind["dist20_pct"] <= 18 else 0
    setup = min(13, setup)

    vr = ind["vol_ratio"]
    vol = 0
    vol += 4 if 0.75 <= vr <= 2.2 else 1 if vr < 3.5 else 0
    vol += 3 if row["changepercent"] >= 0 and vr >= 0.85 else 1
    vol += 3 if not (row["changepercent"] < -4 and vr > 1.5) else 0
    vol += 3 if row["turnoverratio"] <= 20 else 1

    theme_score = 15 if front_row and primary_theme else 14 if hot_front and main_theme else 13 if primary_theme else 11 if main_theme else 8
    support = 0
    support += 5 if close > ma20 else 1
    support += 4 if ind["dist20_pct"] <= 15 else 1
    support += 3 if close > ind["low20"] else 0
    support += 3 if row["amount_yi"] >= 30 else 1

    fundamental = 10
    if any(key in theme for key in ("半导体", "CPO", "PCB", "AI", "机器人", "储能", "玻璃基板", "液冷")):
        fundamental += 4
    if front_row:
        fundamental += 1
    if row["mktcap_yi"] >= 500:
        fundamental += 1
    fundamental = min(15, fundamental)

    tech = 0
    tech += 3 if "多头延续" in ind["macd"] or "金叉" in ind["macd"] else 1 if "多头" in ind["macd"] else 0
    tech += 2 if "多头" in ind["kdj"] or "金叉" in ind["kdj"] else 0
    tech += 2 if ind["j"] <= 100 else 0
    if "死叉" in ind["macd"]:
        tech = max(0, tech - 3)
    if "高位死叉" in ind["kdj"] or ind["j"] > 110:
        tech = max(0, tech - 2)

    liquidity = 5 if row["amount_yi"] >= 80 else 4 if row["amount_yi"] >= 30 else 3
    total = trend + setup + vol + theme_score + support + fundamental + tech + liquidity

    flags = []
    severe_flags = []
    overheat_flags = []
    if close < ma20 and not ma5 > ma10:
        flags.append("收盘低于20日线且短均线未修复")
    if ind["dist20_pct"] > 25:
        flags.append("距20日线过远")
        severe_flags.append("距20日线过远")
    if ind["dist20_pct"] > 18:
        overheat_flags.append("距20日线超过18%")
    if row["changepercent"] > 6:
        overheat_flags.append("单日涨幅超过6%")
    if row["turnoverratio"] > 18:
        overheat_flags.append("换手偏高")
    if ind["j"] > 100:
        overheat_flags.append("KDJ高位偏热")
    if vr > 2.8:
        overheat_flags.append("量比过高")
    if row["changepercent"] > 9 and ind["dist20_pct"] > 10:
        flags.append("单日大涨后未整理")
        severe_flags.append("单日大涨后未整理")
    if row["changepercent"] < -5 and vr > 1.3:
        flags.append("放量下跌")
        severe_flags.append("放量下跌")
    if "高位死叉" in ind["kdj"]:
        flags.append("KDJ高位死叉")
        severe_flags.append("KDJ高位死叉")
    if "死叉" in ind["macd"] and close < ma20:
        flags.append("MACD死叉叠加破位")
        severe_flags.append("MACD死叉叠加破位")
    if not front_row and not main_theme and source_type == "turnover_top200" and source_rank > 120:
        flags.append("细分前排/人气不足")
    if not front_row and not main_theme and source_type == "hot_top100":
        flags.append("热榜有关注但主线辨识度不足")
    if not primary_theme and total >= 85:
        flags.append("非当前验证主线，A档需回避")
    a_ready = (
        total >= 85
        and not flags
        and not overheat_flags
        and primary_theme
        and row["changepercent"] <= 4
        and ind["dist20_pct"] <= 12
        and row["turnoverratio"] <= 15
        and vr <= 2.2
    )
    if severe_flags:
        tier = "剔除"
        state = "X-硬性剔除"
    elif a_ready:
        tier = "A"
        state = "A-确认观察"
    elif total >= 78 and main_theme:
        tier = "B"
        state = "B-等待买点"
    elif overheat_flags and total >= 75:
        tier = "过热跟踪"
        state = "X-过热强势"
    elif total >= 68:
        tier = "C"
        state = "C-只跟踪"
    else:
        tier = "剔除"
        state = "X-结构未达标"

    downgrade_reasons = []
    if overheat_flags and tier in ("A", "B"):
        downgrade_reasons.extend(overheat_flags)
        tier = "过热跟踪"
        state = "X-过热强势"
    support_text = f"10日线{ma10:.2f}/20日线{ma20:.2f}；收盘跌破20日线且1-2日不能收回则降级"
    buy_watch = "观察回踩10/20日线不破后的温和放量转强"
    if ma20_state == "20日线强企稳":
        buy_watch = "趋势票调整至20日线强企稳，观察缩量不破后的温和放量"
    elif ma20_state == "20日线可观察":
        buy_watch = "趋势票接近20日线可观察，等待缩量止跌或快速收回20日线"
    if breakout:
        buy_watch = "观察突破后不快速跌回，或回踩突破位缩量企稳"
    if ind["dist20_pct"] > 18 or row["changepercent"] > 6:
        buy_watch = "不追高，等待3-8日缩量整理并靠近10/20日线"

    if severe_flags:
        tier_reason = "硬性剔除：" + "；".join(severe_flags)
    elif downgrade_reasons:
        tier_reason = "规则降级：" + "；".join(downgrade_reasons)
    elif overheat_flags:
        tier_reason = "过热跟踪：" + "；".join(overheat_flags)
    elif flags:
        tier_reason = "降级观察：" + "；".join(flags)
    elif total < 65:
        tier_reason = "评分未达阈值"
    else:
        tier_reason = "无硬性风险"

    result = {
        **row,
        "theme": theme,
        "date": ind["date"],
        "close": round(close, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma30": round(ind["ma30"], 2),
        "ma60": round(ma60, 2),
        "dist20_pct": round(ind["dist20_pct"], 2),
        "ret5_pct": round(ind["ret5_pct"], 2),
        "ret10_pct": round(ind["ret10_pct"], 2),
        "vol_ratio": round(vr, 2),
        "macd": ind["macd"],
        "dif": round(ind["dif"], 4),
        "dea": round(ind["dea"], 4),
        "hist": round(ind["hist"], 4),
        "kdj": ind["kdj"],
        "k": round(ind["k"], 2),
        "d": round(ind["d"], 2),
        "j": round(ind["j"], 2),
        "score": int(round(total)),
        "tier": tier,
        "state": state,
        "tier_reason": tier_reason,
        "support": support_text,
        "buy_watch": buy_watch,
        "position_plan": position_plan(tier, int(round(total)), ind, row),
        "flags": "；".join(flags),
        "severe_flags": "；".join(severe_flags),
        "ma20_state": ma20_state,
        "source_type": source_type,
        "source_title": row.get("source_title", "成交额前200"),
        "source_rank": source_rank,
        "rank_label": row.get("rank_label", "成交额排名"),
        "turnover_rank": row.get("turnover_rank", ""),
        "hot_rank": row.get("hot_rank", ""),
        "front_row_state": "细分前排/高人气" if front_row else "主线活跃" if main_theme else "辨识度待验证",
        "structure": "平台突破/前高附近" if breakout else ma20_state if ma20_stabilizing else "均线回踩附近" if near_support else "偏离均线较远" if ind["dist20_pct"] > 18 else "震荡修复",
        "trend_state": "多头排列" if ma5 > ma10 > ma20 and close > ma20 else "修复中" if close > ma20 else "弱势",
    }
    return result


def enrich_relative_context(rows):
    valid = [row for row in rows if not row.get("error")]
    theme_groups = {}
    for row in valid:
        theme_groups.setdefault(row["theme"], []).append(row)
    for theme_rows in theme_groups.values():
        ordered = sorted(theme_rows, key=lambda row: row["amount_yi"], reverse=True)
        count = len(ordered)
        for index, row in enumerate(ordered, 1):
            row["theme_rank"] = index
            row["theme_count"] = count
            main_theme = any(key in row["theme"] for key in MAIN_THEME_KEYS)
            theme_front = index <= 3 and row["amount_yi"] >= 30
            if row["front_row_state"] == "细分前排/高人气" or (main_theme and theme_front):
                row["front_row_state"] = f"细分前排/高人气，板块成交第{index}/{count}"
            elif main_theme:
                row["front_row_state"] = f"主线活跃，板块成交第{index}/{count}"
            else:
                row["front_row_state"] = f"辨识度待验证，板块成交第{index}/{count}"


def candidate_source_label():
    if CANDIDATE_SOURCE_LABEL:
        return CANDIDATE_SOURCE_LABEL
    if SOURCE_TOP200 is None:
        return "新浪实时成交额排名"
    try:
        return str(SOURCE_TOP200.relative_to(ROOT))
    except ValueError:
        return str(SOURCE_TOP200)


def kline_source_label():
    return KLINE_SOURCE_LABEL


def generate_report(rows, summary):
    valid = [r for r in rows if not r.get("error")]
    a_rows = [r for r in valid if r["tier"] == "A"]
    b_rows = [r for r in valid if r["tier"] == "B"]
    c_rows = [r for r in valid if r["tier"] == "C"]
    hot_rows = [r for r in valid if r["tier"] == "过热跟踪"]
    x_rows = [r for r in valid if r["tier"] == "剔除"]

    display_a = sorted(a_rows, key=lambda r: r["score"], reverse=True)[:5]
    display_b = sorted(b_rows, key=lambda r: r["score"], reverse=True)[:5]
    display_c = sorted(c_rows, key=lambda r: r["score"], reverse=True)[:5]
    display_hot = sorted(hot_rows, key=lambda r: r["score"], reverse=True)[:5]
    display_x = sorted(x_rows, key=lambda r: r["score"], reverse=True)[:5]
    display_rows = display_a + display_b + display_c + display_hot + display_x

    def names(items):
        return "、".join(r["name"] for r in items) if items else "无"

    top_themes = Counter(r["theme"] for r in valid).most_common(5)
    theme_text = "、".join(f"{theme}({count})" for theme, count in top_themes) if top_themes else "无"
    latest_dates = summary.get("latest_kline_dates") or {}
    latest_date_text = "、".join(f"{day}:{count}只" for day, count in latest_dates.items()) if latest_dates else "无"
    source_label = candidate_source_label()
    kline_label = kline_source_label()
    missing_count = summary["candidate_count"] - summary["calculated_count"]
    hard_removed = [r for r in x_rows if r.get("severe_flags")]

    lines = []
    lines.append("# A股右侧趋势买入标准筛选结果")
    lines.append("")
    lines.append(f"筛选日期：{SCREENING_DATE}")
    lines.append("执行技能：ashare-trend-buy")
    lines.append("结果类型：研究观察池，不是最终买入名单")
    lines.append("")
    lines.append("## 数据说明")
    lines.append("")
    lines.append(f"- 数据来源：候选池 `{source_label}`；日K来自{kline_label}；结果保存到 `runs/ashare-trend-buy/{SCREENING_DATE}/`。")
    lines.append(f"- 数据完整性：候选 {summary['candidate_count']} 只，完成指标计算 {summary['calculated_count']} 只，未完成 {missing_count} 只；最新K线日期分布：{latest_date_text}。")
    lines.append("- 指标口径：5/10/20/30/60日均线、量比、20日线偏离、20日线企稳分层、MACD(12/26/9)、KDJ(9日RSV)、支撑/失效位、板块内成交前排/人气和右侧趋势评分。")
    lines.append("- 分档纪律：A档必须同时满足主线纯度、不过热、靠近支撑、量能可控；B档作为主要等待池；C档只跟踪，不进入正式短名单。")
    lines.append(f"- 市场环境：候选主线集中在 {theme_text}；右侧策略优先保留趋势结构完整、调整到20日线附近企稳、靠近支撑或突破后可确认的细分前排标的。")
    lines.append("- 剔除解释：剔除档按原始评分展示，高分剔除通常是触发距20日线过远、单日大涨未整理、放量下跌、MACD/KDJ破位等硬性风险。")
    lines.append("- 限制说明：本脚本侧重技术结构与主线归类，基本面/公告证据只作主题逻辑提示；最终报告每个档位最多展示5只，过程数据不归档到 runs。")
    lines.append("")
    lines.append("## 一、筛选结论")
    lines.append("")
    lines.append(f"- 市场环境：主线候选以 {theme_text} 为主，按右侧趋势结构、20日线企稳状态、细分前排/人气和支撑距离排序。")
    lines.append(f"- A档，重点观察（最多5只）：{names(display_a)}")
    lines.append(f"- B档，等待买点（最多5只）：{names(display_b)}")
    lines.append(f"- C档，只跟踪不追（最多5只）：{names(display_c)}")
    lines.append(f"- 过热跟踪，不追高（最多5只）：{names(display_hot)}")
    lines.append(f"- 剔除/暂不追（最多5只）：{names(display_x)}")
    if hard_removed:
        hard_text = "；".join(f"{r['name']}({r['severe_flags']})" for r in display_x if r.get("severe_flags"))
        lines.append(f"- 高分剔除原因：{hard_text or '详见核心表格和逐个点评'}")
    lines.append("")
    lines.append("## 二、核心表格")
    lines.append("")
    lines.append("| 档位 | 状态 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 仓位比例 | 买点观察 |")
    lines.append("|---|---|---:|---|---:|---|---|---|---|---|---|---|---:|---|---|")
    for r in display_rows:
        macd_kdj = f"{r['macd']}；{r['kdj']}，K={r['k']}/D={r['d']}/J={r['j']}"
        key_data = f"成交额{r['amount_yi']:.2f}亿，换手{r['turnoverratio']:.2f}%，涨跌幅{r['changepercent']:.2f}%，距20日线{r['dist20_pct']:.2f}%，{r['ma20_state']}，K线{r['date']}"
        vol = f"量比{r['vol_ratio']:.2f}；成交额排名{r['rank']}"
        tech = f"{r['trend_state']}，{r['structure']}，距20日线{r['dist20_pct']:.2f}%"
        logic = f"{r['theme']}主线；{r['front_row_state']}；{r['tier_reason']}；基本面需另行复核"
        score_text = f"{r['score']}（原始）" if r["tier"] == "剔除" and r.get("severe_flags") else str(r["score"])
        buy_watch_text = f"暂不观察；{r['tier_reason']}" if r["tier"] == "剔除" and r.get("severe_flags") else r["buy_watch"]
        lines.append(
            f"| {r['tier']} | {r.get('state', r['tier'])} | {r['rank']} | {r['name']} | {r['code']} | {r['theme']} | {key_data} | {tech} | {macd_kdj} | {vol} | {logic} | {r['support']} | {score_text} | {r['position_plan']} | {buy_watch_text} |"
        )
    lines.append("")
    lines.append("## 三、逐个点评")
    lines.append("")
    for r in display_rows:
        risk = r["flags"] if r["flags"] else "主要风险是板块高位波动和买点未经二次确认"
        lines.append(
            f"{r['name']}：方向/主线为{r['theme']}，成交额排名{r['rank']}、成交额{r['amount_yi']:.2f}亿、"
            f"换手{r['turnoverratio']:.2f}%、距20日线{r['dist20_pct']:.2f}%。趋势结构是{r['trend_state']}、{r['structure']}；"
            f"MACD/KDJ为{r['macd']}、{r['kdj']}，只作辅助确认。量价/资金看量比{r['vol_ratio']:.2f}。"
            f"证据/逻辑为{r['theme']}主线、{r['front_row_state']}，基本面需结合公告和财报复核。仓位比例为{r['position_plan']}；买点观察是{r['buy_watch']}；"
            f"支撑/失效看{r['support']}。档位原因：{r['tier_reason']}。主要风险：{risk}。"
        )
        lines.append("")
    lines.append("## 四、最终短名单")
    lines.append("")
    lines.append("```text")
    lines.append(f"最优先观察：{names(display_a)}")
    lines.append(f"次优先观察：{names(display_b)}")
    lines.append(f"只跟踪不急买：{names(display_c)}")
    lines.append(f"过热强势只等待整理：{names(display_hot)}")
    lines.append(f"剔除但跟踪板块强度：{names(display_x)}")
    lines.append("```")
    lines.append("")
    lines.append("## 五、买点观察与失效条件")
    lines.append("")
    lines.append("- A/B档共同纪律：不把MACD/KDJ单独作为买点，必须结合趋势结构、量价、20日线企稳状态、支撑距离和细分前排/人气。")
    lines.append("- 均线回踩：优先观察回踩10日/20日线不破，缩量企稳后温和放量转强。")
    lines.append("- 20日线企稳：趋势票调整到或接近20日均线，缩量止跌、收盘不破或1-2日快速收回后再评估。")
    lines.append("- 平台突破：观察突破后不快速跌回平台，或回踩突破位缩量企稳。")
    lines.append("- 强势二买：大阳线后等待3-8日缩量整理，不破10日/20日线再评估。")
    lines.append("- 仓位纪律：仓位比例均为研究观察上限，不是无条件建仓比例；未出现规则内确认时不执行，失效或降级时按 0% 处理。")
    lines.append("- 统一失效：收盘跌破20日线且1-2日不能收回、放量破平台、KDJ高位死叉叠加价格走弱、主线板块放量破位。")
    lines.append("")
    lines.append("## 六、数据限制与风险提示")
    lines.append("")
    lines.append(
        "MACD/KDJ 均来自实际日K计算，但它们不能单独触发买点。若后续指数或主线板块放量破位，A/B档均需重新降级复核；"
        "若个股收盘跌破20日线且1-2日内不能收回，优先剔除。以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。"
    )
    lines.append("")
    lines.append("## 参考来源")
    lines.append("")
    lines.append(f"- 候选池：`{source_label}`")
    lines.append(f"- K线与指标：{kline_label}；本地脚本计算 MA、量比、MACD、KDJ。")
    return "\n".join(lines) + "\n"


TIER_ORDER = {"A": 5, "B": 4, "C": 3, "过热跟踪": 2, "剔除": 1}


def tier_bucket(rows: list[dict], tier: str) -> list[dict]:
    return sorted(
        [row for row in rows if not row.get("error") and row.get("tier") == tier],
        key=lambda row: row.get("composite_score", row.get("score", 0)),
        reverse=True,
    )


def display_rows_for(rows: list[dict]) -> list[dict]:
    display = []
    for tier in ("A", "B", "C"):
        display.extend(tier_bucket(rows, tier)[:5])
    return display


def names_for(rows: list[dict]) -> str:
    return "、".join(row["name"] for row in rows) if rows else "无"


def rank_text(row: dict) -> str:
    label = row.get("rank_label", "排名")
    rank = row.get("source_rank", row.get("rank", ""))
    parts = [f"{label}{rank}"]
    if row.get("turnover_rank") and label != "成交额排名":
        parts.append(f"成交额排名{row['turnover_rank']}")
    if row.get("hot_rank") and label != "人气排名":
        parts.append(f"人气排名{row['hot_rank']}")
    return "；".join(str(part) for part in parts if part)


def merge_recommendations(pool_outputs: list[dict]) -> list[dict]:
    by_code = {}
    for pool in pool_outputs:
        for row in pool["results"]:
            if row.get("error"):
                continue
            by_code.setdefault(row["code"], []).append(row)

    merged = []
    for rows in by_code.values():
        best = sorted(
            rows,
            key=lambda row: (TIER_ORDER.get(row.get("tier"), 0), row.get("score", 0)),
            reverse=True,
        )[0]
        source_titles = sorted({row.get("source_title", "") for row in rows if row.get("source_title")})
        source_types = {row.get("source_type") for row in rows}
        ab_rows = [row for row in rows if row.get("tier") in ("A", "B")]
        if any(row.get("tier") == "A" for row in rows):
            combined_tier = "A"
        elif any(row.get("tier") == "B" for row in rows):
            combined_tier = "B"
        elif any(row.get("tier") == "C" for row in rows):
            combined_tier = "C"
        elif any(row.get("tier") == "过热跟踪" for row in rows):
            combined_tier = "过热跟踪"
        else:
            combined_tier = "剔除"
        bonus = 0
        if len(source_types) >= 2:
            bonus += 8
        if len(ab_rows) >= 2:
            bonus += 4
        composite_score = min(100, int(best.get("score", 0)) + bonus)
        merged.append(
            {
                **best,
                "tier": combined_tier,
                "state": f"综合-{combined_tier}",
                "combined_sources": " + ".join(source_titles),
                "source_count": len(source_types),
                "source_grades": "；".join(
                    f"{row.get('source_title')}:{row.get('tier')}({row.get('score')})" for row in rows
                ),
                "composite_score": composite_score,
            }
        )
    return sorted(
        merged,
        key=lambda row: (
            TIER_ORDER.get(row.get("tier"), 0),
            row.get("source_count", 0),
            row.get("composite_score", 0),
        ),
        reverse=True,
    )


def append_result_table(lines: list[str], rows: list[dict], *, combined: bool = False):
    if combined:
        lines.append("| 档位 | 状态 | 排名 | 标的 | 代码 | 综合来源 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 仓位比例 | 买点观察 |")
        lines.append("|---|---|---|---|---:|---|---|---|---|---|---|---|---|---:|---|---|")
    else:
        lines.append("| 档位 | 状态 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 仓位比例 | 买点观察 |")
        lines.append("|---|---|---|---|---:|---|---|---|---|---|---|---|---:|---|---|")
    for row in rows:
        macd_kdj = f"{row['macd']}；{row['kdj']}，K={row['k']}/D={row['d']}/J={row['j']}"
        key_data = (
            f"成交额{row['amount_yi']:.2f}亿，换手{row['turnoverratio']:.2f}%，"
            f"涨跌幅{row['changepercent']:.2f}%，距20日线{row['dist20_pct']:.2f}%，"
            f"{row['ma20_state']}，K线{row['date']}"
        )
        vol = f"量比{row['vol_ratio']:.2f}；{rank_text(row)}"
        tech = f"{row['trend_state']}，{row['structure']}，距20日线{row['dist20_pct']:.2f}%"
        logic = f"{row['theme']}主线；{row['front_row_state']}；{row['tier_reason']}；基本面需另行复核"
        score = row.get("composite_score", row.get("score", ""))
        if row["tier"] == "剔除" and row.get("severe_flags"):
            score = f"{score}（原始）"
        buy_watch = f"暂不观察；{row['tier_reason']}" if row["tier"] == "剔除" and row.get("severe_flags") else row["buy_watch"]
        rank = rank_text(row)
        if combined:
            lines.append(
                f"| {row['tier']} | {row.get('state', row['tier'])} | {rank} | {row['name']} | {row['code']} | "
                f"{row.get('combined_sources', row.get('source_title', ''))} | {row['theme']} | {key_data} | {tech} | "
                f"{macd_kdj} | {vol} | {logic}；分源结果：{row.get('source_grades', '')} | {row['support']} | "
                f"{score} | {row['position_plan']} | {buy_watch} |"
            )
        else:
            lines.append(
                f"| {row['tier']} | {row.get('state', row['tier'])} | {rank} | {row['name']} | {row['code']} | "
                f"{row['theme']} | {key_data} | {tech} | {macd_kdj} | {vol} | {logic} | {row['support']} | "
                f"{score} | {row['position_plan']} | {buy_watch} |"
            )


def source_conclusion(rows: list[dict]) -> list[str]:
    return [
        f"A档：{names_for(tier_bucket(rows, 'A')[:5])}",
        f"B档：{names_for(tier_bucket(rows, 'B')[:5])}",
        f"C档：{names_for(tier_bucket(rows, 'C')[:5])}",
    ]


def excluded_summary(rows: list[dict]) -> str:
    hot = tier_bucket(rows, "过热跟踪")[:5]
    removed = tier_bucket(rows, "剔除")[:5]
    parts = []
    if hot:
        parts.append(f"过热未纳入ABC：{names_for(hot)}")
    if removed:
        parts.append(f"剔除/暂不纳入：{names_for(removed)}")
    return "；".join(parts) if parts else "无"


def append_commentary(lines: list[str], rows: list[dict], *, combined: bool = False):
    display_rows = display_rows_for(rows)
    if not display_rows:
        lines.append("无 A/B/C 档标的。")
        lines.append("")
        return
    for row in display_rows:
        risk = row["flags"] if row["flags"] else "主要风险是板块高位波动和买点未经二次确认"
        source_text = ""
        if combined:
            source_text = f"综合来源为{row.get('combined_sources', row.get('source_title', ''))}，分源结果为{row.get('source_grades', '')}。"
        lines.append(
            f"{row['name']}：{source_text}方向/主线为{row['theme']}，{rank_text(row)}，"
            f"成交额{row['amount_yi']:.2f}亿、换手{row['turnoverratio']:.2f}%、距20日线{row['dist20_pct']:.2f}%。"
            f"趋势结构是{row['trend_state']}、{row['structure']}；MACD/KDJ为{row['macd']}、{row['kdj']}，只作辅助确认。"
            f"买点观察是{row['buy_watch']}；支撑/失效看{row['support']}。档位原因：{row['tier_reason']}。主要风险：{risk}。"
        )
        lines.append("")


def append_abc_report_block(lines: list[str], title: str, rows: list[dict], *, combined: bool = False):
    lines.append(f"## {title}")
    lines.append("")
    lines.append("### 一、筛选结论")
    lines.append("")
    for item in source_conclusion(rows):
        lines.append(f"- {item}")
    lines.append(f"- 未纳入ABC说明：{excluded_summary(rows)}")
    lines.append("")
    lines.append("### 二、核心表格")
    lines.append("")
    append_result_table(lines, display_rows_for(rows), combined=combined)
    lines.append("")
    lines.append("### 三、逐个点评")
    lines.append("")
    append_commentary(lines, rows, combined=combined)
    lines.append("### 四、最终短名单")
    lines.append("")
    lines.append("```text")
    lines.append(f"A档，最优先观察：{names_for(tier_bucket(rows, 'A')[:5])}")
    lines.append(f"B档，次优先等待：{names_for(tier_bucket(rows, 'B')[:5])}")
    lines.append(f"C档，只跟踪不追：{names_for(tier_bucket(rows, 'C')[:5])}")
    lines.append("```")
    lines.append("")


def generate_multi_source_report(pool_outputs: list[dict], combined_rows: list[dict], summary: dict):
    all_valid = [row for pool in pool_outputs for row in pool["results"] if not row.get("error")]
    top_themes = Counter(row["theme"] for row in all_valid).most_common(6)
    theme_text = "、".join(f"{theme}({count})" for theme, count in top_themes) if top_themes else "无"
    latest_dates = Counter(row["date"] for row in all_valid)
    latest_date_text = "、".join(f"{day}:{count}只" for day, count in latest_dates.items()) if latest_dates else "无"
    kline_label = kline_source_label()

    lines = []
    lines.append("# A股右侧趋势买入标准筛选结果")
    lines.append("")
    lines.append(f"筛选日期：{SCREENING_DATE}")
    lines.append("执行技能：ashare-trend-buy")
    lines.append("结果类型：研究观察池，不是最终买入名单")
    lines.append("")
    lines.append("## 数据说明")
    lines.append("")
    for pool in pool_outputs:
        missing = pool["candidate_count"] - pool["calculated_count"]
        status = f"候选 {pool['candidate_count']} 只，完成指标计算 {pool['calculated_count']} 只，未完成 {missing} 只"
        if pool.get("error"):
            status += f"；数据源失败：{pool['error']}"
        lines.append(f"- {pool['title']}：`{pool['source_label']}`；{status}。")
    lines.append(f"- 日K来源：{kline_label}；最新K线日期分布：{latest_date_text}；结果保存到 `runs/ashare-trend-buy/{SCREENING_DATE}/`。")
    lines.append("- 指标口径：5/10/20/30/60日均线、量比、20日线偏离、20日线企稳分层、MACD(12/26/9)、KDJ(9日RSV)、支撑/失效位、板块内成交前排/人气和右侧趋势评分。")
    lines.append("- 合并口径：同一股票在两个来源中去重，优先保留 A/B 档和高分结果；同时出现在成交额前200与热榜前100的标的给予综合确认加权，但不因为热度直接放宽过热、破位或失效条件。")
    lines.append(f"- 市场环境：候选主线集中在 {theme_text}。")
    lines.append("")

    for pool in pool_outputs:
        append_abc_report_block(lines, f"{pool['title']}筛选结果", pool["results"])
    append_abc_report_block(lines, "综合推荐", combined_rows, combined=True)

    lines.append("## 买点观察与失效条件")
    lines.append("")
    lines.append("- A/B档共同纪律：不把MACD/KDJ单独作为买点，必须结合趋势结构、量价、20日线企稳状态、支撑距离和细分前排/人气。")
    lines.append("- 成交额前200用于识别资金承载和高流动性；热榜前100用于识别关注度和潜在扩散，但热度不能替代趋势、支撑和不过热条件。")
    lines.append("- 均线回踩：优先观察回踩10日/20日线不破，缩量企稳后温和放量转强。")
    lines.append("- 平台突破：观察突破后不快速跌回平台，或回踩突破位缩量企稳。")
    lines.append("- 统一失效：收盘跌破20日线且1-2日不能收回、放量破平台、KDJ高位死叉叠加价格走弱、主线板块放量破位。")
    lines.append("")
    lines.append("## 参考来源")
    lines.append("")
    for pool in pool_outputs:
        lines.append(f"- {pool['title']}：`{pool['source_label']}`")
    lines.append(f"- K线与指标：{kline_label}；本地脚本计算 MA、量比、MACD、KDJ。")
    lines.append("")
    lines.append("以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。")
    return "\n".join(lines) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="Run ashare-trend-buy screening.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Screening date, YYYY-MM-DD.")
    parser.add_argument("--runs-dir", default="runs", help="Run artifact root directory.")
    parser.add_argument("--top200", help="Optional verified same-day turnover top-200 CSV.")
    parser.add_argument("--max-candidates", type=int, help="Optional per-source cap for fast runs when data sources throttle.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for daily K-line fetches.")
    parser.add_argument("--request-retries", type=int, default=4, help="HTTP retry attempts for quote and K-line APIs.")
    parser.add_argument("--request-backoff", type=float, default=1.0, help="Base seconds for exponential retry backoff.")
    parser.add_argument("--request-jitter", type=float, default=0.35, help="Random extra seconds added to retries and K-line pacing.")
    parser.add_argument("--kline-request-delay", type=float, default=0.35, help="Base seconds to wait before each K-line HTTP request.")
    parser.add_argument(
        "--market-cache-db",
        default=str(DEFAULT_MARKET_CACHE_DB),
        help="SQLite cache from ashare-kline-sqlite-cache; used before public APIs.",
    )
    parser.add_argument("--ignore-market-cache", action="store_true", help="Skip ashare-kline-sqlite-cache SQLite reads.")
    parser.add_argument("--no-network", action="store_true", help="Disable network access.")
    return parser.parse_args()


def configure(args):
    global RUN_DIR, RUNS_ROOT, SOURCE_TOP200, SCREENING_DATE, NO_NETWORK
    global MARKET_CACHE_DB, IGNORE_MARKET_CACHE
    global REQUEST_RETRIES, REQUEST_BACKOFF, REQUEST_JITTER, KLINE_REQUEST_DELAY
    SCREENING_DATE = args.date
    NO_NETWORK = bool(args.no_network)
    MARKET_CACHE_DB = Path(args.market_cache_db)
    if not MARKET_CACHE_DB.is_absolute():
        MARKET_CACHE_DB = ROOT / MARKET_CACHE_DB
    IGNORE_MARKET_CACHE = bool(args.ignore_market_cache)
    REQUEST_RETRIES = max(1, int(args.request_retries or 1))
    REQUEST_BACKOFF = max(0.0, float(args.request_backoff or 0.0))
    REQUEST_JITTER = max(0.0, float(args.request_jitter or 0.0))
    KLINE_REQUEST_DELAY = max(0.0, float(args.kline_request_delay or 0.0))
    runs_root = Path(args.runs_dir)
    if not runs_root.is_absolute():
        runs_root = ROOT / runs_root
    RUNS_ROOT = runs_root
    RUN_DIR = runs_root / "ashare-trend-buy" / SCREENING_DATE
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    if args.top200:
        SOURCE_TOP200 = Path(args.top200)
        if not SOURCE_TOP200.is_absolute():
            SOURCE_TOP200 = ROOT / SOURCE_TOP200
    else:
        SOURCE_TOP200 = None

    if SOURCE_TOP200 is not None and not SOURCE_TOP200.exists():
        raise FileNotFoundError(f"top200 file not found: {SOURCE_TOP200}")


def main():
    args = parse_args()
    configure(args)
    progress(
        "start ashare-trend-buy "
        f"date={SCREENING_DATE} workers={args.workers} "
        f"max_candidates={args.max_candidates or 'full'} "
        f"retries={REQUEST_RETRIES}"
    )
    progress("fetching candidate pools")
    pools = read_candidate_pools()
    for pool in pools:
        if args.max_candidates:
            pool["rows"] = pool["rows"][: args.max_candidates]
        progress(
            f"pool loaded key={pool['key']} candidates={len(pool['rows'])} "
            f"source={pool['source_label']} error={pool.get('error', '') or '-'}"
        )

    symbol_rows = {}
    for pool in pools:
        for row in pool["rows"]:
            symbol_rows.setdefault(row["symbol"], row)

    kline_cache = {}
    workers = max(1, int(args.workers or 1))
    total_symbols = len(symbol_rows)
    progress(f"fetching daily kline symbols={total_symbols} workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_symbol = {
            executor.submit(fetch_kline, row["symbol"]): row["symbol"]
            for row in symbol_rows.values()
        }
        completed = 0
        failed = 0
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                kline_cache[symbol] = future.result()
            except Exception as exc:
                kline_cache[symbol] = exc
                failed += 1
            completed += 1
            if completed == total_symbols or completed % 10 == 0:
                progress(
                    f"kline progress completed={completed}/{total_symbols} "
                    f"failed={failed}"
                )

    pool_outputs = []
    for pool in pools:
        candidates = pool["rows"]
        results = []
        progress(f"scoring pool key={pool['key']} candidates={len(candidates)}")
        for row in candidates:
            try:
                cached = kline_cache[row["symbol"]]
                if isinstance(cached, Exception):
                    raise cached
                krows, _payload = cached
                ind = indicators(krows)
                results.append(score_candidate(row, ind))
            except Exception as exc:
                results.append({**row, "tier": "初筛观察池", "error": str(exc)})
        enrich_relative_context(results)
        calculated = [r for r in results if not r.get("error")]
        pool_outputs.append(
            {
                **pool,
                "candidate_count": len(candidates),
                "calculated_count": len(calculated),
                "results": results,
                "tier_counts": dict(Counter(r["tier"] for r in calculated)),
            }
        )
        progress(
            f"pool scored key={pool['key']} calculated={len(calculated)}/{len(candidates)} "
            f"tier_counts={dict(Counter(r['tier'] for r in calculated))}"
        )

    combined_rows = merge_recommendations(pool_outputs)
    calculated = [row for pool in pool_outputs for row in pool["results"] if not row.get("error")]
    summary = {
        "screening_date": SCREENING_DATE,
        "sources": [
            {
                "key": pool["key"],
                "title": pool["title"],
                "source_label": pool["source_label"],
                "candidate_count": pool["candidate_count"],
                "calculated_count": pool["calculated_count"],
                "error": pool.get("error", ""),
                "tier_counts": pool["tier_counts"],
            }
            for pool in pool_outputs
        ],
        "candidate_count": sum(pool["candidate_count"] for pool in pool_outputs),
        "calculated_count": len(calculated),
        "latest_kline_dates": dict(Counter(r["date"] for r in calculated)),
        "tier_counts": dict(Counter(r["tier"] for r in calculated)),
        "combined_count": len(combined_rows),
    }
    progress(f"writing report path={RUN_DIR / f'{SCREENING_DATE}.md'}")
    report = generate_multi_source_report(pool_outputs, combined_rows, summary)
    (RUN_DIR / f"{SCREENING_DATE}.md").write_text(report, encoding="utf-8")
    progress(
        f"done calculated={summary['calculated_count']}/{summary['candidate_count']} "
        f"combined={summary['combined_count']}"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for row in combined_rows[:25]:
        print(row["tier"], row.get("composite_score", row["score"]), row["code"], row["name"], row["theme"], row["date"], row.get("combined_sources", ""))

if __name__ == "__main__":
    main()
