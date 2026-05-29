"""Generate rolling backtest reports for ashare-ai-slowbull recommendations."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CN_TZ = timezone(timedelta(hours=8))
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
REPORT_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CODE_RE = re.compile(r"\b\d{6}\b")
GRADE_SET = {"A", "B", "C"}


@dataclass(frozen=True)
class Recommendation:
    folder_date: str
    report_date: str
    grade: str
    rank: str
    name: str
    code: str
    direction: str
    source_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate slowbull rolling backtest_report files.")
    parser.add_argument("--root", default="runs/ashare-ai-slowbull")
    parser.add_argument("--end-date", help="Exclude recommendation folders on or after this date.")
    parser.add_argument("--lookback", type=int, default=10)
    return parser.parse_args()


def fetch_text(url: str, timeout: int = 10, tries: int = 3) -> str:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=USER_AGENT)
            return urllib.request.urlopen(request, timeout=timeout).read().decode(
                "utf-8", errors="ignore"
            )
        except Exception as exc:  # pragma: no cover - network behavior varies.
            last = exc
            time.sleep(0.8 + attempt)
    raise RuntimeError(f"fetch failed: {url}") from last


def sina_symbol(code: str) -> str:
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


def fetch_sina_daily_k(code: str) -> list[dict[str, Any]]:
    symbol = sina_symbol(code)
    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/"
        "CN_MarketDataService.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen=180"
    )
    text = fetch_text(url, timeout=8, tries=3)
    match = re.search(r"=\((.*)\);?", text, re.S)
    data = json.loads(match.group(1)) if match else []
    return [
        {
            "date": item["day"],
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item["volume"]),
        }
        for item in data
    ]


def normalize_grade(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    grade = value[0].upper()
    return grade if grade in GRADE_SET else None


def parse_table_row(cells: list[str], folder_date: str, source_path: Path) -> Recommendation | None:
    if len(cells) < 4:
        return None

    # Current report format:
    # | 档位 | 排名 | 标的 | 代码 | 方向/主线 | ... |
    grade = normalize_grade(cells[0])
    if grade and CODE_RE.fullmatch(cells[3].strip()):
        return Recommendation(
            folder_date=folder_date,
            report_date=folder_date,
            grade=grade,
            rank=cells[1].strip(),
            name=cells[2].strip(),
            code=cells[3].strip(),
            direction=cells[4].strip() if len(cells) > 4 else "",
            source_path=source_path,
        )

    # Older report format:
    # | 排名 | 标的 | 代码 | 所属方向 | ... | 档位 |
    grade = normalize_grade(cells[-1])
    if grade and CODE_RE.fullmatch(cells[2].strip()):
        return Recommendation(
            folder_date=folder_date,
            report_date=folder_date,
            grade=grade,
            rank=cells[0].strip(),
            name=cells[1].strip(),
            code=cells[2].strip(),
            direction=cells[3].strip() if len(cells) > 3 else "",
            source_path=source_path,
        )

    return None


def parse_recommendations(report_path: Path) -> list[Recommendation]:
    folder_date = report_path.parent.name
    records: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()

    for line in report_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        record = parse_table_row(cells, folder_date, report_path)
        if not record:
            continue
        key = (record.folder_date, record.code)
        if key not in seen:
            seen.add(key)
            records.append(record)

    return records


def pct(current: float, base: float) -> float | None:
    if base == 0:
        return None
    return (current / base - 1) * 100


def calc_result(rec: Recommendation, klines: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [str(item["date"]) for item in klines]
    if rec.folder_date not in dates:
        return {
            **rec.__dict__,
            "calc_date": rec.folder_date,
            "reco_day_pct": None,
            "five_day_pct": None,
            "five_day_date": "",
            "to_date_pct": None,
            "latest_date": dates[-1] if dates else "",
            "rec_close": None,
            "latest_close": None,
            "status": "missing recommendation date kline",
        }

    idx = dates.index(rec.folder_date)
    rec_close = float(klines[idx]["close"])
    prev_close = float(klines[idx - 1]["close"]) if idx > 0 else None
    latest = klines[-1]
    five = klines[idx + 5] if idx + 5 < len(klines) else None

    return {
        **rec.__dict__,
        "calc_date": rec.folder_date,
        "reco_day_pct": pct(rec_close, prev_close) if prev_close else None,
        "five_day_pct": pct(float(five["close"]), rec_close) if five else None,
        "five_day_date": str(five["date"]) if five else "不足5个交易日",
        "to_date_pct": pct(float(latest["close"]), rec_close),
        "latest_date": str(latest["date"]),
        "rec_close": rec_close,
        "latest_close": float(latest["close"]),
        "status": "ok",
    }


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def avg(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return statistics.fmean(valid) if valid else None


def win_rate(values: list[float | None]) -> str:
    valid = [value for value in values if value is not None]
    if not valid:
        return "N/A"
    wins = sum(1 for value in valid if value > 0)
    return f"{wins}/{len(valid)} ({wins / len(valid) * 100:.1f}%)"


def grade_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = [("全部", results)]
    groups.extend((grade, [row for row in results if row["grade"] == grade]) for grade in sorted(GRADE_SET))
    for grade, rows_for_grade in groups:
        if not rows_for_grade:
            continue
        rows.append(
            {
                "grade": grade,
                "count": len(rows_for_grade),
                "reco_day_avg": avg([row["reco_day_pct"] for row in rows_for_grade]),
                "five_day_avg": avg([row["five_day_pct"] for row in rows_for_grade]),
                "to_date_avg": avg([row["to_date_pct"] for row in rows_for_grade]),
                "to_date_win_rate": win_rate([row["to_date_pct"] for row in rows_for_grade]),
            }
        )
    return rows


def markdown_table(results: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 日期 | 档位 | 排名 | 标的 | 代码 | 方向 | 推荐当日 | 5日 | 5日日期 | 至今 | 最新日期 | 状态 |",
        "|---|---|---:|---|---:|---|---:|---:|---|---:|---|---|",
    ]
    for row in results:
        lines.append(
            "| "
            f"{row['folder_date']} | {row['grade']} | {row['rank']} | {row['name']} | {row['code']} | "
            f"{row['direction']} | {fmt_pct(row['reco_day_pct'])} | {fmt_pct(row['five_day_pct'])} | "
            f"{row['five_day_date']} | {fmt_pct(row['to_date_pct'])} | {row['latest_date']} | {row['status']} |"
        )
    return lines


def summary_lines(results: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 档位 | 样本数 | 推荐当日均值 | 5日均值 | 至今均值 | 至今胜率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in grade_summary(results):
        lines.append(
            f"| {row['grade']} | {row['count']} | {fmt_pct(row['reco_day_avg'])} | "
            f"{fmt_pct(row['five_day_avg'])} | {fmt_pct(row['to_date_avg'])} | {row['to_date_win_rate']} |"
        )
    return lines


def write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    fieldnames = [
        "folder_date",
        "report_date",
        "calc_date",
        "grade",
        "rank",
        "name",
        "code",
        "direction",
        "reco_day_pct",
        "five_day_pct",
        "five_day_date",
        "to_date_pct",
        "latest_date",
        "rec_close",
        "latest_close",
        "status",
        "source_path",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        serializable = dict(row)
        serializable["source_path"] = str(serializable["source_path"])
        writer.writerow(serializable)
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")


def build_summary_report(selected_dates: list[str], results: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S +08:00")
    start_date, end_date = selected_dates[0], selected_dates[-1]
    lines = [
        f"# A股AI硬件慢牛滚动回测报告（{start_date} 至 {end_date}）",
        "",
        f"生成时间：{generated_at}  ",
        f"回测范围：最近 {len(selected_dates)} 个推荐日期  ",
        "数据口径：推荐当日涨跌幅=推荐日收盘价/前一交易日收盘价-1；5日涨跌幅=推荐后第5个交易日收盘价/推荐日收盘价-1；至今涨跌幅=最新日K收盘价/推荐日收盘价-1。",
        "",
        "## 分档表现",
        "",
        *summary_lines(results),
        "",
        "## 明细",
        "",
        *markdown_table(results),
        "",
    ]
    return "\n".join(lines)


def build_date_report(date: str, results: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S +08:00")
    lines = [
        f"# {date} 推荐标的回测报告",
        "",
        f"生成时间：{generated_at}  ",
        "数据口径同汇总回测报告；本文件用于复盘该日期目录下的推荐结果。",
        "",
        "## 分档表现",
        "",
        *summary_lines(results),
        "",
        "## 明细",
        "",
        *markdown_table(results),
        "",
    ]
    return "\n".join(lines)


def candidate_report_paths(root: Path, end_date: str | None, lookback: int) -> list[Path]:
    paths: list[Path] = []
    for child in root.iterdir() if root.exists() else []:
        if not child.is_dir() or not REPORT_DIR_RE.fullmatch(child.name):
            continue
        if end_date and child.name >= end_date:
            continue
        report = child / f"{child.name}.md"
        if report.exists():
            paths.append(report)
    return sorted(paths, key=lambda path: path.parent.name)[-lookback:]


def generate_backtest_reports(root: Path, end_date: str | None = None, lookback: int = 10) -> list[Path]:
    report_paths = candidate_report_paths(root, end_date=end_date, lookback=lookback)
    if not report_paths:
        return []

    recommendations: list[Recommendation] = []
    for path in report_paths:
        recommendations.extend(parse_recommendations(path))
    if not recommendations:
        return []

    kline_cache: dict[str, list[dict[str, Any]]] = {}
    results: list[dict[str, Any]] = []
    for rec in recommendations:
        if rec.code not in kline_cache:
            kline_cache[rec.code] = fetch_sina_daily_k(rec.code)
        results.append(calc_result(rec, kline_cache[rec.code]))

    results.sort(key=lambda row: (row["folder_date"], row["grade"], int(row["rank"]) if str(row["rank"]).isdigit() else 999))
    selected_dates = sorted({path.parent.name for path in report_paths})
    start_date, finish_date = selected_dates[0], selected_dates[-1]

    generated: list[Path] = []
    summary_dir = root / "backtest_reports"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_md = summary_dir / f"{start_date}_{finish_date}_slowbull_backtest_report.md"
    summary_csv = summary_dir / f"{start_date}_{finish_date}_slowbull_backtest_report.csv"
    summary_md.write_text(build_summary_report(selected_dates, results), encoding="utf-8")
    write_csv(summary_csv, results)
    generated.extend([summary_md, summary_csv])

    for date in selected_dates:
        date_results = [row for row in results if row["folder_date"] == date]
        date_path = root / date / f"{date}-backtest_report.md"
        date_path.write_text(build_date_report(date, date_results), encoding="utf-8")
        generated.append(date_path)

    return generated


def main() -> None:
    args = parse_args()
    for path in generate_backtest_reports(Path(args.root), end_date=args.end_date, lookback=args.lookback):
        print(path)


if __name__ == "__main__":
    main()
