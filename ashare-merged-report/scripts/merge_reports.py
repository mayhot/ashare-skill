#!/usr/bin/env python3
"""Merge same-day ashare-ai-slowbull and ashare-trend-buy Markdown reports."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_REPORT_FILES = {
    "ashare-ai-slowbull": "report.md",
    "ashare-trend-buy": "result.md",
}


@dataclass
class SourceRecord:
    source: str
    code: str
    name: str
    grade: str
    score: float | None
    direction: str = ""
    trend: str = ""
    technical: str = ""
    buy_point: str = ""
    risk: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge same-day ashare-ai-slowbull and ashare-trend-buy reports."
    )
    parser.add_argument("--runs-dir", default="runs", help="Directory containing skill run outputs.")
    parser.add_argument("--date", help="Trading date to merge, in YYYY-MM-DD format.")
    parser.add_argument("--slow-dir", default="ashare-ai-slowbull", help="Slow-bull run subdirectory.")
    parser.add_argument("--trend-dir", default="ashare-trend-buy", help="Trend-buy run subdirectory.")
    parser.add_argument("--out-dir", default="ashare-merged-report", help="Output run subdirectory.")
    parser.add_argument(
        "--flat-output",
        action="store_true",
        help="Write legacy flat output as runs/<out-dir>/YYYY-MM-DD.md instead of a date folder.",
    )
    return parser.parse_args()


def report_filename(source_dir: str) -> str:
    return DEFAULT_REPORT_FILES.get(source_dir, "report.md")


def available_report_dates(runs_dir: Path, source_dir: str) -> set[str]:
    root = runs_dir / source_dir
    dates = {
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and DATE_DIR_RE.match(path.name)
        and (path / report_filename(source_dir)).exists()
    } if root.exists() else set()
    dates.update(
        path.stem
        for path in root.glob("*.md")
        if DATE_FILE_RE.match(path.name)
    )
    return dates


def common_dates(runs_dir: Path, slow_dir: str, trend_dir: str) -> list[str]:
    slow_dates = available_report_dates(runs_dir, slow_dir)
    trend_dates = available_report_dates(runs_dir, trend_dir)
    return sorted(slow_dates & trend_dates)


def choose_date(runs_dir: Path, slow_dir: str, trend_dir: str, requested: str | None) -> str:
    if requested:
        return requested
    dates = common_dates(runs_dir, slow_dir, trend_dir)
    if not dates:
        raise SystemExit(
            f"No common date-folder or legacy YYYY-MM-DD.md reports found in {runs_dir / slow_dir} and {runs_dir / trend_dir}."
        )
    return dates[-1]


def resolve_report_path(runs_dir: Path, source_dir: str, report_date: str) -> Path:
    new_path = runs_dir / source_dir / report_date / report_filename(source_dir)
    if new_path.exists():
        return new_path
    legacy_path = runs_dir / source_dir / f"{report_date}.md"
    if legacy_path.exists():
        return legacy_path
    raise SystemExit(
        f"Missing source report for {source_dir} on {report_date}: expected {new_path} or {legacy_path}"
    )


def read_report(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Missing source report: {path}")
    return path.read_text(encoding="utf-8")


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def extract_core_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    lines = markdown.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    in_core_section = False
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("## ") and "核心表格" in line:
            in_core_section = True
            index += 1
            continue
        if in_core_section and line.startswith("## "):
            break
        if in_core_section and line.startswith("|"):
            header = split_markdown_row(line)
            index += 1
            if index < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[index]):
                index += 1
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = split_markdown_row(lines[index])
                if len(row) >= len(header):
                    rows.append(row[: len(header)])
                index += 1
            tables.append((header, rows))
            continue
        index += 1
    return tables


def value(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key]:
            return row[key].strip()
    return ""


def parse_score(raw: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", raw or "")
    return float(match.group(0)) if match else None


def normalize_code(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits.zfill(6)[-6:] if digits else raw.strip()


def parse_records(markdown: str, source: str) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for header, rows in extract_core_tables(markdown):
        for raw_row in rows:
            row = dict(zip(header, raw_row))
            code = normalize_code(value(row, "代码"))
            name = value(row, "标的")
            if not code or not name:
                continue
            if source == "slow":
                records.append(
                    SourceRecord(
                        source=source,
                        code=code,
                        name=name,
                        grade=value(row, "档位"),
                        score=parse_score(value(row, "评分")),
                        direction=value(row, "所属方向"),
                        trend=value(row, "趋势状态", "涨幅状态"),
                        technical=value(row, "技术动量"),
                        buy_point=value(row, "趋势状态"),
                        risk=value(row, "证据等级"),
                    )
                )
            else:
                records.append(
                    SourceRecord(
                        source=source,
                        code=code,
                        name=name,
                        grade=value(row, "档位"),
                        score=parse_score(value(row, "评分")),
                        direction=value(row, "主线方向"),
                        trend=value(row, "技术状态"),
                        technical=value(row, "MACD/KDJ"),
                        buy_point=value(row, "买点观察"),
                        risk=value(row, "支撑/失效位"),
                    )
                )
    return records


def grade_value(grade: str) -> float:
    text = (grade or "").upper()
    if "剔除" in text or "不追" in text:
        return 0.0
    values: list[float] = []
    if "A" in text:
        values.append(3.0)
    if "B" in text:
        values.append(2.0)
    if "C" in text:
        values.append(1.0)
    return max(values) if values else 0.0


def format_score(score: float | None) -> str:
    if score is None:
        return "-"
    return str(int(score)) if score.is_integer() else f"{score:.1f}"


def merged_rank(slow: SourceRecord | None, trend: SourceRecord | None) -> float:
    grade_sum = grade_value(slow.grade if slow else "") + grade_value(trend.grade if trend else "")
    scores = [record.score for record in (slow, trend) if record and record.score is not None]
    score_avg = sum(scores) / len(scores) if scores else 0.0
    consensus_bonus = 8 if slow and trend else 0
    high_grade_bonus = 4 if grade_sum >= 5 else 0
    return score_avg + grade_sum * 6 + consensus_bonus + high_grade_bonus


def merged_level(slow: SourceRecord | None, trend: SourceRecord | None) -> str:
    sg = grade_value(slow.grade if slow else "")
    tg = grade_value(trend.grade if trend else "")
    if sg >= 3 and tg >= 3:
        return "双A共振"
    if sg >= 2 and tg >= 2:
        return "双策略重点"
    if sg >= 2 and tg < 2:
        return "主题强，等技术"
    if tg >= 2 and sg < 2:
        return "技术强，等主线验证"
    if sg >= 1 or tg >= 1:
        return "低优先跟踪"
    return "剔除/不追"


def action_text(slow: SourceRecord | None, trend: SourceRecord | None) -> str:
    if slow and trend:
        if grade_value(slow.grade) >= 2 and grade_value(trend.grade) >= 2:
            return trend.buy_point or slow.buy_point or "等缩量回踩不破后再转强"
        if grade_value(slow.grade) >= 2:
            return "保留产业链观察，等待右侧技术确认"
        if grade_value(trend.grade) >= 2:
            return "保留技术观察，补充主线与基本面验证"
    if slow:
        return "仅慢牛池入选，等待趋势买点确认"
    if trend:
        return trend.buy_point or "仅趋势池入选，需确认慢牛逻辑"
    return "-"


def brief_text(*parts: str, limit: int = 48) -> str:
    text = "；".join(part for part in parts if part and part != "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sorted_merged(
    slow_records: Iterable[SourceRecord], trend_records: Iterable[SourceRecord]
) -> list[tuple[str, SourceRecord | None, SourceRecord | None]]:
    slow_map = {record.code: record for record in slow_records}
    trend_map = {record.code: record for record in trend_records}
    codes = sorted(set(slow_map) | set(trend_map))
    merged = [(code, slow_map.get(code), trend_map.get(code)) for code in codes]
    merged.sort(key=lambda item: merged_rank(item[1], item[2]), reverse=True)
    return merged


def table_row(cells: Iterable[object]) -> str:
    escaped = [str(cell).replace("\n", " ").replace("|", "/") for cell in cells]
    return "| " + " | ".join(escaped) + " |"


def make_priority_table(items: list[tuple[str, SourceRecord | None, SourceRecord | None]]) -> list[str]:
    lines = [
        table_row(["优先级", "标的", "代码", "合并判断", "慢牛档/分", "趋势档/分", "方向/技术摘要", "观察动作"]),
        "|---:|---|---:|---|---|---|---|---|",
    ]
    for rank, (code, slow, trend) in enumerate(items, 1):
        name = (slow or trend).name if (slow or trend) else ""
        lines.append(
            table_row(
                [
                    rank,
                    name,
                    code,
                    merged_level(slow, trend),
                    f"{slow.grade}/{format_score(slow.score)}" if slow else "-",
                    f"{trend.grade}/{format_score(trend.score)}" if trend else "-",
                    brief_text(
                        slow.direction if slow else "",
                        trend.direction if trend else "",
                        trend.technical if trend else "",
                    ),
                    brief_text(action_text(slow, trend), limit=56),
                ]
            )
        )
    return lines


def make_full_table(items: list[tuple[str, SourceRecord | None, SourceRecord | None]]) -> list[str]:
    lines = [
        table_row(["标的", "代码", "慢牛档/分", "趋势档/分", "合并判断", "慢牛依据", "趋势依据", "风控/失效"]),
        "|---|---:|---|---|---|---|---|---|",
    ]
    for code, slow, trend in items:
        name = (slow or trend).name if (slow or trend) else ""
        lines.append(
            table_row(
                [
                    name,
                    code,
                    f"{slow.grade}/{format_score(slow.score)}" if slow else "-",
                    f"{trend.grade}/{format_score(trend.score)}" if trend else "-",
                    merged_level(slow, trend),
                    brief_text(slow.direction if slow else "", slow.trend if slow else ""),
                    brief_text(trend.trend if trend else "", trend.technical if trend else ""),
                    brief_text(slow.risk if slow else "", trend.risk if trend else ""),
                ]
            )
        )
    return lines


def names(items: Iterable[tuple[str, SourceRecord | None, SourceRecord | None]]) -> str:
    rendered = []
    for code, slow, trend in items:
        record = slow or trend
        if record:
            rendered.append(f"{record.name}({code})")
    return "、".join(rendered) if rendered else "无"


def build_report(
    merge_date: str,
    slow_path: Path,
    trend_path: Path,
    slow_records: list[SourceRecord],
    trend_records: list[SourceRecord],
) -> str:
    merged = sorted_merged(slow_records, trend_records)
    consensus = [
        item
        for item in merged
        if item[1] and item[2] and grade_value(item[1].grade) >= 2 and grade_value(item[2].grade) >= 2
    ]
    slow_wait = [
        item
        for item in merged
        if item[1] and grade_value(item[1].grade) >= 2 and (not item[2] or grade_value(item[2].grade) < 2)
    ]
    trend_wait = [
        item
        for item in merged
        if item[2] and grade_value(item[2].grade) >= 2 and (not item[1] or grade_value(item[1].grade) < 2)
    ]
    conflicts = [
        item
        for item in merged
        if item[1] and item[2] and abs(grade_value(item[1].grade) - grade_value(item[2].grade)) >= 2
    ]
    priority = consensus + slow_wait[:5] + trend_wait[:5]
    if not priority:
        priority = merged[:10]

    lines: list[str] = [
        f"# A股双策略合并报告",
        "",
        f"合并日期：{merge_date}",
        f"生成日期：{date.today().isoformat()}",
        "",
        "## 数据来源",
        "",
        f"- 慢牛报告：`{slow_path.as_posix()}`",
        f"- 右侧趋势报告：`{trend_path.as_posix()}`",
        "",
        "## 合并结论",
        "",
        f"- 双策略 A/B 共振：{len(consensus)} 只，优先看 `{names(consensus[:8])}`。",
        f"- 慢牛逻辑较强但右侧确认不足：{len(slow_wait)} 只，重点等待缩量回踩、平台突破或 MACD/KDJ 修复。",
        f"- 右侧技术较强但慢牛主线验证不足：{len(trend_wait)} 只，适合保留技术观察但降低仓位优先级。",
        f"- 明显分歧/降级：{len(conflicts)} 只，分歧票不直接升级，只保留复核条件。",
        "",
        "## 一、合并优先级名单",
        "",
        *make_priority_table(priority[:20]),
        "",
        "## 二、单策略强信号",
        "",
        f"- 慢牛强、趋势待确认：{names(slow_wait[:12])}。",
        f"- 趋势强、慢牛待验证：{names(trend_wait[:12])}。",
        "",
        "## 三、冲突与降级",
        "",
    ]
    if conflicts:
        for code, slow, trend in conflicts[:12]:
            record = slow or trend
            lines.append(
                f"- {record.name}({code})：慢牛 `{slow.grade if slow else '-'}`，趋势 `{trend.grade if trend else '-'}`；"
                f"处理方式：{action_text(slow, trend)}。"
            )
    else:
        lines.append("- 未发现 A/C 级别的显著冲突。")

    lines.extend(
        [
            "",
            "## 四、完整合并表",
            "",
            *make_full_table(merged),
            "",
            "## 五、执行规则与风险提示",
            "",
            "- 共振票也不追当日大阳线，优先等待缩量回踩 10/20 日线、平台不破或二次放量转强。",
            "- 单策略强信号必须补齐另一侧验证：慢牛票补技术确认，趋势票补主线与基本面确认。",
            "- 若核心龙头破位、板块成交退潮、或高位票放量滞涨，A/B 档均需快速降级。",
            "- 本报告仅为研究观察池合并，不构成个性化投资建议。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    merge_date = choose_date(runs_dir, args.slow_dir, args.trend_dir, args.date)
    slow_path = resolve_report_path(runs_dir, args.slow_dir, merge_date)
    trend_path = resolve_report_path(runs_dir, args.trend_dir, merge_date)

    slow_text = read_report(slow_path)
    trend_text = read_report(trend_path)
    slow_records = parse_records(slow_text, "slow")
    trend_records = parse_records(trend_text, "trend")
    if not slow_records:
        raise SystemExit(f"No core table records parsed from {slow_path}")
    if not trend_records:
        raise SystemExit(f"No core table records parsed from {trend_path}")

    out_dir = runs_dir / args.out_dir if args.flat_output else runs_dir / args.out_dir / merge_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{merge_date}.md" if args.flat_output else out_dir / "report.md"
    out_path.write_text(
        build_report(merge_date, slow_path, trend_path, slow_records, trend_records),
        encoding="utf-8",
    )
    print(out_path)


if __name__ == "__main__":
    main()
