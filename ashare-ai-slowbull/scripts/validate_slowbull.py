"""Validate a prior ashare-ai-slowbull report against current Sina quotes.

The script reads the report's core table, fetches current quotes for the listed
codes, compares A/B/C/anchor groups, and writes a compact validation Markdown.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean


CN_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKET_CACHE_DB = ROOT / "runs" / "ashare-kline-sqlite-cache" / "ashare_kline.sqlite"
USER_AGENT = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}
INDEX_SYMBOLS = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sz399673": "创业板50",
}


@dataclass(frozen=True)
class Pick:
    grade: str
    rank: str
    name: str
    code: str
    direction: str


@dataclass(frozen=True)
class Quote:
    name: str
    price: float
    preclose: float
    pct: float
    amount_yi: float
    date: str
    time: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a slowbull report.")
    parser.add_argument("--report", required=True, help="Path to YYYY-MM-DD.md report.")
    parser.add_argument("--output", help="Optional output Markdown path.")
    parser.add_argument(
        "--market-cache-db",
        default=str(DEFAULT_MARKET_CACHE_DB),
        help="SQLite cache from ashare-kline-sqlite-cache; used before Sina quotes.",
    )
    parser.add_argument("--ignore-market-cache", action="store_true")
    return parser.parse_args()


def symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_cached_quotes(symbols: list[str], db_path: Path, *, ignore_cache: bool) -> dict[str, Quote]:
    if ignore_cache or not symbols or not db_path.exists():
        return {}
    codes = [item[-6:] for item in symbols if re.fullmatch(r"s[hz]\d{6}", item)]
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    with sqlite3.connect(str(db_path.resolve())) as conn:
        conn.row_factory = sqlite3.Row
        if not sqlite_table_exists(conn, "stock_universe"):
            return {}
        rows = conn.execute(
            f"""
            SELECT code, name, latest_price, previous_close, pct_chg, amount, updated_at
            FROM stock_universe
            WHERE code IN ({placeholders})
            """,
            codes,
        ).fetchall()
    quotes: dict[str, Quote] = {}
    for row in rows:
        code = str(row["code"])
        sym = symbol(code)
        price = float(row["latest_price"] or 0)
        preclose = float(row["previous_close"] or 0)
        pct = float(row["pct_chg"] or ((price / preclose - 1) * 100 if preclose else 0))
        updated = str(row["updated_at"] or "")
        date_part, _, time_part = updated.partition(" ")
        quotes[sym] = Quote(
            name=row["name"] or "",
            price=price,
            preclose=preclose,
            pct=pct,
            amount_yi=float(row["amount"] or 0) / 1e8,
            date=date_part,
            time=time_part,
        )
    return quotes


def fetch_sina(symbols: list[str]) -> dict[str, Quote]:
    if not symbols:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    request = urllib.request.Request(url, headers=USER_AGENT)
    text = urllib.request.urlopen(request, timeout=15).read().decode("gbk", errors="replace")
    quotes: dict[str, Quote] = {}
    for match in re.finditer(r'var hq_str_(s[hz]\d+)="(.*?)";', text):
        parts = match.group(2).split(",")
        if len(parts) < 32 or not parts[0]:
            continue
        preclose = float(parts[2])
        price = float(parts[3])
        quotes[match.group(1)] = Quote(
            name=parts[0],
            price=price,
            preclose=preclose,
            pct=(price / preclose - 1) * 100 if preclose else 0,
            amount_yi=float(parts[9]) / 1e8,
            date=parts[30],
            time=parts[31],
        )
    return quotes


def parse_report(path: Path) -> tuple[str, list[Pick]]:
    text = path.read_text(encoding="utf-8")
    trade_date_match = re.search(r"筛选日期：(\d{4}-\d{2}-\d{2})", text)
    trade_date = trade_date_match.group(1) if trade_date_match else path.stem
    picks: list[Pick] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| 档位 |"):
            in_table = True
            continue
        if in_table and (not line.startswith("|") or line.startswith("## ")):
            break
        if not in_table or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        grade, rank, name, code, direction = cells[:5]
        if grade in {"A", "B", "C", "剔除"} and re.fullmatch(r"\d{6}", code):
            picks.append(Pick(grade, rank, name, code, direction))
    return trade_date, picks


def fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


def group_summary(rows: list[tuple[Pick, Quote]]) -> list[str]:
    lines: list[str] = []
    for grade in ["A", "B", "C", "剔除"]:
        values = [quote.pct for pick, quote in rows if pick.grade == grade]
        if not values:
            continue
        lines.append(
            f"- {grade}档：平均 {fmt_pct(mean(values))}，胜率 "
            f"{sum(value > 0 for value in values)}/{len(values)}，"
            f"最高 {fmt_pct(max(values))}，最低 {fmt_pct(min(values))}"
        )
    return lines


def reflection(rows: list[tuple[Pick, Quote]], index_quotes: dict[str, Quote]) -> list[str]:
    by_grade: dict[str, list[float]] = defaultdict(list)
    for pick, quote in rows:
        by_grade[pick.grade].append(quote.pct)
    a_avg = mean(by_grade["A"]) if by_grade["A"] else 0
    b_avg = mean(by_grade["B"]) if by_grade["B"] else 0
    c_avg = mean(by_grade["C"]) if by_grade["C"] else 0
    anchor_avg = mean(by_grade["剔除"]) if by_grade["剔除"] else 0
    index_avg = mean(quote.pct for quote in index_quotes.values()) if index_quotes else 0
    lines = []
    lines.append(
        "A档有效性："
        + ("较好，A档平均表现优于B/C档。" if a_avg > b_avg and a_avg > c_avg else "一般，A档未明显拉开B/C档。")
    )
    lines.append(
        "相对指数："
        + ("跑赢主要指数均值。" if a_avg > index_avg else "未跑赢主要指数均值，需要复核主线选择。")
    )
    lines.append(
        "板块锚："
        + ("强于A档，说明资金仍偏龙头集中，二线扩散需更谨慎。" if anchor_avg > a_avg else "弱于或接近A档，二线筛选有一定扩散价值。")
    )
    lines.append("调权建议：复盘最大拖累所属细分；若同细分连续拖累，下次降低该细分或高位偏离票权重。")
    return [f"- {line}" for line in lines]


def build_report(
    source_date: str,
    rows: list[tuple[Pick, Quote]],
    index_quotes: dict[str, Quote],
    data_source: str,
) -> str:
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S +08:00")
    quote_times = sorted({f"{quote.date} {quote.time}" for _, quote in rows})
    lines = [
        "# A股AI硬件上游二线慢牛次日验证",
        "",
        f"源报告日期：{source_date}",
        f"验证时间：{now}",
        f"行情时间：{quote_times[0]} 至 {quote_times[-1]}" if quote_times else "行情时间：无",
        f"数据来源：{data_source}",
        "",
        "## 分组表现",
        *group_summary(rows),
        "",
        "## 个股表现",
        "| 源档位 | 源排名 | 标的 | 代码 | 方向/主线 | 最新价 | 涨跌幅 | 成交额 | 行情时间 |",
        "|---|---:|---|---:|---|---:|---:|---:|---|",
    ]
    for pick, quote in rows:
        lines.append(
            f"| {pick.grade} | {pick.rank} | {quote.name or pick.name} | {pick.code} | "
            f"{pick.direction} | {quote.price:.2f} | {fmt_pct(quote.pct)} | "
            f"{quote.amount_yi:.2f}亿 | {quote.date} {quote.time} |"
        )
    lines.extend(["", "## 指数参照"])
    for code, quote in index_quotes.items():
        lines.append(f"- {INDEX_SYMBOLS.get(code, code)}：{fmt_pct(quote.pct)}，{quote.date} {quote.time}")
    lines.extend(["", "## 复盘反思", *reflection(rows, index_quotes)])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    report_path = Path(args.report)
    source_date, picks = parse_report(report_path)
    market_cache_db = Path(args.market_cache_db)
    if not market_cache_db.is_absolute():
        market_cache_db = ROOT / market_cache_db
    pick_symbols = [symbol(pick.code) for pick in picks]
    quotes = fetch_cached_quotes(pick_symbols, market_cache_db, ignore_cache=args.ignore_market_cache)
    cached_quote_count = len(quotes)
    missing_symbols = [item for item in pick_symbols if item not in quotes]
    if missing_symbols:
        quotes.update(fetch_sina(missing_symbols))
    rows = [(pick, quotes[symbol(pick.code)]) for pick in picks if symbol(pick.code) in quotes]
    index_quotes = fetch_sina(list(INDEX_SYMBOLS))
    output = Path(args.output) if args.output else report_path.with_name(f"validation-{datetime.now(CN_TZ):%Y-%m-%d}.md")
    data_source = (
        "ashare-kline-sqlite-cache SQLite stock_universe; missing symbols and indexes fallback to Sina realtime quotes"
        if cached_quote_count
        else "Sina realtime quotes"
    )
    output.write_text(build_report(source_date, rows, index_quotes, data_source), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
