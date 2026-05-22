#!/usr/bin/env python3
"""Track returns for ashare-trend-buy and ashare-ai-slowbull recommendations."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SOURCE_SKILLS = ("ashare-trend-buy", "ashare-ai-slowbull")
HORIZONS = (5, 10, 20)


@dataclass
class Pick:
    source_skill: str
    run_date: str
    code: str
    name: str = ""
    grade: str = ""
    score: str = ""
    base_price: float | None = None
    base_price_date: str | None = None
    sector: str = ""
    source_file: str = ""
    notes: str = ""


@dataclass
class PriceBar:
    date: str
    close: float


@dataclass
class ReturnRow:
    pick: Pick
    as_of: str
    asof_price_date: str = ""
    asof_price: float | None = None
    return_pct: float | None = None
    elapsed_trading_days: int | None = None
    elapsed_calendar_days: int | None = None
    horizon_returns: dict[int, float | None] = field(default_factory=dict)
    horizon_dates: dict[int, str] = field(default_factory=dict)
    daily_rows: list[dict[str, str]] = field(default_factory=list)
    status: str = "ok"
    message: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate recommendation returns for A-share screening runs."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root containing runs/.")
    parser.add_argument("--as-of", default=dt.date.today().isoformat(), help="As-of date YYYY-MM-DD.")
    parser.add_argument("--start-date", help="Earliest source run date to process.")
    parser.add_argument("--end-date", help="Latest source run date to process. Defaults to --as-of.")
    parser.add_argument(
        "--source-skill",
        action="append",
        choices=SOURCE_SKILLS,
        help="Limit to one source skill. Can be passed more than once.",
    )
    parser.add_argument(
        "--include-grades",
        default="A,B",
        help="Comma-separated grades to track, default A,B. Use A,B,C to include C.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write CSV files.")
    parser.add_argument("--no-fetch", action="store_true", help="Do not call remote price APIs.")
    parser.add_argument("--sleep", type=float, default=0.05, help="Seconds to sleep between price fetches.")
    return parser.parse_args()


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def valid_date_dir(path: Path) -> bool:
    try:
        parse_date(path.name)
    except ValueError:
        return False
    return path.is_dir()


def normalize_code(value: str) -> str:
    match = re.search(r"(\d{6})", value or "")
    return match.group(1) if match else ""


def market_symbol(code: str) -> str:
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    if code.startswith(("00", "30", "20")):
        return f"sz{code}"
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"bj{code}"
    return f"sz{code}"


def to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def grade_allowed(value: str, allowed: set[str]) -> bool:
    text = (value or "").strip().upper()
    return text in allowed


def pick_from_row(
    *,
    source_skill: str,
    run_date: str,
    row: dict[str, str],
    code_key: str,
    grade_key: str,
    price_keys: Iterable[str],
    date_keys: Iterable[str],
    source_file: Path,
) -> Pick | None:
    code = normalize_code(row.get(code_key, ""))
    if not code:
        code = normalize_code(row.get("symbol", ""))
    if not code:
        return None
    base_price = None
    for key in price_keys:
        base_price = to_float(row.get(key))
        if base_price is not None:
            break
    base_date = None
    for key in date_keys:
        value = (row.get(key) or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            base_date = value
            break
    return Pick(
        source_skill=source_skill,
        run_date=run_date,
        code=code,
        name=(row.get("name") or "").strip(),
        grade=(row.get(grade_key) or "").strip(),
        score=(row.get("score") or "").strip(),
        base_price=base_price,
        base_price_date=base_date or run_date,
        sector=(row.get("sector") or row.get("direction") or "").strip(),
        source_file=str(source_file),
    )


def extract_from_structured_csv(source_dir: Path, source_skill: str, allowed: set[str]) -> list[Pick]:
    run_date = source_dir.name
    data_dir = source_dir / "data"
    picks: list[Pick] = []
    if source_skill == "ashare-trend-buy":
        path = data_dir / "scored-candidates.csv"
        if not path.exists():
            return []
        for row in read_csv_rows(path):
            if not grade_allowed(row.get("tier", ""), allowed):
                continue
            pick = pick_from_row(
                source_skill=source_skill,
                run_date=run_date,
                row=row,
                code_key="code",
                grade_key="tier",
                price_keys=("close", "trade"),
                date_keys=("date",),
                source_file=path,
            )
            if pick:
                picks.append(pick)
    elif source_skill == "ashare-ai-slowbull":
        path = data_dir / "candidates.csv"
        if not path.exists():
            return []
        for row in read_csv_rows(path):
            if not grade_allowed(row.get("grade", ""), allowed):
                continue
            pick = pick_from_row(
                source_skill=source_skill,
                run_date=run_date,
                row=row,
                code_key="code",
                grade_key="grade",
                price_keys=("trade", "close"),
                date_keys=("date",),
                source_file=path,
            )
            if pick:
                picks.append(pick)
    return dedupe_picks(picks)


def extract_from_markdown(source_dir: Path, source_skill: str, allowed: set[str]) -> list[Pick]:
    report_names = ("result.md", "report.md")
    report_path = next((source_dir / name for name in report_names if (source_dir / name).exists()), None)
    if not report_path:
        return []
    text = report_path.read_text(encoding="utf-8", errors="replace")
    picks: list[Pick] = []
    for line in text.splitlines():
        if "|" not in line or re.match(r"^\s*\|?\s*-{3,}", line):
            continue
        code = normalize_code(line)
        if not code:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        grade = next((cell.upper() for cell in cells if cell.strip().upper() in allowed), "")
        if not grade:
            continue
        code_index = next((i for i, cell in enumerate(cells) if normalize_code(cell) == code), -1)
        name = ""
        if code_index > 0:
            name = cells[code_index - 1].strip()
        score = next((cell for cell in reversed(cells) if re.fullmatch(r"\d{1,3}(\.\d+)?", cell)), "")
        picks.append(
            Pick(
                source_skill=source_skill,
                run_date=source_dir.name,
                code=code,
                name=name,
                grade=grade,
                score=score,
                base_price_date=source_dir.name,
                source_file=str(report_path),
                notes="extracted_from_markdown",
            )
        )
    return dedupe_picks(picks)


def dedupe_picks(picks: Iterable[Pick]) -> list[Pick]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Pick] = []
    for pick in picks:
        key = (pick.source_skill, pick.run_date, pick.code)
        if key in seen:
            continue
        seen.add(key)
        result.append(pick)
    return result


def extract_picks(source_dir: Path, source_skill: str, allowed: set[str]) -> list[Pick]:
    picks = extract_from_structured_csv(source_dir, source_skill, allowed)
    if picks:
        return picks
    return extract_from_markdown(source_dir, source_skill, allowed)


def tencent_url(code: str, start: str, end: str) -> str:
    symbol = market_symbol(code)
    param = f"{symbol},day,{start},{end},640,qfq"
    return f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"


def fetch_tencent_bars(code: str, start: str, end: str, cache_dir: Path | None = None) -> list[PriceBar]:
    cache_path = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{code}-{start}-{end}.json"
        if cache_path.exists():
            raw = cache_path.read_text(encoding="utf-8")
        else:
            raw = http_get(tencent_url(code, start, end))
            cache_path.write_text(raw, encoding="utf-8")
    else:
        raw = http_get(tencent_url(code, start, end))

    payload = json.loads(raw)
    symbol = market_symbol(code)
    node = payload.get("data", {}).get(symbol, {})
    rows = node.get("qfqday") or node.get("day") or []
    bars = []
    for row in rows:
        if len(row) < 3:
            continue
        close = to_float(row[2])
        if close is None:
            continue
        bars.append(PriceBar(date=str(row[0]), close=close))
    return bars


def http_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 recommendation-return-tracker",
            "Referer": "https://gu.qq.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def choose_asof_bar(bars: list[PriceBar], as_of: str) -> tuple[int, PriceBar] | None:
    candidates = [(idx, bar) for idx, bar in enumerate(bars) if bar.date <= as_of]
    return candidates[-1] if candidates else None


def nearest_base_index(bars: list[PriceBar], base_date: str) -> int | None:
    for idx, bar in enumerate(bars):
        if bar.date >= base_date:
            return idx
    return None


def pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new / old - 1.0) * 100.0


def calculate_return(
    pick: Pick,
    as_of: str,
    *,
    no_fetch: bool,
    cache_dir: Path,
    sleep_seconds: float,
) -> ReturnRow:
    row = ReturnRow(pick=pick, as_of=as_of)
    try:
        row.elapsed_calendar_days = (parse_date(as_of) - parse_date(pick.run_date)).days
    except ValueError:
        row.elapsed_calendar_days = None

    if pick.base_price is None:
        row.status = "missing_base_price"
        row.message = "No base price in source row; remote fetch required."

    if no_fetch:
        local_date = pick.base_price_date or pick.run_date
        if pick.base_price is not None and local_date == as_of:
            row.asof_price = pick.base_price
            row.asof_price_date = local_date
            row.return_pct = 0.0
            row.elapsed_trading_days = 0
            row.daily_rows = [
                daily_tracking_row(
                    pick=pick,
                    date=local_date,
                    close=pick.base_price,
                    base_price=pick.base_price,
                    elapsed_trading_days=0,
                    status="local_base_only",
                    message="Remote fetch disabled; as-of equals local base date.",
                )
            ]
            row.status = "local_base_only"
            row.message = "Remote fetch disabled; as-of equals local base date."
        elif pick.base_price is not None:
            row.status = "no_fetch_forward_unavailable"
            row.message = "Remote fetch disabled; forward return needs daily price data."
        else:
            row.status = "no_fetch_no_price"
            row.message = "Remote fetch disabled and no usable local price found."
        for horizon in HORIZONS:
            row.horizon_returns[horizon] = None
        return row

    start = pick.base_price_date or pick.run_date
    try:
        bars = fetch_tencent_bars(pick.code, start, as_of, cache_dir=cache_dir)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if pick.base_price is not None and start == as_of:
            row.asof_price = pick.base_price
            row.asof_price_date = start
            row.return_pct = 0.0
            row.elapsed_trading_days = 0
            row.status = "local_base_fallback"
            row.message = f"Price fetch failed on base/as-of date; used source base price. {exc}"
            row.daily_rows = [
                daily_tracking_row(
                    pick=pick,
                    date=start,
                    close=pick.base_price,
                    base_price=pick.base_price,
                    elapsed_trading_days=0,
                    status=row.status,
                    message=row.message,
                )
            ]
            for horizon in HORIZONS:
                row.horizon_returns[horizon] = None
            return row
        row.status = "price_fetch_failed"
        row.message = str(exc)
        return row

    if not bars:
        row.status = "no_price_bars"
        row.message = "Price API returned no daily bars."
        return row

    base_index = nearest_base_index(bars, start)
    asof_choice = choose_asof_bar(bars, as_of)
    if base_index is None or asof_choice is None:
        row.status = "price_date_unavailable"
        row.message = "No price bar found for base or as-of window."
        return row

    asof_index, asof_bar = asof_choice
    api_base = bars[base_index]
    base_price = pick.base_price if pick.base_price is not None else api_base.close
    row.asof_price = asof_bar.close
    row.asof_price_date = asof_bar.date
    row.return_pct = pct(asof_bar.close, base_price)
    row.elapsed_trading_days = max(0, asof_index - base_index)
    row.status = "ok"
    row.daily_rows = [
        daily_tracking_row(
            pick=pick,
            date=bar.date,
            close=bar.close,
            base_price=base_price,
            elapsed_trading_days=idx - base_index,
            status="ok",
            message="",
        )
        for idx, bar in enumerate(bars[base_index : asof_index + 1], start=base_index)
    ]

    for horizon in HORIZONS:
        target_index = base_index + horizon
        if target_index < len(bars) and bars[target_index].date <= as_of:
            target_bar = bars[target_index]
            row.horizon_returns[horizon] = pct(target_bar.close, base_price)
            row.horizon_dates[horizon] = target_bar.date
        else:
            row.horizon_returns[horizon] = None
    return row


def daily_tracking_row(
    *,
    pick: Pick,
    date: str,
    close: float,
    base_price: float,
    elapsed_trading_days: int,
    status: str,
    message: str,
) -> dict[str, str]:
    return {
        "date": date,
        "stock_name": pick.name,
        "code": pick.code,
        "daily_price": fmt_float(close),
        "return_since_buy_pct": fmt_float(pct(close, base_price)),
        "buy_date": pick.base_price_date or pick.run_date,
        "buy_price": fmt_float(base_price),
        "source_skill": pick.source_skill,
        "run_date": pick.run_date,
        "grade": pick.grade,
        "score": pick.score,
        "sector": pick.sector,
        "elapsed_trading_days": str(elapsed_trading_days),
        "status": status,
        "message": message,
        "source_file": pick.source_file,
    }


def fmt_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"


def return_row_to_dict(row: ReturnRow) -> dict[str, str]:
    pick = row.pick
    data = {
        "source_skill": pick.source_skill,
        "run_date": pick.run_date,
        "code": pick.code,
        "name": pick.name,
        "grade": pick.grade,
        "score": pick.score,
        "sector": pick.sector,
        "base_price_date": pick.base_price_date or pick.run_date,
        "base_price": fmt_float(pick.base_price),
        "as_of": row.as_of,
        "asof_price_date": row.asof_price_date,
        "asof_price": fmt_float(row.asof_price),
        "return_pct": fmt_float(row.return_pct),
        "elapsed_trading_days": "" if row.elapsed_trading_days is None else str(row.elapsed_trading_days),
        "elapsed_calendar_days": "" if row.elapsed_calendar_days is None else str(row.elapsed_calendar_days),
        "status": row.status,
        "message": row.message,
        "source_file": pick.source_file,
        "notes": pick.notes,
    }
    for horizon in HORIZONS:
        data[f"return_{horizon}d_pct"] = fmt_float(row.horizon_returns.get(horizon))
        data[f"return_{horizon}d_date"] = row.horizon_dates.get(horizon, "")
    return data


def daily_rows_to_dicts(rows: list[ReturnRow]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        if row.daily_rows:
            result.extend(row.daily_rows)
            continue
        pick = row.pick
        result.append(
            {
                "date": row.asof_price_date or row.as_of,
                "stock_name": pick.name,
                "code": pick.code,
                "daily_price": fmt_float(row.asof_price),
                "return_since_buy_pct": fmt_float(row.return_pct),
                "buy_date": pick.base_price_date or pick.run_date,
                "buy_price": fmt_float(pick.base_price),
                "source_skill": pick.source_skill,
                "run_date": pick.run_date,
                "grade": pick.grade,
                "score": pick.score,
                "sector": pick.sector,
                "elapsed_trading_days": ""
                if row.elapsed_trading_days is None
                else str(row.elapsed_trading_days),
                "status": row.status,
                "message": row.message,
                "source_file": pick.source_file,
            }
        )
    return result


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_values(rows: list[ReturnRow], values: list[tuple[ReturnRow, float]]) -> dict[str, str]:
    if not values:
        return {
            "available_count": "0",
            "total_count": str(len(rows)),
            "avg_return_pct": "",
            "median_return_pct": "",
            "win_rate_pct": "",
            "best_code": "",
            "best_name": "",
            "best_return_pct": "",
            "worst_code": "",
            "worst_name": "",
            "worst_return_pct": "",
        }
    nums = [value for _, value in values]
    best_row, best_value = max(values, key=lambda item: item[1])
    worst_row, worst_value = min(values, key=lambda item: item[1])
    wins = sum(1 for value in nums if value > 0)
    return {
        "available_count": str(len(values)),
        "total_count": str(len(rows)),
        "avg_return_pct": fmt_float(sum(nums) / len(nums)),
        "median_return_pct": fmt_float(statistics.median(nums)),
        "win_rate_pct": fmt_float(wins / len(nums) * 100.0),
        "best_code": best_row.pick.code,
        "best_name": best_row.pick.name,
        "best_return_pct": fmt_float(best_value),
        "worst_code": worst_row.pick.code,
        "worst_name": worst_row.pick.name,
        "worst_return_pct": fmt_float(worst_value),
    }


def summary_rows(rows: list[ReturnRow], as_of: str) -> list[dict[str, str]]:
    if not rows:
        return []
    first = rows[0]
    result: list[dict[str, str]] = []
    asof_values = [(row, row.return_pct) for row in rows if row.return_pct is not None]
    base = {
        "source_skill": first.pick.source_skill,
        "run_date": first.pick.run_date,
        "as_of": as_of,
    }
    result.append({"horizon": "asof", **base, **summarize_values(rows, asof_values)})
    for horizon in HORIZONS:
        values = [
            (row, row.horizon_returns[horizon])
            for row in rows
            if row.horizon_returns.get(horizon) is not None
        ]
        result.append({"horizon": f"{horizon}d", **base, **summarize_values(rows, values)})
    return result


def discover_source_dirs(
    repo_root: Path,
    skills: Iterable[str],
    start_date: str | None,
    end_date: str,
) -> list[tuple[str, Path]]:
    start = parse_date(start_date) if start_date else None
    end = parse_date(end_date)
    result: list[tuple[str, Path]] = []
    for skill in skills:
        root = repo_root / "runs" / skill
        if not root.exists():
            continue
        for path in sorted(root.iterdir()):
            if not valid_date_dir(path):
                continue
            if not has_source_artifact(path):
                continue
            run_date = parse_date(path.name)
            if start and run_date < start:
                continue
            if run_date > end:
                continue
            result.append((skill, path))
    return result


def has_source_artifact(path: Path) -> bool:
    return any(
        (path / relative).exists()
        for relative in (
            "result.md",
            "report.md",
            "data/scored-candidates.csv",
            "data/candidates.csv",
        )
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    as_of = args.as_of
    end_date = args.end_date or as_of
    allowed = {item.strip().upper() for item in args.include_grades.split(",") if item.strip()}
    skills = tuple(args.source_skill or SOURCE_SKILLS)
    source_dirs = discover_source_dirs(repo_root, skills, args.start_date, end_date)
    out_root = repo_root / "runs" / "ashare-recommendation-returns" / as_of
    cache_dir = out_root / "data" / "price-cache"

    all_rows: list[ReturnRow] = []
    all_summaries: list[dict[str, str]] = []
    processed = 0

    for skill, source_dir in source_dirs:
        picks = extract_picks(source_dir, skill, allowed)
        if not picks:
            print(f"[WARN] {skill}/{source_dir.name}: no matching recommendations found", file=sys.stderr)
            continue
        return_rows = [
            calculate_return(
                pick,
                as_of,
                no_fetch=args.no_fetch,
                cache_dir=cache_dir,
                sleep_seconds=args.sleep,
            )
            for pick in picks
        ]
        summaries = summary_rows(return_rows, as_of)
        all_rows.extend(return_rows)
        all_summaries.extend(summaries)
        processed += 1

        detail_dicts = daily_rows_to_dicts(return_rows)
        latest_dicts = [return_row_to_dict(row) for row in return_rows]
        if not args.dry_run:
            write_csv(source_dir / "data" / "recommendation-returns.csv", detail_dicts)
            write_csv(source_dir / "data" / "recommendation-returns-latest.csv", latest_dicts)
            write_csv(source_dir / "data" / "recommendation-returns-summary.csv", summaries)
        print(f"[OK] {skill}/{source_dir.name}: {len(return_rows)} rows")

    if not args.dry_run:
        detail_dicts = daily_rows_to_dicts(all_rows)
        latest_dicts = [return_row_to_dict(row) for row in all_rows]
        write_csv(out_root / "all-recommendation-returns.csv", detail_dicts)
        write_csv(out_root / "all-recommendation-returns-latest.csv", latest_dicts)
        write_csv(out_root / "all-recommendation-returns-summary.csv", all_summaries)

    print(
        json.dumps(
            {
                "as_of": as_of,
                "processed_date_folders": processed,
                "recommendation_rows": len(all_rows),
                "dry_run": args.dry_run,
                "no_fetch": args.no_fetch,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
