import argparse
import json
import statistics
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUOTE_URL = "https://hq.sinajs.cn/list={symbols}"
INDEX_SYMBOLS = [
    ("上证指数", "sh000001"),
    ("深证成指", "sz399001"),
    ("创业板指", "sz399006"),
    ("科创50", "sh000688"),
]


def stock_symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def previous_day(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    req = urllib.request.Request(
        QUOTE_URL.format(symbols=",".join(symbols)),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    text = urllib.request.urlopen(req, timeout=30).read().decode("gbk", "replace")
    quotes = {}
    for line in [line for line in text.splitlines() if line.strip()]:
        symbol = line.split("hq_str_", 1)[1].split("=", 1)[0]
        data = line.split('="', 1)[1].rsplit('"', 1)[0]
        fields = data.split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        open_price = fnum(fields[1])
        preclose = fnum(fields[2])
        price = fnum(fields[3])
        high = fnum(fields[4])
        low = fnum(fields[5])
        quotes[symbol] = {
            "name": fields[0],
            "open": open_price,
            "preclose": preclose,
            "price": price,
            "high": high,
            "low": low,
            "pct": pct(price, preclose),
            "intraday_pct": pct(price, open_price),
            "amplitude_pct": ((high - low) / preclose * 100) if preclose else 0.0,
            "amount_yi": fnum(fields[9]) / 100000000,
            "date": fields[30],
            "time": fields[31],
        }
    return quotes


def fnum(value, default=0.0) -> float:
    try:
        return float(value) if value not in ("", None, "-") else default
    except Exception:
        return default


def pct(value: float, base: float) -> float:
    return (value / base - 1) * 100 if base else 0.0


def parse_report(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("|---") or line.startswith("| 档位"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) >= 14:
            tier, state, rank, name, code = parts[:5]
        elif len(parts) >= 13:
            tier, rank, name, code = parts[:4]
            state = tier
        else:
            continue
        if code.isdigit() and len(code) == 6:
            rows.append({"tier": tier, "state": state, "rank": rank, "name": name, "code": code})
    return rows


def summarize(items: list[dict]) -> dict:
    values = [item["pct"] for item in items if "pct" in item]
    if not values:
        return {"count": 0}
    best = max(items, key=lambda item: item["pct"])
    worst = min(items, key=lambda item: item["pct"])
    return {
        "count": len(values),
        "avg": statistics.mean(values),
        "median": statistics.median(values),
        "win": sum(value > 0 for value in values),
        "best": best,
        "worst": worst,
    }


def format_pct(value: float) -> str:
    return f"{value:+.2f}%"


def generate_report(source_date: str, quote_date: str, rows: list[dict], quotes: dict, index_quotes: dict) -> str:
    enriched = []
    for row in rows:
        symbol = stock_symbol(row["code"])
        quote = quotes.get(symbol)
        if quote:
            enriched.append({**row, **quote})
        else:
            enriched.append({**row, "error": "未取得行情"})

    by_tier = defaultdict(list)
    by_state = defaultdict(list)
    for row in enriched:
        if "pct" not in row:
            continue
        by_tier[row["tier"]].append(row)
        by_state[row["state"]].append(row)

    lines = []
    lines.append(f"# ashare-trend-buy 次日验证")
    lines.append("")
    lines.append(f"筛选日期：{source_date}")
    lines.append(f"验证行情日期：{quote_date}")
    if enriched and "date" in enriched[0]:
        lines.append(f"行情时间：{enriched[0]['date']} {enriched[0]['time']}")
    lines.append("")
    lines.append("## 指数背景")
    lines.append("")
    for label, symbol in INDEX_SYMBOLS:
        quote = index_quotes.get(symbol)
        if quote:
            lines.append(f"- {label}：{format_pct(quote['pct'])}")
    lines.append("")
    lines.append("## 分档表现")
    lines.append("")
    lines.append("| 分组 | 数量 | 平均涨跌 | 中位数 | 胜率 | 最强 | 最弱 |")
    lines.append("|---|---:|---:|---:|---:|---|---|")
    for key in ["A", "B", "C", "过热跟踪", "剔除"]:
        summary = summarize(by_tier.get(key, []))
        if not summary.get("count"):
            continue
        lines.append(
            f"| {key} | {summary['count']} | {format_pct(summary['avg'])} | {format_pct(summary['median'])} | "
            f"{summary['win']}/{summary['count']} | {summary['best']['name']} {format_pct(summary['best']['pct'])} | "
            f"{summary['worst']['name']} {format_pct(summary['worst']['pct'])} |"
        )
    lines.append("")
    lines.append("## 状态表现")
    lines.append("")
    lines.append("| 状态 | 数量 | 平均涨跌 | 中位数 | 胜率 |")
    lines.append("|---|---:|---:|---:|---:|")
    for key in sorted(by_state):
        summary = summarize(by_state[key])
        if summary.get("count"):
            lines.append(
                f"| {key} | {summary['count']} | {format_pct(summary['avg'])} | "
                f"{format_pct(summary['median'])} | {summary['win']}/{summary['count']} |"
            )
    lines.append("")
    lines.append("## 个股明细")
    lines.append("")
    lines.append("| 昨日档位 | 状态 | 标的 | 代码 | 今日涨跌 | 开盘至收盘 | 振幅 | 成交额 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for row in enriched:
        if "pct" not in row:
            lines.append(f"| {row['tier']} | {row['state']} | {row['name']} | {row['code']} | 未取得 |  |  |  |")
            continue
        lines.append(
            f"| {row['tier']} | {row['state']} | {row['name']} | {row['code']} | "
            f"{format_pct(row['pct'])} | {format_pct(row['intraday_pct'])} | "
            f"{row['amplitude_pct']:.2f}% | {row['amount_yi']:.2f}亿 |"
        )
    lines.append("")
    lines.append("## 复盘提示")
    lines.append("")
    lines.append("- A/B档若平均收益和胜率持续高于指数，说明主线和趋势结构有效；若只有少数极端值贡献，需降低集中度判断。")
    lines.append("- 过热跟踪若持续跑赢，不代表可以追高，而是说明应保留二次确认池；若次日冲高回落，应强化不追高纪律。")
    lines.append("- C档若常有单票爆发但整体胜率低，应保留为低确定性高弹性池，不应升为主观察池。")
    lines.append("- 剔除组若持续跑赢，需检查硬剔除是否误杀；若持续跑输，说明失效规则有效。")
    lines.append("")
    lines.append("以上为研究复盘，不构成个性化投资建议。")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an ashare-trend-buy shortlist against quote data.")
    parser.add_argument("--source-date", help="Screening date to validate, defaults to the day before --quote-date.")
    parser.add_argument("--quote-date", default=date.today().isoformat(), help="Quote date label for the validation report.")
    parser.add_argument("--report", help="Optional report path. Defaults to runs/ashare-trend-buy/SOURCE/SOURCE.md.")
    parser.add_argument("--output", help="Optional Markdown output path.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable enriched rows instead of Markdown.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_date = args.source_date or previous_day(args.quote_date)
    report_path = Path(args.report) if args.report else ROOT / "runs" / "ashare-trend-buy" / source_date / f"{source_date}.md"
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    rows = parse_report(report_path)
    symbols = [stock_symbol(row["code"]) for row in rows]
    quotes = fetch_quotes(symbols)
    index_quotes = fetch_quotes([symbol for _label, symbol in INDEX_SYMBOLS])
    if args.json:
        enriched = []
        for row in rows:
            enriched.append({**row, **quotes.get(stock_symbol(row["code"]), {})})
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return
    report = generate_report(source_date, args.quote_date, rows, quotes, index_quotes)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
