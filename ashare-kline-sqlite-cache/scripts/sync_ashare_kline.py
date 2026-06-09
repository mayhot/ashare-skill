import argparse
import csv
import io
import json
import random
import sqlite3
import sys
import threading
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
SINA_KLINE_URLS = [
    "https://quotes.sina.cn/cn/api/json_v2.php/"
    "CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}",
    "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}",
]
TENCENT_KLINE_URL = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
NETEASE_KLINE_URL = (
    "http://quotes.money.163.com/service/chddata.html?"
    "code={symbol}&start={begin}&end={end}&"
    "fields=TCLOSE;HIGH;LOW;TOPEN;LCLOSE;CHG;PCHG;VOTURNOVER;VATURNOVER;TURNOVER"
)
EASTMONEY_POPULARITY_URLS = [
    "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
    "http://emappdata.eastmoney.com/stockrank/getAllCurrentList",
]
ADJUST_FLAGS = {"none": "0", "qfq": "1", "hfq": "2"}
DEFAULT_KLINE_SOURCES = ["tencent", "eastmoney", "sina", "netease", "akshare"]
DEFAULT_POPULARITY_SOURCES = ["eastmoney", "akshare"]
REQUEST_THROTTLE_LOCK = threading.Lock()
NEXT_REQUEST_AT = 0.0


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


def log(message: str) -> None:
    stamp = now_china().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def format_eta(done: int, total: int, elapsed: float) -> str:
    if done <= 0 or total <= 0 or done >= total:
        return "0s"
    rate = done / max(elapsed, 0.001)
    return format_duration((total - done) / rate)


def format_count_map(counts: dict[str, int]) -> str:
    visible = [f"{key}:{value}" for key, value in counts.items() if value]
    return ",".join(visible) if visible else "none"


def format_average_seconds(totals: dict[str, float], counts: dict[str, int]) -> str:
    values = []
    for key, total in totals.items():
        count = counts.get(key, 0)
        if count:
            values.append(f"{key}:{total / count:.2f}s")
    return ",".join(values) if values else "none"


class SourceCircuitBreaker:
    def __init__(self, threshold: int) -> None:
        self.threshold = max(0, int(threshold or 0))
        self.failures: dict[str, int] = {}
        self.failure_streaks: dict[str, int] = {}
        self.disabled: set[str] = set()
        self.lock = threading.Lock()

    def allow(self, source: str) -> bool:
        if self.threshold <= 0:
            return True
        with self.lock:
            return source not in self.disabled

    def record_failure(self, source: str, exc: Exception) -> bool:
        if self.threshold <= 0:
            return False
        should_log = False
        with self.lock:
            if source in self.disabled:
                return True
            failures = self.failures.get(source, 0) + 1
            streak = self.failure_streaks.get(source, 0) + 1
            self.failures[source] = failures
            self.failure_streaks[source] = streak
            if streak >= self.threshold:
                self.disabled.add(source)
                should_log = True
        if should_log:
            log(
                "kline source disabled: "
                f"source={source} consecutive_failures={streak} total_failures={failures} "
                f"threshold={self.threshold} last_error={str(exc)[:160]}"
            )
        return should_log

    def record_success(self, source: str) -> None:
        if self.threshold <= 0:
            return
        with self.lock:
            self.failure_streaks[source] = 0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "threshold": self.threshold,
                "failures": dict(self.failures),
                "failure_streaks": dict(self.failure_streaks),
                "disabled": sorted(self.disabled),
            }


def parse_sources(value: str, default: list[str], allowed: set[str]) -> list[str]:
    text = str(value or "auto").strip().lower()
    if text == "auto":
        return list(default)
    sources = [item.strip().lower() for item in text.split(",") if item.strip()]
    unknown = [item for item in sources if item not in allowed]
    if unknown:
        raise SystemExit(f"Unsupported source(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}, auto")
    deduped: list[str] = []
    for source in sources:
        if source not in deduped:
            deduped.append(source)
    if not deduped:
        raise SystemExit("At least one source must be selected.")
    return deduped


def throttle_public_request(request_delay: float, request_jitter: float) -> None:
    global NEXT_REQUEST_AT
    delay = max(0.0, float(request_delay or 0.0))
    jitter = max(0.0, float(request_jitter or 0.0))
    if delay <= 0 and jitter <= 0:
        return
    spacing = delay + (random.uniform(0, jitter) if jitter > 0 else 0.0)
    with REQUEST_THROTTLE_LOCK:
        now = time.monotonic()
        target = max(now, NEXT_REQUEST_AT)
        NEXT_REQUEST_AT = target + spacing
    wait = target - now
    if wait > 0:
        time.sleep(wait)


def retry_sleep_seconds(attempt: int, retry_base_sleep: float, retry_max_sleep: float) -> float:
    base = max(0.0, float(retry_base_sleep or 0.0))
    maximum = max(base, float(retry_max_sleep or base or 0.0))
    delay = min(maximum, base * (2 ** attempt))
    jitter = random.uniform(0, min(1.0, max(base, 0.0))) if base > 0 else 0.0
    return delay + jitter


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


def netease_symbol_for_code(code: str) -> str:
    code = normalize_code(code)
    exchange = exchange_for_code(code)
    if exchange == "SH":
        return f"0{code}"
    if exchange == "SZ":
        return f"1{code}"
    return f"2{code}"


def to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def request_json(
    url: str,
    timeout: int,
    attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    last_error: Exception | None = None
    total_attempts = max(1, int(attempts or 1))
    for attempt in range(total_attempts):
        if source_breaker and source_name and not source_breaker.allow(source_name):
            raise RuntimeError(f"{source_name} disabled after repeated request failures")
        try:
            throttle_public_request(request_delay, request_jitter)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if source_breaker and source_name:
                    source_breaker.record_success(source_name)
                return payload
        except Exception as exc:
            last_error = exc
            disabled = False
            if source_breaker and source_name:
                disabled = source_breaker.record_failure(source_name, exc)
            if disabled:
                break
            if attempt < total_attempts - 1:
                time.sleep(retry_sleep_seconds(attempt, retry_base_sleep, retry_max_sleep))
    raise last_error or RuntimeError("request failed")


def request_text(
    url: str,
    timeout: int,
    attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
    source_name: str | None = None,
    encoding: str = "utf-8",
) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    last_error: Exception | None = None
    total_attempts = max(1, int(attempts or 1))
    for attempt in range(total_attempts):
        if source_breaker and source_name and not source_breaker.allow(source_name):
            raise RuntimeError(f"{source_name} disabled after repeated request failures")
        try:
            throttle_public_request(request_delay, request_jitter)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                try:
                    text = data.decode(encoding)
                except UnicodeDecodeError:
                    text = data.decode("gb18030", errors="replace")
                if source_breaker and source_name:
                    source_breaker.record_success(source_name)
                return text
        except Exception as exc:
            last_error = exc
            disabled = False
            if source_breaker and source_name:
                disabled = source_breaker.record_failure(source_name, exc)
            if disabled:
                break
            if attempt < total_attempts - 1:
                time.sleep(retry_sleep_seconds(attempt, retry_base_sleep, retry_max_sleep))
    raise last_error or RuntimeError("request failed")


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://quote.eastmoney.com/",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    total_attempts = max(1, int(attempts or 1))
    for attempt in range(total_attempts):
        try:
            throttle_public_request(request_delay, request_jitter)
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < total_attempts - 1:
                time.sleep(retry_sleep_seconds(attempt, retry_base_sleep, retry_max_sleep))
    raise last_error or RuntimeError("request failed")


def fetch_stock_universe(
    limit: int | None,
    timeout: int,
    prefer_akshare: bool,
    universe_source: str,
) -> tuple[list[dict[str, Any]], str]:
    if universe_source in ("official", "auto"):
        try:
            rows = fetch_stock_universe_official(limit)
            if rows:
                return rows, "official_exchanges:akshare_wrapped"
        except Exception as exc:
            if universe_source == "official":
                raise
            print(f"official exchange universe unavailable, falling back to market sources: {exc}")
    if universe_source == "seed":
        raise RuntimeError("--universe-source seed requires --seed-kline-csv and is handled before online fetch")
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


def fetch_stock_universe_official(limit: int | None) -> list[dict[str, Any]]:
    import akshare as ak  # type: ignore

    started = time.time()
    log("official universe: fetching SSE/SZSE/BSE stock lists")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    source_counts = {"SSE": 0, "SZSE": 0, "BSE": 0}

    for indicator, board in [("主板A股", "SSE Main Board"), ("科创板", "STAR Market")]:
        try:
            df = call_with_retries(lambda: ak.stock_info_sh_name_code(indicator), f"SSE {indicator}")
            normalized = normalize_official_rows(df.to_dict("records"), "SH", board, "SSE")
            rows.extend(normalized)
            source_counts["SSE"] += len(normalized)
            log(f"official universe: SSE {indicator} rows={len(normalized)} total_sse={source_counts['SSE']}")
        except Exception as exc:
            errors.append(f"SSE {indicator}: {exc}")

    try:
        df = call_with_retries(lambda: ak.stock_info_sz_name_code("A股列表"), "SZSE A股列表")
        normalized = normalize_official_rows(df.to_dict("records"), "SZ", "", "SZSE")
        rows.extend(normalized)
        source_counts["SZSE"] += len(normalized)
        log(f"official universe: SZSE A-share rows={len(normalized)}")
    except Exception as exc:
        errors.append(f"SZSE A股列表: {exc}")

    try:
        df = call_with_retries(ak.stock_info_bj_name_code, "BSE stock list")
        normalized = normalize_official_rows(df.to_dict("records"), "BJ", "BSE", "BSE")
        rows.extend(normalized)
        source_counts["BSE"] += len(normalized)
        log(f"official universe: BSE rows={len(normalized)}")
    except Exception as exc:
        errors.append(f"BSE stock list: {exc}")

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["code"]
        if not is_a_share_code(code, row.get("exchange", "")):
            continue
        deduped[code] = row

    result = sorted(deduped.values(), key=lambda item: item["code"])
    if limit:
        result = result[:limit]
    missing_sources = [source for source, count in source_counts.items() if count <= 0]
    if missing_sources:
        raise RuntimeError(
            "official exchange universe incomplete; "
            f"missing={','.join(missing_sources)}; "
            f"counts={source_counts}; errors={'; '.join(errors)}"
        )
    if not result:
        raise RuntimeError("; ".join(errors) or "official exchange universe returned empty")
    log(f"official universe: merged rows={len(result)} counts={source_counts} elapsed={format_duration(time.time() - started)}")
    return result


def call_with_retries(fn: Any, label: str, attempts: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            started = time.time()
            log(f"{label}: fetch attempt {attempt + 1}/{attempts}")
            result = fn()
            log(f"{label}: fetch ok elapsed={format_duration(time.time() - started)}")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                log(f"{label}: failed, retrying: {exc}")
                time.sleep(1.0 + attempt * 2)
    raise last_error or RuntimeError(f"{label} failed")


def normalize_official_rows(records: list[dict[str, Any]], exchange: str, default_board: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in records:
        code = normalize_code(
            raw.get("代码")
            or raw.get("公司代码")
            or raw.get("A股代码")
            or raw.get("证券代码")
        )
        if not code:
            continue
        name = (
            raw.get("简称")
            or raw.get("公司简称")
            or raw.get("A股简称")
            or raw.get("证券简称")
            or ""
        )
        board = str(raw.get("板块") or default_board or "").strip()
        rows.append(
            {
                "code": code,
                "name": str(name).strip(),
                "exchange": exchange,
                "secid": secid_for_code(code),
                "board": board,
                "listing_date": str(
                    raw.get("上市日期")
                    or raw.get("A股上市日期")
                    or ""
                ).strip(),
                "industry": str(raw.get("所属行业") or "").strip(),
                "region": str(raw.get("地区") or raw.get("注册地") or "").strip(),
                "official_source": source,
                "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
            }
        )
    return rows


def is_a_share_code(code: str, exchange: str) -> bool:
    code = normalize_code(code)
    if exchange == "SH":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if exchange == "BJ":
        return code.startswith(("4", "8", "920"))
    return bool(code)


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
    sources: list[str],
    request_attempts: int,
    retry_base_sleep: float,
    retry_max_sleep: float,
    request_delay: float,
    request_jitter: float,
    source_breaker: SourceCircuitBreaker | None = None,
) -> tuple[str, list[dict[str, Any]], str, float]:
    errors: list[str] = []
    last_code = stock["code"]
    for source in sources:
        if source_breaker and not source_breaker.allow(source):
            errors.append(f"{source}: disabled after repeated request failures")
            continue
        source_started = time.time()
        try:
            if source == "eastmoney":
                code, rows = fetch_eastmoney_kline_rows(
                    stock,
                    begin,
                    end,
                    adjust,
                    timeout,
                    request_attempts,
                    retry_base_sleep,
                    retry_max_sleep,
                    request_delay,
                    request_jitter,
                    source_breaker,
                )
            elif source == "tencent":
                code, rows = fetch_tencent_kline_rows(
                    stock,
                    begin,
                    end,
                    adjust,
                    timeout,
                    request_attempts,
                    retry_base_sleep,
                    retry_max_sleep,
                    request_delay,
                    request_jitter,
                    source_breaker,
                )
            elif source == "netease":
                code, rows = fetch_netease_kline_rows(
                    stock,
                    begin,
                    end,
                    adjust,
                    timeout,
                    request_attempts,
                    retry_base_sleep,
                    retry_max_sleep,
                    request_delay,
                    request_jitter,
                    source_breaker,
                )
            elif source == "sina":
                code, rows = fetch_sina_kline_rows(
                    stock,
                    begin,
                    end,
                    adjust,
                    timeout,
                    request_attempts,
                    retry_base_sleep,
                    retry_max_sleep,
                    request_delay,
                    request_jitter,
                    source_breaker,
                )
            elif source == "akshare":
                code, rows = fetch_akshare_kline_rows(
                    stock,
                    begin,
                    end,
                    adjust,
                )
            else:
                raise RuntimeError(f"unsupported kline source: {source}")
            last_code = code
            if rows:
                return code, rows, source, time.time() - source_started
            errors.append(f"{source}: empty")
        except Exception as exc:
            if source in ("akshare", "sina") and source_breaker:
                source_breaker.record_failure(source, exc)
            errors.append(f"{source}: {exc}")
    raise RuntimeError("; ".join(errors) or "all kline sources failed")


def fetch_eastmoney_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
    request_attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    code = stock["code"]
    url = EASTMONEY_KLINE_URL.format(
        secid=stock.get("secid") or secid_for_code(code),
        begin=begin,
        end=end,
        fqt=ADJUST_FLAGS[adjust],
    )
    payload = request_json(
        url,
        timeout,
        request_attempts,
        retry_base_sleep,
        retry_max_sleep,
        request_delay,
        request_jitter,
        source_breaker,
        "eastmoney",
    )
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
    request_attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
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
        payload = request_json(
            TENCENT_KLINE_URL.format(param=param),
            timeout,
            request_attempts,
            retry_base_sleep,
            retry_max_sleep,
            request_delay,
            request_jitter,
            source_breaker,
            "tencent",
        )
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


def fetch_netease_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
    request_attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    if adjust != "none":
        return stock["code"], []
    code = stock["code"]
    text = request_text(
        NETEASE_KLINE_URL.format(symbol=netease_symbol_for_code(code), begin=begin, end=end),
        timeout,
        request_attempts,
        retry_base_sleep,
        retry_max_sleep,
        request_delay,
        request_jitter,
        source_breaker,
        "netease",
        "gb18030",
    )
    return code, parse_netease_kline_csv(stock, text)


def parse_netease_kline_csv(stock: dict[str, Any], text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    code = stock["code"]
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    for parts in reader:
        if len(parts) < 13:
            continue
        trade_date = str(parts[0]).strip()
        if not trade_date or trade_date.lower() == "none":
            continue
        close = to_float(parts[3])
        open_price = to_float(parts[6])
        high = to_float(parts[4])
        low = to_float(parts[5])
        if close is None and open_price is None and high is None and low is None:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": trade_date,
                "name": stock.get("name") or str(parts[2]).strip(),
                "exchange": stock.get("exchange") or exchange_for_code(code),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": to_float(parts[10]),
                "amount": to_float(parts[11]),
                "amplitude": None,
                "pct_chg": to_float(parts[9]),
                "change_amount": to_float(parts[8]),
                "turnover": to_float(parts[12]),
                "source": "netease.chddata.adjust=none",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_line": ",".join(parts),
            }
        )
    return sorted(rows, key=lambda item: item["trade_date"])


def fetch_sina_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
    timeout: int,
    request_attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
    source_breaker: SourceCircuitBreaker | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    if adjust != "none":
        return stock["code"], []

    code = stock["code"]
    begin_date = f"{begin[:4]}-{begin[4:6]}-{begin[6:]}"
    end_date = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    begin_dt = datetime.strptime(begin_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    datalen = max(30, min(1200, int((end_dt - begin_dt).days * 1.8) + 30))
    data: list[dict[str, Any]] = []
    errors: list[str] = []
    for url_template in SINA_KLINE_URLS:
        try:
            payload = request_json(
                url_template.format(symbol=qq_symbol_for_code(code), datalen=datalen),
                timeout,
                request_attempts,
                retry_base_sleep,
                retry_max_sleep,
                request_delay,
                request_jitter,
                source_breaker,
                "sina",
            )
            if isinstance(payload, list):
                data = payload
            if data:
                break
            errors.append("empty")
        except Exception as exc:
            errors.append(str(exc))
    if not data:
        if errors:
            raise RuntimeError("; ".join(errors))
        return code, []
    rows: list[dict[str, Any]] = []
    for raw in data:
        trade_date = value_by_alias(raw, ["day", "date", "日期"], 0)
        trade_date = str(trade_date)[:10]
        if trade_date < begin_date or trade_date > end_date:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": trade_date,
                "name": stock.get("name") or "",
                "exchange": stock.get("exchange") or exchange_for_code(code),
                "open": to_float(value_by_alias(raw, ["open", "开盘"], 1)),
                "close": to_float(value_by_alias(raw, ["close", "收盘"], 4)),
                "high": to_float(value_by_alias(raw, ["high", "最高"], 2)),
                "low": to_float(value_by_alias(raw, ["low", "最低"], 3)),
                "volume": to_float(value_by_alias(raw, ["volume", "成交量"], 5)),
                "amount": to_float(value_by_alias(raw, ["amount", "成交额"], 6)),
                "amplitude": None,
                "pct_chg": None,
                "change_amount": None,
                "turnover": to_float(value_by_alias(raw, ["turnover", "换手率"], 8)),
                "source": "sina.stock_zh_a_daily.adjust=none",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_line": json.dumps(raw, ensure_ascii=False, default=str),
            }
        )
    return code, [row for row in rows if row["trade_date"]]


def value_by_alias(raw: dict[str, Any], aliases: list[str], fallback_index: int) -> Any:
    for alias in aliases:
        if alias in raw:
            return raw.get(alias)
    values = list(raw.values())
    if fallback_index < len(values):
        return values[fallback_index]
    return None


def fetch_akshare_kline_rows(
    stock: dict[str, Any],
    begin: str,
    end: str,
    adjust: str,
) -> tuple[str, list[dict[str, Any]]]:
    import akshare as ak  # type: ignore

    code = stock["code"]
    ak_adjust = "" if adjust == "none" else adjust
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=begin, end_date=end, adjust=ak_adjust)
    if df is None or df.empty:
        return code, []
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict("records"):
        values = list(raw.values())
        if len(values) < 12:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": str(values[0])[:10],
                "name": stock.get("name") or "",
                "exchange": stock.get("exchange") or exchange_for_code(code),
                "open": to_float(values[2]),
                "close": to_float(values[3]),
                "high": to_float(values[4]),
                "low": to_float(values[5]),
                "volume": to_float(values[6]),
                "amount": to_float(values[7]),
                "amplitude": to_float(values[8]),
                "pct_chg": to_float(values[9]),
                "change_amount": to_float(values[10]),
                "turnover": to_float(values[11]),
                "source": f"akshare.stock_zh_a_hist.adjust={adjust}",
                "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                "raw_line": json.dumps(raw, ensure_ascii=False, default=str),
            }
        )
    return code, rows


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")
    conn.commit()


def fetch_popularity_top100(
    trade_date: str,
    timeout: int,
    limit: int,
    sources: list[str],
    request_attempts: int,
    retry_base_sleep: float,
    retry_max_sleep: float,
    request_delay: float,
    request_jitter: float,
) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for source in sources:
        try:
            if source == "akshare":
                rows = fetch_popularity_top100_akshare(trade_date, limit)
                source_name = "akshare.stock_hot_rank_em"
            elif source == "eastmoney":
                rows = fetch_popularity_top100_eastmoney(
                    trade_date,
                    timeout,
                    limit,
                    request_attempts,
                    retry_base_sleep,
                    retry_max_sleep,
                    request_delay,
                    request_jitter,
                )
                source_name = "eastmoney.stockrank.getAllCurrentList"
            else:
                raise RuntimeError(f"unsupported popularity source: {source}")
            if rows:
                return rows, source_name
            errors.append(f"{source}: empty")
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            log(f"popularity source failed: {source}: {exc}")
    raise RuntimeError("; ".join(errors) or "all popularity sources failed")


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
    request_attempts: int = 3,
    retry_base_sleep: float = 0.5,
    retry_max_sleep: float = 8.0,
    request_delay: float = 0.0,
    request_jitter: float = 0.0,
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
            response = post_json(
                url,
                payload,
                timeout,
                request_attempts,
                retry_base_sleep,
                retry_max_sleep,
                request_delay,
                request_jitter,
            )
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
            board TEXT,
            listing_date TEXT,
            industry TEXT,
            region TEXT,
            official_source TEXT,
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
    ensure_columns(
        conn,
        "stock_universe",
        {
            "board": "TEXT",
            "listing_date": "TEXT",
            "industry": "TEXT",
            "region": "TEXT",
            "official_source": "TEXT",
        },
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
        "board",
        "listing_date",
        "industry",
        "region",
        "official_source",
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


def prune_stock_universe_to_codes(conn: sqlite3.Connection, codes: set[str]) -> int:
    if not codes:
        return 0
    placeholders = ",".join("?" for _ in codes)
    cur = conn.execute(
        f"DELETE FROM stock_universe WHERE code NOT IN ({placeholders})",
        tuple(codes),
    )
    conn.commit()
    return int(cur.rowcount or 0)


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


def load_seed_kline_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    begin: str,
    end: str,
    wanted_codes: set[str] | None,
    batch_rows: int,
) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    started = time.time()
    file_size = csv_path.stat().st_size
    log(f"seed csv: start path={csv_path} size={file_size / 1024 / 1024:.1f}MB")
    begin_date = f"{begin[:4]}-{begin[4:6]}-{begin[6:]}"
    end_date = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    imported = 0
    scanned = 0
    matched = 0
    last_log = started
    pending: list[dict[str, Any]] = []
    fetched_at = now_china().strftime("%Y-%m-%d %H:%M:%S%z")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            scanned += 1
            code = normalize_code(raw.get("code"))
            if not code or (wanted_codes is not None and code not in wanted_codes):
                continue
            trade_date = str(raw.get("date") or raw.get("trade_date") or "").strip()
            if not trade_date or trade_date < begin_date or trade_date > end_date:
                continue
            matched += 1
            pending.append(
                {
                    "code": code,
                    "trade_date": trade_date,
                    "name": str(raw.get("name") or "").strip() or code,
                    "exchange": exchange_for_code(code),
                    "open": to_float(raw.get("open")),
                    "close": to_float(raw.get("close")),
                    "high": to_float(raw.get("high")),
                    "low": to_float(raw.get("low")),
                    "volume": to_float(raw.get("volume")),
                    "amount": to_float(raw.get("amount")),
                    "amplitude": to_float(raw.get("amplitude")),
                    "pct_chg": to_float(raw.get("pct_chg") or raw.get("pctChg")),
                    "change_amount": to_float(raw.get("change_amount")),
                    "turnover": to_float(raw.get("turnover")),
                    "source": f"seed_csv:{csv_path.name}",
                    "fetched_at": fetched_at,
                    "raw_line": json.dumps(raw, ensure_ascii=False),
                }
            )
            if len(pending) >= batch_rows:
                imported += upsert_kline_rows(conn, pending)
                pending = []
            current = time.time()
            if scanned % 100_000 == 0 or current - last_log >= 15:
                last_log = current
                log(
                    "seed csv: "
                    f"scanned={scanned:,} matched={matched:,} imported={imported + len(pending):,} "
                    f"elapsed={format_duration(current - started)}"
                )
    imported += upsert_kline_rows(conn, pending)
    log(
        "seed csv: done "
        f"scanned={scanned:,} matched={matched:,} imported={imported:,} "
        f"elapsed={format_duration(time.time() - started)}"
    )
    return imported


def kline_status_by_code(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT code, COUNT(*) AS row_count, MAX(trade_date) AS latest_date
        FROM daily_kline
        GROUP BY code
        """
    ).fetchall()
    return {
        str(row[0]): {"row_count": int(row[1] or 0), "latest_date": str(row[2] or "")}
        for row in rows
    }


def load_cached_official_universe(conn: sqlite3.Connection, limit: int | None) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            code, name, exchange, secid, board, listing_date,
            industry, region, official_source, raw_json
        FROM stock_universe
        WHERE official_source IN ('SSE', 'SZSE', 'BSE')
        ORDER BY code
        """
    ).fetchall()
    result = [
        {
            "code": row[0],
            "name": row[1],
            "exchange": row[2],
            "secid": row[3] or secid_for_code(row[0]),
            "board": row[4],
            "listing_date": row[5],
            "industry": row[6],
            "region": row[7],
            "official_source": row[8],
            "raw_json": row[9] or "{}",
        }
        for row in rows
    ]
    return result[:limit] if limit else result


def cached_official_universe_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT official_source, COUNT(*)
        FROM stock_universe
        WHERE official_source IN ('SSE', 'SZSE', 'BSE')
        GROUP BY official_source
        """
    ).fetchall()
    counts = {"SSE": 0, "SZSE": 0, "BSE": 0}
    for source, count in rows:
        counts[str(source)] = int(count or 0)
    return counts


def has_complete_cached_official_universe(conn: sqlite3.Connection) -> bool:
    counts = cached_official_universe_counts(conn)
    return all(counts[source] > 0 for source in ("SSE", "SZSE", "BSE"))


def should_refresh_official_universe(conn: sqlite3.Connection, args: argparse.Namespace) -> bool:
    if args.refresh_universe:
        return True
    if not has_complete_cached_official_universe(conn):
        return True
    trade_day = datetime.strptime(args.trade_date, "%Y-%m-%d").date()
    return trade_day.day == args.official_universe_refresh_day


def yyyymmdd_days_before(trade_date: str, days: int) -> str:
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d").date()
    return (end_dt - timedelta(days=days)).strftime("%Y%m%d")


def yyyymmdd_day_after(trade_date: str) -> str:
    parsed = datetime.strptime(trade_date, "%Y-%m-%d").date()
    return (parsed + timedelta(days=1)).strftime("%Y%m%d")


def build_fetch_jobs(
    conn: sqlite3.Connection,
    stocks: list[dict[str, Any]],
    begin: str,
    end: str,
    args: argparse.Namespace,
    seed_rows_imported: int,
) -> list[tuple[dict[str, Any], str, str]]:
    if seed_rows_imported <= 0:
        log(f"fetch plan: no seed rows, scheduling full window for {len(stocks)} symbols")
        return [(stock, begin, end) for stock in stocks]

    status = kline_status_by_code(conn)
    jobs: list[tuple[dict[str, Any], str, str]] = []
    skipped_current = 0
    gap_jobs = 0
    full_jobs = 0
    for stock in stocks:
        code = stock["code"]
        item = status.get(code, {})
        row_count = int(item.get("row_count") or 0)
        latest_date = str(item.get("latest_date") or "")
        if row_count > 0 and latest_date >= args.trade_date:
            skipped_current += 1
            continue
        if row_count > 0 and latest_date:
            job_begin = max(begin, yyyymmdd_day_after(latest_date))
            gap_jobs += 1
        else:
            job_begin = begin
            full_jobs += 1
        jobs.append((stock, job_begin, end))
    log(
        "fetch plan: "
        f"total={len(stocks)} skipped_current={skipped_current} "
        f"gap_fill={gap_jobs} full={full_jobs}"
    )
    return jobs


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


def kline_coverage_for_date(conn: sqlite3.Connection, trade_date: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS universe_count,
               SUM(
                 CASE WHEN EXISTS (
                   SELECT 1
                   FROM daily_kline k
                   WHERE k.code = u.code AND k.trade_date = ?
                 )
                 THEN 1 ELSE 0 END
               ) AS cached_count
        FROM stock_universe u
        """,
        (trade_date,),
    ).fetchone()
    universe_count = int(row[0] or 0)
    cached_count = int(row[1] or 0)
    return {
        "trade_date": trade_date,
        "universe_count": universe_count,
        "cached_count": cached_count,
        "missing_count": max(0, universe_count - cached_count),
    }


def missing_kline_stocks(conn: sqlite3.Connection, trade_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            u.code, u.name, u.exchange, u.secid, u.board, u.listing_date,
            u.industry, u.region, u.official_source, u.raw_json
        FROM stock_universe u
        WHERE NOT EXISTS (
            SELECT 1
            FROM daily_kline k
            WHERE k.code = u.code AND k.trade_date = ?
        )
        ORDER BY u.code
        """,
        (trade_date,),
    ).fetchall()
    return [
        {
            "code": row[0],
            "name": row[1] or row[0],
            "exchange": row[2] or exchange_for_code(row[0]),
            "secid": row[3] or secid_for_code(row[0]),
            "board": row[4],
            "listing_date": row[5],
            "industry": row[6],
            "region": row[7],
            "official_source": row[8],
            "raw_json": row[9] or "{}",
        }
        for row in rows
    ]


def prefix_counts(stocks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stock in stocks:
        prefix = normalize_code(stock["code"])[:3]
        counts[prefix] = counts.get(prefix, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def popularity_count_for_date(conn: sqlite3.Connection, trade_date: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM popularity_top100 WHERE trade_date = ?", (trade_date,)).fetchone()
    return int(row[0] or 0)


def unfinished_run_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM sync_runs WHERE finished_at IS NULL").fetchone()
    return int(row[0] or 0)


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


def stock_rows_from_symbols_cached(conn: sqlite3.Connection, symbols: str) -> list[dict[str, Any]]:
    basic_rows = stock_rows_from_symbols(symbols)
    if not basic_rows:
        return []
    codes = [row["code"] for row in basic_rows]
    placeholders = ",".join("?" for _ in codes)
    cached_rows = conn.execute(
        f"""
        SELECT
            code, name, exchange, secid, board, listing_date,
            industry, region, official_source, raw_json
        FROM stock_universe
        WHERE code IN ({placeholders})
        """,
        tuple(codes),
    ).fetchall()
    cached_by_code = {
        row[0]: {
            "code": row[0],
            "name": row[1] or row[0],
            "exchange": row[2] or exchange_for_code(row[0]),
            "secid": row[3] or secid_for_code(row[0]),
            "board": row[4],
            "listing_date": row[5],
            "industry": row[6],
            "region": row[7],
            "official_source": row[8],
            "raw_json": row[9] or "{}",
        }
        for row in cached_rows
    }
    return [cached_by_code.get(row["code"], row) for row in basic_rows]


def stock_rows_from_seed_csv(csv_path: Path, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            code = normalize_code(raw.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                {
                    "code": code,
                    "name": str(raw.get("name") or "").strip() or code,
                    "exchange": exchange_for_code(code),
                    "secid": secid_for_code(code),
                    "raw_json": "{}",
                }
            )
            if limit and len(rows) >= limit:
                break
    return rows


def date_window(trade_date: str, mode: str, args: argparse.Namespace) -> tuple[str, str]:
    end_dt = datetime.strptime(trade_date, "%Y-%m-%d").date()
    days = args.initial_lookback_days if mode == "init" else args.incremental_lookback_days
    begin = (end_dt - timedelta(days=days)).strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")
    return begin, end


def parse_hhmm(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise SystemExit(f"Invalid --min-run-time {text!r}; expected HH:MM such as 15:30.") from exc
    return parsed.hour, parsed.minute


def same_day_min_run_time(args: argparse.Namespace) -> tuple[int, int]:
    if getattr(args, "min_run_hour", None) is not None and args.min_run_time == "15:30":
        return int(args.min_run_hour), 0
    return parse_hhmm(args.min_run_time)


def enforce_time_guard(args: argparse.Namespace) -> None:
    if args.allow_before_close:
        return
    current = now_china()
    min_hour, min_minute = same_day_min_run_time(args)
    min_time = current.replace(hour=min_hour, minute=min_minute, second=0, microsecond=0)
    if args.trade_date == current.date().isoformat() and current < min_time:
        raise SystemExit(
            f"Refusing same-day sync before {min_hour:02d}:{min_minute:02d} Asia/Shanghai. "
            "Run during the allowed same-day window or pass --allow-before-close for explicit testing."
        )


def check_database_writable(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            "SQLite database is not writable in the current execution context. "
            "Close stale sync processes or rerun with permissions that can write the database and WAL sidecar."
        ) from exc


def sync(args: argparse.Namespace) -> dict[str, Any]:
    run_started = time.time()
    enforce_time_guard(args)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        ensure_schema(conn)
        actual_mode = resolve_mode(conn, args.mode)
        args.mode = actual_mode
        run_id = start_run(conn, args)
        begin, end = date_window(args.trade_date, actual_mode, args)

        log(f"run: database={db_path}")
        log(f"run: mode={actual_mode} window={begin}-{end} adjust={args.adjust} trade_date={args.trade_date}")
        if args.seed_universe_only or args.universe_source == "seed":
            if not args.seed_kline_csv:
                raise SystemExit("--seed-universe-only/--universe-source seed requires --seed-kline-csv")
            stocks = stock_rows_from_seed_csv(Path(args.seed_kline_csv), args.limit)
            universe_source = "seed_csv_universe"
        elif args.symbols_only:
            if not args.symbols:
                raise SystemExit("--symbols-only requires --symbols")
            stocks = stock_rows_from_symbols_cached(conn, args.symbols)
            universe_source = "symbols_only"
        elif args.universe_source == "official" and not should_refresh_official_universe(conn, args):
            stocks = load_cached_official_universe(conn, args.limit)
            counts = cached_official_universe_counts(conn)
            universe_source = f"cached_official_universe:{counts}"
            log(f"official universe: using cached monthly universe counts={counts}")
        else:
            try:
                stocks, universe_source = fetch_stock_universe(
                    args.limit,
                    args.request_timeout,
                    args.prefer_akshare,
                    args.universe_source,
                )
            except Exception as exc:
                if args.universe_source == "official":
                    raise
                if args.seed_kline_csv:
                    stocks = stock_rows_from_seed_csv(Path(args.seed_kline_csv), args.limit)
                    universe_source = f"seed_csv_universe_fallback:{exc}"
                elif not args.symbols:
                    raise
                else:
                    stocks = stock_rows_from_symbols_cached(conn, args.symbols)
                    universe_source = f"symbols_fallback:{exc}"
        if args.symbols:
            wanted = {normalize_code(code) for code in args.symbols.split(",") if normalize_code(code)}
            stocks = [row for row in stocks if row["code"] in wanted]
        if not stocks:
            raise SystemExit("No A-share symbols found from the selected universe source.")
        upsert_stock_universe(conn, stocks)
        universe_pruned = 0
        if actual_mode == "init" and (
            universe_source.startswith("official_exchanges")
            or universe_source.startswith("cached_official_universe")
        ):
            universe_pruned = prune_stock_universe_to_codes(conn, {row["code"] for row in stocks})
        log(f"universe: stock_count={len(stocks)} source={universe_source}")
        if universe_pruned:
            log(f"universe: pruned_stale_rows={universe_pruned}")
        wanted_codes = {row["code"] for row in stocks}

        seed_rows_imported = 0
        if args.seed_kline_csv:
            seed_path = Path(args.seed_kline_csv)
            seed_rows_imported = load_seed_kline_csv(
                conn,
                seed_path,
                begin,
                end,
                wanted_codes,
                args.batch_rows,
            )
            log(f"seed csv: imported_rows={seed_rows_imported:,}")

        popularity_count = 0
        popularity_source = "skipped"
        popularity_error = ""
        if not args.skip_popularity:
            try:
                popularity_sources = parse_sources(
                    args.popularity_sources,
                    DEFAULT_POPULARITY_SOURCES,
                    {"eastmoney", "akshare"},
                )
                log(f"popularity sources: order={','.join(popularity_sources)}")
                popularity_rows, popularity_source = fetch_popularity_top100(
                    args.trade_date,
                    args.request_timeout,
                    args.popularity_limit,
                    popularity_sources,
                    args.request_attempts,
                    args.retry_base_sleep,
                    args.retry_max_sleep,
                    args.request_delay,
                    args.request_jitter,
                )
                popularity_count = replace_popularity_top100(conn, args.trade_date, popularity_rows)
                log(f"popularity: rows={popularity_count} source={popularity_source}")
            except Exception as exc:
                popularity_error = str(exc)
                replace_popularity_top100(conn, args.trade_date, [])
                log(f"popularity: unavailable error={popularity_error}")

        rows_upserted = 0
        failures: list[tuple[str, str, str]] = []
        pending: list[dict[str, Any]] = []
        completed = 0
        started = time.time()
        kline_sources = parse_sources(args.kline_sources, DEFAULT_KLINE_SOURCES, {"eastmoney", "tencent", "sina", "netease", "akshare"})
        source_breaker = SourceCircuitBreaker(args.source_fail_threshold)
        log(f"kline sources: order={','.join(kline_sources)}")
        log(
            "network policy: "
            f"workers={args.max_workers} attempts={args.request_attempts} "
            f"retry_base={args.retry_base_sleep}s retry_max={args.retry_max_sleep}s "
            f"request_delay={args.request_delay}s request_jitter={args.request_jitter}s "
            f"source_fail_threshold={args.source_fail_threshold}"
        )
        fetch_jobs = build_fetch_jobs(conn, stocks, begin, end, args, seed_rows_imported)
        log(f"network kline: scheduled_symbols={len(fetch_jobs)} workers={args.max_workers}")
        success_symbols = 0
        empty_symbols = 0
        error_symbols = 0
        source_counts: dict[str, int] = {source: 0 for source in kline_sources}
        source_elapsed: dict[str, float] = {source: 0.0 for source in kline_sources}
        fallback_symbols = 0
        last_progress = started
        last_error = ""
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {
                executor.submit(
                    fetch_kline_rows,
                    stock,
                    job_begin,
                    job_end,
                    args.adjust,
                    args.request_timeout,
                    kline_sources,
                    args.request_attempts,
                    args.retry_base_sleep,
                    args.retry_max_sleep,
                    args.request_delay,
                    args.request_jitter,
                    source_breaker,
                ): stock
                for stock, job_begin, job_end in fetch_jobs
            }
            for future in as_completed(futures):
                stock = futures[future]
                completed += 1
                try:
                    _code, rows, source, source_seconds = future.result()
                    if rows:
                        pending.extend(rows)
                        success_symbols += 1
                        source_counts[source] = source_counts.get(source, 0) + 1
                        source_elapsed[source] = source_elapsed.get(source, 0.0) + source_seconds
                        if kline_sources and source != kline_sources[0]:
                            fallback_symbols += 1
                    else:
                        empty_symbols += 1
                        failures.append((stock["code"], stock.get("name") or "", "empty kline response"))
                except Exception as exc:
                    error_symbols += 1
                    last_error = str(exc)
                    failures.append((stock["code"], stock.get("name") or "", str(exc)))
                if len(pending) >= args.batch_rows:
                    rows_upserted += upsert_kline_rows(conn, pending)
                    pending = []
                current = time.time()
                should_log = (
                    completed == len(fetch_jobs)
                    or completed % args.progress_every == 0
                    or current - last_progress >= args.progress_seconds
                )
                if should_log:
                    last_progress = current
                    elapsed = current - started
                    rate = completed / max(elapsed, 0.001)
                    message = (
                        "network kline: "
                        f"{completed}/{len(fetch_jobs)} "
                        f"ok={success_symbols} empty={empty_symbols} errors={error_symbols} "
                        f"sources={format_count_map(source_counts)} fallback={fallback_symbols} "
                        f"rows_pending_or_saved={rows_upserted + len(pending):,} "
                        f"rate={rate:.2f}/s eta={format_eta(completed, len(fetch_jobs), elapsed)} "
                        f"elapsed={format_duration(elapsed)} "
                        f"avg_source_latency={format_average_seconds(source_elapsed, source_counts)}"
                    )
                    disabled_sources = source_breaker.snapshot()["disabled"]
                    if disabled_sources:
                        message += f" disabled_sources={','.join(disabled_sources)}"
                    if last_error:
                        message += f" last_error={last_error[:120]}"
                    log(message)
        rows_upserted += upsert_kline_rows(conn, pending)
        add_failures(conn, run_id, failures)
        cutoff, retention_applied = apply_kline_retention(conn, actual_mode, args.retain_trading_days)
        latest_dates = latest_date_summary(conn)
        trade_days = distinct_trade_day_count(conn)
        notes = (
            f"retained_distinct_trade_days={trade_days}; "
            f"retention_applied={retention_applied}; "
            f"stock_universe_pruned={universe_pruned}; "
            f"seed_rows_imported={seed_rows_imported}; "
            f"popularity_count={popularity_count}; "
            f"popularity_source={popularity_source}; "
            f"max_workers={args.max_workers}; "
            f"request_attempts={args.request_attempts}; "
            f"retry_base_sleep={args.retry_base_sleep}; "
            f"retry_max_sleep={args.retry_max_sleep}; "
            f"request_delay={args.request_delay}; "
            f"request_jitter={args.request_jitter}; "
            f"source_fail_threshold={args.source_fail_threshold}; "
            f"kline_source_breaker={json.dumps(source_breaker.snapshot(), ensure_ascii=False)}; "
            f"kline_source_counts={format_count_map(source_counts)}; "
            f"kline_fallback_symbols={fallback_symbols}"
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
        log(
            "run: done "
            f"elapsed={format_duration(time.time() - run_started)} "
            f"rows_upserted={rows_upserted:,} failures={len(failures)} "
            f"retained_trade_days={trade_days}"
        )
        return {
            "database": str(db_path),
            "run_id": run_id,
            "mode": actual_mode,
            "stock_count": len(stocks),
            "stock_universe_pruned": universe_pruned,
            "rows_upserted": rows_upserted,
            "seed_rows_imported": seed_rows_imported,
            "network_fetch_symbols": len(fetch_jobs),
            "failures": len(failures),
            "max_workers": args.max_workers,
            "request_attempts": args.request_attempts,
            "request_delay": args.request_delay,
            "request_jitter": args.request_jitter,
            "source_fail_threshold": args.source_fail_threshold,
            "kline_source_breaker": source_breaker.snapshot(),
            "kline_source_counts": source_counts,
            "kline_fallback_symbols": fallback_symbols,
            "popularity_count": popularity_count,
            "popularity_source": popularity_source,
            "popularity_error": popularity_error,
            "retained_trade_days": trade_days,
            "retention_applied": retention_applied,
            "cutoff_trade_date": cutoff,
            "latest_dates": latest_dates,
        }


def repair_missing(args: argparse.Namespace) -> dict[str, Any]:
    run_started = time.time()
    enforce_time_guard(args)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        ensure_schema(conn)
        check_database_writable(conn)
        initial_coverage = kline_coverage_for_date(conn, args.trade_date)
        initial_missing = missing_kline_stocks(conn, args.trade_date)
        initial_popularity_count = popularity_count_for_date(conn, args.trade_date)
        open_runs = unfinished_run_count(conn)
        if initial_coverage["universe_count"] <= 0:
            raise SystemExit(
                "stock_universe is empty; run --mode init or --mode daily once before --repair-missing."
            )

    log(f"repair: database={db_path}")
    log(
        "repair: preflight "
        f"trade_date={args.trade_date} universe={initial_coverage['universe_count']} "
        f"cached={initial_coverage['cached_count']} missing={initial_coverage['missing_count']} "
        f"popularity_rows={initial_popularity_count} unfinished_runs={open_runs}"
    )
    if initial_missing:
        log(f"repair: missing_by_prefix={prefix_counts(initial_missing)}")
    if initial_popularity_count:
        log("repair: preserving existing popularity rows; K-line repair batches force --skip-popularity")
    if open_runs:
        log("repair: unfinished sync_runs exist; verify no stale Python sync process is still running")

    attempted: set[str] = set()
    batch_summaries: list[dict[str, Any]] = []
    total_rows_upserted = 0
    total_failures = 0
    batch_limit = args.repair_max_batches if args.repair_max_batches and args.repair_max_batches > 0 else None
    batch_number = 0

    while True:
        with closing(sqlite3.connect(db_path)) as conn:
            ensure_schema(conn)
            missing = missing_kline_stocks(conn, args.trade_date)
        candidates = [stock for stock in missing if stock["code"] not in attempted]
        if not candidates:
            break
        if batch_limit is not None and batch_number >= batch_limit:
            break
        batch_number += 1
        batch = candidates[: max(1, args.repair_chunk_size)]
        attempted.update(stock["code"] for stock in batch)
        batch_codes = ",".join(stock["code"] for stock in batch)
        batch_args = argparse.Namespace(**vars(args))
        batch_args.mode = "daily"
        batch_args.symbols = batch_codes
        batch_args.symbols_only = True
        batch_args.skip_popularity = True
        batch_args.limit = None
        batch_args.seed_kline_csv = None
        batch_args.seed_universe_only = False
        before_missing = len(missing)
        log(
            "repair batch: "
            f"{batch_number} size={len(batch)} first={batch[0]['code']} last={batch[-1]['code']} "
            f"remaining_before={before_missing}"
        )
        summary = sync(batch_args)
        with closing(sqlite3.connect(db_path)) as conn:
            after_coverage = kline_coverage_for_date(conn, args.trade_date)
        total_rows_upserted += int(summary["rows_upserted"])
        total_failures += int(summary["failures"])
        batch_summary = {
            "batch": batch_number,
            "stock_count": len(batch),
            "run_id": summary["run_id"],
            "rows_upserted": summary["rows_upserted"],
            "failures": summary["failures"],
            "missing_after": after_coverage["missing_count"],
            "kline_source_counts": summary["kline_source_counts"],
        }
        batch_summaries.append(batch_summary)
        log(
            "repair batch: "
            f"{batch_number} done run_id={summary['run_id']} "
            f"rows_upserted={summary['rows_upserted']:,} failures={summary['failures']} "
            f"missing_after={after_coverage['missing_count']}"
        )

    with closing(sqlite3.connect(db_path)) as conn:
        final_coverage = kline_coverage_for_date(conn, args.trade_date)
        final_missing = missing_kline_stocks(conn, args.trade_date)
        latest_dates = latest_date_summary(conn)
    log(
        "repair: done "
        f"elapsed={format_duration(time.time() - run_started)} "
        f"batches={len(batch_summaries)} total_rows_upserted={total_rows_upserted:,} "
        f"total_failures={total_failures} missing={final_coverage['missing_count']}"
    )
    if final_missing:
        log(f"repair: remaining_missing_by_prefix={prefix_counts(final_missing)}")
    return {
        "database": str(db_path),
        "mode": "repair-missing",
        "trade_date": args.trade_date,
        "initial_coverage": initial_coverage,
        "final_coverage": final_coverage,
        "initial_popularity_count": initial_popularity_count,
        "unfinished_runs": open_runs,
        "batches": batch_summaries,
        "total_rows_upserted": total_rows_upserted,
        "total_failures": total_failures,
        "remaining_missing_by_prefix": prefix_counts(final_missing),
        "remaining_missing_sample": [stock["code"] for stock in final_missing[:80]],
        "latest_dates": latest_dates,
    }


def self_test() -> None:
    breaker = SourceCircuitBreaker(3)
    assert breaker.allow("eastmoney") is True
    assert breaker.record_failure("eastmoney", TimeoutError("timeout")) is False
    assert breaker.record_failure("eastmoney", TimeoutError("timeout")) is False
    breaker.record_success("eastmoney")
    assert breaker.allow("eastmoney") is True
    assert breaker.snapshot()["failure_streaks"]["eastmoney"] == 0
    assert breaker.record_failure("eastmoney", TimeoutError("timeout")) is False
    assert breaker.record_failure("eastmoney", TimeoutError("timeout")) is False
    assert breaker.record_failure("eastmoney", TimeoutError("timeout")) is True
    assert breaker.allow("eastmoney") is False
    assert parse_sources("auto", DEFAULT_KLINE_SOURCES, {"eastmoney", "tencent", "sina", "netease", "akshare"}) == DEFAULT_KLINE_SOURCES
    assert value_by_alias({"date": "2026-06-05"}, ["date"], 0) == "2026-06-05"
    assert value_by_alias({"日期": "2026-06-05"}, ["date", "日期"], 0) == "2026-06-05"
    sample_csv = (
        "date,code,name,close,high,low,open,preclose,change,pct,volume,amount,turnover\n"
        "2026-06-05,'000001,Sample,12.34,12.50,12.00,12.10,12.00,0.34,2.83,1000,123400,1.20\n"
    )
    parsed = parse_netease_kline_csv({"code": "000001", "name": "Sample", "exchange": "SZ"}, sample_csv)
    assert len(parsed) == 1
    assert parsed[0]["trade_date"] == "2026-06-05"
    assert parsed[0]["source"] == "netease.chddata.adjust=none"
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
            cached_symbols = stock_rows_from_symbols_cached(conn, "000001,000004")
            assert cached_symbols[0]["name"] == "sample"
            assert cached_symbols[0]["raw_json"] == "{}"
            assert cached_symbols[1]["code"] == "000004"
            upsert_stock_universe(
                conn,
                [
                    {
                        "code": "999999",
                        "name": "stale",
                        "exchange": "SH",
                        "secid": "1.999999",
                        "raw_json": "{}",
                    }
                ],
            )
            assert prune_stock_universe_to_codes(conn, {"000001"}) == 1
            assert conn.execute("SELECT COUNT(*) FROM stock_universe WHERE code='999999'").fetchone()[0] == 0
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
            seed_path = Path(tmp) / "seed.csv"
            seed_path.write_text(
                "code,date,open,close,high,low,volume,amount,name\n"
                "000002,2026-06-03,1,2,3,1,100,200,sample2\n",
                encoding="utf-8",
            )
            assert load_seed_kline_csv(conn, seed_path, "20260601", "20260604", {"000002"}, 100) == 1
            assert upsert_kline_rows(
                conn,
                [
                    {
                        "code": "000001",
                        "trade_date": "2026-06-04",
                        "name": "sample",
                        "exchange": "SZ",
                        "open": 10,
                        "close": 10,
                        "high": 10,
                        "low": 10,
                        "volume": 100,
                        "amount": 1000,
                        "amplitude": None,
                        "pct_chg": None,
                        "change_amount": None,
                        "turnover": None,
                        "source": "self-test-current",
                        "fetched_at": now_china().strftime("%Y-%m-%d %H:%M:%S%z"),
                        "raw_line": "",
                    }
                ],
            ) == 1
            coverage = kline_coverage_for_date(conn, "2026-06-04")
            assert coverage["universe_count"] == 1
            assert coverage["cached_count"] == 1
            assert coverage["missing_count"] == 0
            assert missing_kline_stocks(conn, "2026-06-04") == []
            assert popularity_count_for_date(conn, "2026-06-04") == 0
            assert unfinished_run_count(conn) == 0
            jobs = build_fetch_jobs(
                conn,
                [{"code": "000001"}, {"code": "000002"}, {"code": "000003"}],
                "20250101",
                "20260604",
                argparse.Namespace(
                    trade_date="2026-06-04",
                    incremental_lookback_days=12,
                    retain_trading_days=126,
                ),
                seed_rows_imported=1,
            )
            job_by_code = {stock["code"]: job_begin for stock, job_begin, _job_end in jobs}
            assert "000001" not in job_by_code
            assert job_by_code["000002"] == "20260604"
            assert job_by_code["000003"] == "20250101"
            assert parse_hhmm("15:30") == (15, 30)
            assert same_day_min_run_time(argparse.Namespace(min_run_time="15:30", min_run_hour=None)) == (15, 30)
            assert same_day_min_run_time(argparse.Namespace(min_run_time="15:30", min_run_hour=17)) == (17, 0)
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch full-market A-share daily K-line data into SQLite and retain latest trade days."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--trade-date", default=now_china().date().isoformat())
    parser.add_argument("--mode", choices=["auto", "init", "daily"], default="auto")
    parser.add_argument("--adjust", choices=sorted(ADJUST_FLAGS), default="none")
    parser.add_argument("--kline-sources", default="auto", help="comma-separated K-line source order: auto, tencent,eastmoney,sina,netease,akshare")
    parser.add_argument("--retain-trading-days", type=int, default=126)
    parser.add_argument("--initial-lookback-days", type=int, default=240)
    parser.add_argument("--incremental-lookback-days", type=int, default=12)
    parser.add_argument("--min-run-time", default="15:30", help="earliest same-day run time in Asia/Shanghai, HH:MM")
    parser.add_argument("--min-run-hour", type=int, help="deprecated compatibility option; use --min-run-time")
    parser.add_argument("--allow-before-close", action="store_true")
    parser.add_argument("--request-timeout", type=int, default=15)
    parser.add_argument("--request-attempts", type=int, default=4, help="HTTP attempts per public endpoint request")
    parser.add_argument("--retry-base-sleep", type=float, default=0.8, help="base seconds for exponential retry backoff")
    parser.add_argument("--retry-max-sleep", type=float, default=10.0, help="maximum seconds for exponential retry backoff")
    parser.add_argument("--source-fail-threshold", type=int, default=3, help="disable a K-line source for the rest of the run after this many request failures; 0 disables source circuit breaking")
    parser.add_argument("--request-delay", type=float, default=0.12, help="minimum shared delay between public endpoint requests")
    parser.add_argument("--request-jitter", type=float, default=0.18, help="extra random shared delay between public endpoint requests")
    parser.add_argument("--prefer-akshare", action="store_true", help="try akshare.stock_zh_a_spot_em before built-in endpoints")
    parser.add_argument(
        "--universe-source",
        choices=["official", "auto", "market", "seed"],
        default="official",
        help="stock universe source; official uses SSE/SZSE/BSE official lists via AkShare wrappers",
    )
    parser.add_argument("--refresh-universe", action="store_true", help="force refresh official stock universe even outside the monthly refresh day")
    parser.add_argument("--official-universe-refresh-day", type=int, default=1, help="day of month to refresh official SSE/SZSE/BSE universe")
    parser.add_argument("--skip-popularity", action="store_true", help="skip current-day popularity top 100 sync")
    parser.add_argument("--popularity-limit", type=int, default=100, help="number of popularity rows to keep for the current trade date")
    parser.add_argument("--popularity-sources", default="auto", help="comma-separated popularity source order: auto, eastmoney,akshare")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--progress-every", type=int, default=200)
    parser.add_argument("--progress-seconds", type=int, default=15, help="print network progress at least this often")
    parser.add_argument("--limit", type=int, help="limit symbols for development runs")
    parser.add_argument("--symbols", help="comma-separated 6-digit stock codes")
    parser.add_argument("--symbols-only", action="store_true", help="use --symbols directly and skip full-market universe fetch")
    parser.add_argument("--seed-kline-csv", help="load existing kline CSV before fetching missing rows from the network")
    parser.add_argument("--seed-universe-only", action="store_true", help="derive the stock universe from --seed-kline-csv and skip online universe fetch")
    parser.add_argument("--repair-missing", action="store_true", help="repair only symbols missing K-line rows for --trade-date")
    parser.add_argument("--repair-chunk-size", type=int, default=150, help="symbols per --repair-missing batch")
    parser.add_argument("--repair-max-batches", type=int, default=0, help="maximum repair batches; 0 means all missing symbols")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return
    summary = repair_missing(args) if args.repair_missing else sync(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
