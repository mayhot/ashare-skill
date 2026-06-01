#!/usr/bin/env python3
"""Build an executable A-share super-shortline discipline report.

Two modes are supported:
1. --input plan.json: use already-normalized market/account/candidate data.
2. --symbols 300308,新易盛: fetch public K-line data and derive candidate fields.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


GREEN = "green"
YELLOW = "yellow"
RED = "red"
UNKNOWN = "unknown"

VALID_PATTERNS = {
    "breakthrough": "突破形态买",
    "sector_leader_ignition": "板块龙头点火",
    "airborne_add": "强势股空中加油",
    "pre_launch_dig": "启动前挖坑",
    "bull_volume": "牛市放量大阳",
    "slowbull_neighbor": "慢牛邻近启动",
    "continuous_strong": "强势股连续操作",
    "board_follow": "板块强势跟随",
    "platform_reentry": "强势平台再进",
    "hot_market_safe": "热市安全点",
    "super_pullback": "超级强势回调",
}

THEME_HINTS = {
    "300308": "CPO/光模块",
    "300502": "CPO/光模块",
    "000988": "光通信/激光设备",
    "002281": "光通信/CPO",
    "603986": "半导体/存储芯片",
    "688008": "半导体/存储接口",
    "300476": "PCB/AI服务器",
    "002384": "PCB/AI硬件",
    "601138": "AI服务器",
    "300750": "动力电池/储能",
}


@dataclass
class Gate:
    name: str
    state: str
    reason: str


def as_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        value = float(value)
        return default if math.isnan(value) else value
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_code(value: str) -> str | None:
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 6:
        return digits
    return None


def qq_symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def fetch_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tencent_daily(code: str, rows: int = 260) -> tuple[list[dict[str, Any]], str]:
    symbol = qq_symbol(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urllib.parse.urlencode(
        {"param": f"{symbol},day,,,{rows},qfq"}
    )
    payload = fetch_json(url)
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("msg") or "Tencent API error")
    stock = (payload.get("data") or {}).get(symbol) or {}
    raw_rows = stock.get("qfqday") or stock.get("day") or []
    parsed = []
    for row in raw_rows:
        if len(row) < 6:
            continue
        parsed.append(
            {
                "date": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
            }
        )
    if len(parsed) < 60:
        raise RuntimeError(f"K线不足60根：{len(parsed)}")
    return parsed, "Tencent qfqday"


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else math.nan


def detect_pattern(krows: list[dict[str, Any]]) -> tuple[str, str, str, float, str]:
    closes = [r["close"] for r in krows]
    highs = [r["high"] for r in krows]
    lows = [r["low"] for r in krows]
    vols = [r["volume"] for r in krows]
    last = krows[-1]
    close = closes[-1]
    prev_close = closes[-2]
    ma5 = mean(closes[-5:])
    ma10 = mean(closes[-10:])
    ma20 = mean(closes[-20:])
    ma60 = mean(closes[-60:])
    vol5 = mean(vols[-6:-1])
    vol_ratio = vols[-1] / vol5 if vol5 else math.nan
    prev20_high = max(highs[-21:-1])
    recent20_low = min(lows[-20:])
    recent_pct = pct(close, prev_close)
    dist20 = pct(close, ma20)
    trigger = "待确认"
    invalidation = f"跌破20日线{ma20:.2f}且次日无法修复"
    invalidation_distance = abs(pct(close, ma20))

    if close > prev20_high and vol_ratio >= 1.2:
        return (
            "breakthrough",
            f"收盘突破20日平台高点{prev20_high:.2f}，量比{vol_ratio:.2f}",
            f"跌回平台高点{prev20_high:.2f}且次日无法修复",
            abs(pct(close, prev20_high)),
            "confirmed",
        )
    if ma5 > ma10 > ma20 and close > ma20 and 0 <= dist20 <= 8:
        return (
            "continuous_strong",
            f"MA5/10/20多头，距20日线{dist20:.2f}%",
            invalidation,
            invalidation_distance,
            "healthy" if vol_ratio <= 1.8 else "mixed",
        )
    if ma20 > ma60 and -2 <= dist20 <= 3 and vol_ratio <= 1.2:
        return (
            "platform_reentry",
            f"靠近20日线缩量企稳，距20日线{dist20:.2f}%",
            invalidation,
            invalidation_distance,
            "mixed",
        )
    if recent_pct > 7 and vol_ratio >= 1.5:
        return (
            "bull_volume",
            f"单日涨幅{recent_pct:.2f}%且量比{vol_ratio:.2f}",
            f"跌破当日低点{last['low']:.2f}或放量回落",
            abs(pct(close, last["low"])),
            "strong",
        )
    return (
        "",
        f"未识别出系统内强买点；距20日线{dist20:.2f}%，20日低点{recent20_low:.2f}",
        invalidation,
        invalidation_distance,
        "unknown",
    )


def derive_candidate(symbol: str, name_map: dict[str, str], no_network: bool) -> dict[str, Any]:
    code = normalize_code(symbol) or name_map.get(symbol)
    if not code:
        return {
            "name": symbol,
            "code": "",
            "pattern": "",
            "trigger": "无法解析名称，请提供代码或name-map",
            "invalidation": "无法评估",
            "error": "无法解析名称，请提供代码或name-map",
        }
    candidate: dict[str, Any] = {"code": code, "name": symbol if not normalize_code(symbol) else code}
    if no_network:
        candidate.update({"pattern": "", "trigger": "网络禁用，未抓取公开K线", "invalidation": "无法评估", "error": "network disabled"})
        return candidate
    try:
        krows, source = fetch_tencent_daily(code)
        pattern, trigger, invalidation, invalidation_pct, volume_state = detect_pattern(krows)
        last = krows[-1]
        candidate.update(
            {
                "theme": THEME_HINTS.get(code, ""),
                "pattern": pattern,
                "trigger": trigger,
                "invalidation": invalidation,
                "invalidation_distance_pct": round(invalidation_pct, 2),
                "volume_state": volume_state,
                "liquidity": "normal",
                "latest_price": round(last["close"], 2),
                "kline_date": last["date"],
                "data_source": source,
            }
        )
    except Exception as exc:
        candidate.update({"pattern": "", "trigger": f"行情抓取失败：{exc}", "invalidation": "无法评估", "error": str(exc)})
    return candidate


def market_gate(data: dict[str, Any]) -> Gate:
    phase = normalize_text(data.get("market_phase"))
    money = normalize_text(data.get("money_effect"))
    month_pct = as_float(data.get("broad_index_month_pct"))

    if phase in {"falling", "weak", "down", "下跌", "弱势"} or money in {"weak", "none", "poor", "差"}:
        return Gate("市场闸门", RED, "大盘或赚钱效应偏弱")
    if month_pct is not None and month_pct < -5:
        return Gate("市场闸门", RED, "指数月度跌幅超过5%")
    if phase in {"range", "mixed", "震荡", "分化"} or money in {"mixed", "partial", "一般"}:
        return Gate("市场闸门", YELLOW, "市场分化，仅适合精选最强方向")
    if phase in {"rising", "strong", "up", "上涨", "强势"} or money in {"strong", "good", "强"}:
        return Gate("市场闸门", GREEN, "市场具备短线赚钱效应")
    if month_pct is not None and month_pct > 5:
        return Gate("市场闸门", GREEN, "指数月度涨幅超过5%")
    return Gate("市场闸门", UNKNOWN, "市场阶段信息不足")


def account_gate(data: dict[str, Any]) -> Gate:
    week = as_float(data.get("account_week_return"))
    month = as_float(data.get("account_month_return"))
    bad_week = bool(data.get("one_bad_week"))
    goal_reached = bool(data.get("goal_reached"))
    if bad_week or (week is not None and week <= -8):
        return Gate("账户闸门", RED, "周亏损接近8%或出现完整坏周")
    if goal_reached or (month is not None and month >= 30) or (week is not None and week >= 10):
        return Gate("账户闸门", YELLOW, "目标已接近或达成，应降速保护收益")
    if week is not None and month is not None and week > -3 and month > -5:
        return Gate("账户闸门", GREEN, "账户曲线未触发红线")
    return Gate("账户闸门", UNKNOWN, "账户收益和回撤信息不足")


def psychology_gate(data: dict[str, Any]) -> Gate:
    state = normalize_text(data.get("trader_state"))
    red_words = {"revenge", "panic", "fomo", "angry", "distracted", "fear", "焦虑", "恐慌", "报复", "上头"}
    yellow_words = {"excited", "hesitant", "tired", "兴奋", "犹豫", "疲惫"}
    green_words = {"calm", "prepared", "neutral", "冷静", "平静", "有计划"}
    if state in red_words:
        return Gate("心态闸门", RED, "心态不适合进攻")
    if state in yellow_words:
        return Gate("心态闸门", YELLOW, "心态需要降速确认")
    if state in green_words:
        return Gate("心态闸门", GREEN, "心态可执行纪律")
    return Gate("心态闸门", UNKNOWN, "心态信息不足")


def candidate_gate(candidate: dict[str, Any]) -> Gate:
    if candidate.get("error"):
        return Gate("候选闸门", RED, f"数据错误：{candidate['error']}")
    pattern = normalize_text(candidate.get("pattern"))
    invalidation = candidate.get("invalidation") or candidate.get("support_or_invalidation")
    late_chase = bool(candidate.get("late_chase"))
    invalidation_pct = as_float(candidate.get("invalidation_distance_pct"))
    if not pattern or pattern not in VALID_PATTERNS:
        return Gate("候选闸门", RED, "没有匹配系统内买点模式")
    if late_chase:
        return Gate("候选闸门", RED, "存在情绪化追高风险")
    if not invalidation:
        return Gate("候选闸门", YELLOW, "缺少明确失效条件")
    if invalidation_pct is not None and invalidation_pct > 8:
        return Gate("候选闸门", YELLOW, "失效距离偏远，盈亏比不足")
    return Gate("候选闸门", GREEN, "买点模式和失效条件基本清晰")


def score_candidate(data: dict[str, Any], candidate: dict[str, Any], gates: list[Gate]) -> tuple[int, str, str]:
    gate_map = {gate.name: gate.state for gate in gates}
    score = 0
    score += {"green": 15, "yellow": 8, "unknown": 5, "red": 0}[gate_map["市场闸门"]]
    score += {"green": 10, "yellow": 5, "unknown": 3, "red": 0}[gate_map["账户闸门"]]
    score += {"green": 10, "yellow": 5, "unknown": 3, "red": 0}[gate_map["心态闸门"]]
    score += {"green": 20, "yellow": 10, "unknown": 5, "red": 0}[gate_map["候选闸门"]]

    leading_themes = {normalize_text(x) for x in data.get("leading_themes", [])}
    theme = normalize_text(candidate.get("theme"))
    if theme and any(key in theme for key in leading_themes):
        score += 15
    elif theme:
        score += 8
    else:
        score += 3

    volume_state = normalize_text(candidate.get("volume_state"))
    if volume_state in {"confirmed", "healthy", "strong", "温和放量", "健康"}:
        score += 10
    elif volume_state in {"mixed", "unknown", ""}:
        score += 4

    liquidity = normalize_text(candidate.get("liquidity"))
    if liquidity in {"good", "normal", "高", "正常"}:
        score += 5
    elif liquidity in {"poor", "low", "差", "低"}:
        score -= 5

    if any(gate.state == RED for gate in gates[:3]):
        score = min(score, 69)

    if score >= 85:
        return score, "A", "条件满足才可纳入进攻计划"
    if score >= 70:
        return score, "B", "等待确认或轻仓试错"
    if score >= 55:
        return score, "C", "只观察，不主动交易"
    return score, "Reject", "剔除"


def size_ceiling(classification: str, gates: list[Gate]) -> str:
    if any(gate.state == RED for gate in gates):
        return "0%-5%"
    if classification == "A":
        return "20%-30%"
    if classification == "B":
        return "5%-15%"
    if classification == "C":
        return "0%-5%"
    return "0%"


def allowed_action(gates: list[Gate]) -> str:
    if any(gate.state == RED for gate in gates[:3]):
        return "停止新开进攻仓，只复盘或观察"
    if any(gate.state in {YELLOW, UNKNOWN} for gate in gates[:3]):
        return "轻仓试错或等待确认"
    return "允许按系统筛选候选股"


def render_report(data: dict[str, Any]) -> str:
    report_date = data.get("date") or date.today().isoformat()
    market = market_gate(data)
    account = account_gate(data)
    psychology = psychology_gate(data)
    base_gates = [market, account, psychology]

    lines = [
        "# 职业超级短线交易计划",
        f"日期：{report_date}",
        "结果类型：研究纪律清单，不构成个性化投资建议",
        "",
        "## 1. 执行闸门",
        "| 闸门 | 状态 | 原因 |",
        "|---|---|---|",
    ]
    for gate in base_gates:
        lines.append(f"| {gate.name} | {gate.state} | {gate.reason} |")

    lines.extend(
        [
            "",
            f"今日允许动作：{allowed_action(base_gates)}",
            "",
            "## 2. 目标与红线",
            f"- 本月收益：{data.get('account_month_return', '未知')}%",
            f"- 本周收益：{data.get('account_week_return', '未知')}%",
            f"- 指数月度位置：{data.get('broad_index_month_pct', '未知')}%",
            f"- 最大单票仓位：{data.get('max_single_position', '未知')}",
            "- 纪律：目标是约束节奏，不是收益承诺；红线优先于机会。",
            "",
            "## 3. 候选交易清单",
            "| 优先级 | 标的 | 代码 | K线日 | 主线 | 买点模式 | 评分 | 分档 | 触发条件 | 失效条件 | 数据状态 | 仓位上限 | 处理 |",
            "|---:|---|---|---|---|---|---:|---|---|---|---|---:|---|",
        ]
    )

    candidates = data.get("candidates") or []
    if not candidates:
        lines.append("| - | 无候选 | - | - | - | - | - | - | - | - | - | 0% | 信息不足，仅输出系统纪律 |")
    else:
        for idx, candidate in enumerate(candidates, start=1):
            cg = candidate_gate(candidate)
            gates = base_gates + [cg]
            score, classification, action = score_candidate(data, candidate, gates)
            pattern = VALID_PATTERNS.get(normalize_text(candidate.get("pattern")), candidate.get("pattern", ""))
            lines.append(
                "| {idx} | {name} | {code} | {date} | {theme} | {pattern} | {score} | {cls} | {trigger} | {invalid} | {data_status} | {size} | {action} |".format(
                    idx=idx,
                    name=candidate.get("name", ""),
                    code=candidate.get("code", ""),
                    date=candidate.get("kline_date", ""),
                    theme=candidate.get("theme", ""),
                    pattern=pattern or "无",
                    score=score,
                    cls=classification,
                    trigger=candidate.get("trigger", "待确认"),
                    invalid=candidate.get("invalidation") or candidate.get("support_or_invalidation", "未提供"),
                    data_status=candidate.get("error") or candidate.get("data_source", "manual"),
                    size=size_ceiling(classification, gates),
                    action=action,
                )
            )

    lines.extend(
        [
            "",
            "## 4. 下单前最后检查",
            "- 是否属于当前最强方向：未满足则不进攻。",
            "- 是否有系统内买点名称：没有则剔除。",
            "- 是否有明确失效位：没有则最多观察。",
            "- 是否因贪婪、恐惧、报复交易或怕踏空而下单：是则停止。",
            "- 若失败，是否仍能保持账户绿线：不能则降低仓位或放弃。",
            "",
            "## 5. 盘后复盘",
            "- 执行分类：按系统执行 / 买点错误 / 卖点错误 / 仓位错误 / 心态错误。",
            "- 明日第一规则：把今天最大的错误改写成一条可执行限制。",
            "",
            "免责声明：以上为交易纪律和研究框架，不构成个性化投资建议。",
        ]
    )
    return "\n".join(lines) + "\n"


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_name_map(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if p.suffix.lower() == ".json":
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): normalize_code(v) or str(v) for k, v in raw.items()}
    mapping = {}
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = normalize_code(row.get("code", ""))
            name = row.get("name", "")
            if code and name:
                mapping[name] = code
    return mapping


def build_from_symbols(args: argparse.Namespace) -> dict[str, Any]:
    data = load_json(args.account_json)
    for key in [
        "date",
        "market_phase",
        "money_effect",
        "broad_index_month_pct",
        "account_month_return",
        "account_week_return",
        "max_single_position",
        "trader_state",
    ]:
        value = getattr(args, key, None)
        if value not in (None, ""):
            data[key] = value
    if args.leading_themes:
        data["leading_themes"] = [x.strip() for x in args.leading_themes.split(",") if x.strip()]
    symbols = [x.strip() for x in args.symbols.split(",") if x.strip()]
    name_map = load_name_map(args.name_map)
    data["candidates"] = [derive_candidate(symbol, name_map, args.no_network) for symbol in symbols]
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build A-share super-shortline trading discipline report.")
    parser.add_argument("--input", help="Path to normalized input JSON.")
    parser.add_argument("--symbols", help="Comma-separated stock codes or names.")
    parser.add_argument("--account-json", help="Optional account/market JSON merged with --symbols mode.")
    parser.add_argument("--name-map", help="Optional JSON or CSV mapping stock name to code.")
    parser.add_argument("--output", help="Optional output markdown path.")
    parser.add_argument("--date", dest="date")
    parser.add_argument("--market-phase")
    parser.add_argument("--money-effect")
    parser.add_argument("--broad-index-month-pct", type=float)
    parser.add_argument("--leading-themes")
    parser.add_argument("--account-month-return", type=float)
    parser.add_argument("--account-week-return", type=float)
    parser.add_argument("--max-single-position")
    parser.add_argument("--trader-state")
    parser.add_argument("--no-network", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.symbols:
        data = build_from_symbols(args)
    elif args.input:
        data = load_json(args.input)
    else:
        raise SystemExit("Provide either --input or --symbols.")
    report = render_report(data)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
