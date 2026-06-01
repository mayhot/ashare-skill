#!/usr/bin/env python3
"""Daily A-share position health check from holdings and optional price CSVs."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


ALIASES = {
    "code": ["code", "symbol", "证券代码", "股票代码", "代码"],
    "name": ["name", "证券名称", "股票名称", "名称", "标的"],
    "quantity": ["quantity", "qty", "shares", "持仓数量", "数量", "可用数量"],
    "cost_price": ["cost_price", "cost", "成本价", "持仓成本", "买入成本", "成本"],
    "latest_price": ["latest_price", "price", "last", "close", "现价", "最新价", "收盘价"],
    "market_value": ["market_value", "value", "市值", "持仓市值", "股票市值"],
    "portfolio_weight": ["portfolio_weight", "weight", "仓位", "持仓占比", "组合占比"],
    "today_pct": ["today_pct", "pct_chg", "涨跌幅", "今日涨跌幅", "当日涨跌幅"],
    "unrealized_pct": ["unrealized_pct", "pnl_pct", "浮盈浮亏", "收益率", "盈亏比例"],
    "hold_days": ["hold_days", "持仓天数", "持有天数"],
    "industry": ["industry", "sector", "行业", "板块"],
    "note": ["note", "备注", "逻辑", "持仓理由"],
    "date": ["date", "交易日期", "日期"],
    "open": ["open", "开盘", "开盘价"],
    "high": ["high", "最高", "最高价"],
    "low": ["low", "最低", "最低价"],
    "close": ["close", "收盘", "收盘价", "最新价"],
    "volume": ["volume", "vol", "成交量"],
    "event": ["event", "事件", "事项", "公告", "风险事件"],
    "impact": ["impact", "severity", "risk_level", "影响", "级别", "风险级别"],
}


def norm_key(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "gbk", "utf-16"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeError:
            continue
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def pick(row: dict[str, Any], field: str) -> Any:
    keys = {norm_key(k): k for k in row.keys()}
    for alias in ALIASES[field]:
        key = keys.get(norm_key(alias))
        if key is not None:
            return row.get(key)
    return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text in {"-", "--", "nan", "None"}:
        return None
    multiplier = 0.01 if text.endswith("%") else 1.0
    text = text.rstrip("%")
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def pct(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "-"
    return f"{value * 100:.2f}%"


def money(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "-"
    if abs(value) >= 100000000:
        return f"{value / 100000000:.2f}亿"
    if abs(value) >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.2f}"


def ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(values[-window - 1 : -1], values[-window:]):
        diff = cur - prev
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def macd(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 35:
        return None, None, None
    diffs = [a - b for a, b in zip(ema(values, 12), ema(values, 26))]
    dea = ema(diffs, 9)
    return diffs[-1], dea[-1], (diffs[-1] - dea[-1]) * 2


def kdj(rows: list[dict[str, Any]], window: int = 9) -> tuple[float | None, float | None, float | None]:
    if len(rows) < window:
        return None, None, None
    k = 50.0
    d = 50.0
    for idx in range(window - 1, len(rows)):
        part = rows[max(0, idx - window + 1) : idx + 1]
        highs = [r["high"] for r in part if r.get("high") is not None]
        lows = [r["low"] for r in part if r.get("low") is not None]
        close = rows[idx].get("close")
        if not highs or not lows or close is None:
            continue
        low_n = min(lows)
        high_n = max(highs)
        rsv = 50.0 if high_n == low_n else (close - low_n) / (high_n - low_n) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
    return k, d, 3 * k - 2 * d


def calc_indicators(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [r["close"] for r in rows if r.get("close") is not None]
    vols = [r["volume"] for r in rows if r.get("volume") is not None]
    if not closes:
        return {}
    latest = closes[-1]
    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60)
    vol_ratio = None
    if len(vols) >= 21 and sum(vols[-21:-1]) > 0:
        vol_ratio = vols[-1] / (sum(vols[-21:-1]) / 20)
    high20 = max((r.get("high") or r.get("close") for r in rows[-20:]), default=None)
    low20 = min((r.get("low") or r.get("close") for r in rows[-20:]), default=None)
    drawdown20 = (latest / high20 - 1) if high20 else None
    ret20 = (latest / closes[-20] - 1) if len(closes) >= 20 and closes[-20] else None
    ret60 = (latest / closes[-60] - 1) if len(closes) >= 60 and closes[-60] else None
    dif, dea, hist = macd(closes)
    k, d, j = kdj(rows)
    atr14_pct = calc_atr_pct(rows, 14)
    support_candidates = [x for x in (ma20, ma60, low20) if x and x < latest]
    support = max(support_candidates) if support_candidates else low20
    invalidation = support * 0.98 if support else None
    return {
        "close": latest,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_dev": latest / ma20 - 1 if ma20 else None,
        "vol_ratio": vol_ratio,
        "high20": high20,
        "low20": low20,
        "drawdown20": drawdown20,
        "ret20": ret20,
        "ret60": ret60,
        "rsi14": rsi(closes),
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
        "kdj_k": k,
        "kdj_d": d,
        "kdj_j": j,
        "atr14_pct": atr14_pct,
        "support": support,
        "invalidation": invalidation,
    }


def calc_atr_pct(rows: list[dict[str, Any]], window: int = 14) -> float | None:
    if len(rows) <= window:
        return None
    true_ranges: list[float] = []
    prev_close = rows[-window - 1].get("close")
    for row in rows[-window:]:
        high = row.get("high")
        low = row.get("low")
        close = row.get("close")
        if high is None or low is None or close is None:
            return None
        if prev_close is None:
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(true_range)
        prev_close = close
    latest = rows[-1].get("close")
    if not latest:
        return None
    return sum(true_ranges) / len(true_ranges) / latest


@dataclass
class Holding:
    code: str
    name: str
    quantity: float | None
    cost_price: float | None
    latest_price: float | None
    market_value: float | None
    weight: float | None
    today_pct: float | None
    unrealized_pct: float | None
    hold_days: float | None
    industry: str
    note: str
    indicators: dict[str, Any]


def load_holdings(path: Path) -> list[Holding]:
    rows = read_csv(path)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        quantity = to_float(pick(row, "quantity"))
        cost_price = to_float(pick(row, "cost_price"))
        latest_price = to_float(pick(row, "latest_price"))
        market_value = to_float(pick(row, "market_value"))
        if market_value is None and quantity is not None and latest_price is not None:
            market_value = quantity * latest_price
        unrealized_pct = to_float(pick(row, "unrealized_pct"))
        if unrealized_pct is None and cost_price and latest_price:
            unrealized_pct = latest_price / cost_price - 1
        parsed.append(
            {
                "code": str(pick(row, "code") or "").strip(),
                "name": str(pick(row, "name") or "").strip(),
                "quantity": quantity,
                "cost_price": cost_price,
                "latest_price": latest_price,
                "market_value": market_value,
                "weight": to_float(pick(row, "portfolio_weight")),
                "today_pct": to_float(pick(row, "today_pct")),
                "unrealized_pct": unrealized_pct,
                "hold_days": to_float(pick(row, "hold_days")),
                "industry": str(pick(row, "industry") or "").strip(),
                "note": str(pick(row, "note") or "").strip(),
            }
        )
    total = sum(x["market_value"] or 0 for x in parsed)
    holdings: list[Holding] = []
    for item in parsed:
        weight = item["weight"]
        if weight is None and total > 0 and item["market_value"] is not None:
            weight = item["market_value"] / total
        item = {**item, "weight": weight}
        holdings.append(Holding(**item, indicators={}))
    return [h for h in holdings if h.code or h.name]


def load_prices(path: Path | None, run_date: str | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_csv(path):
        code = str(pick(row, "code") or "").strip()
        row_date = str(pick(row, "date") or "").strip()
        if not code or not row_date:
            continue
        if run_date and row_date > run_date:
            continue
        close = to_float(pick(row, "close"))
        if close is None:
            continue
        grouped[code].append(
            {
                "date": row_date,
                "open": to_float(pick(row, "open")),
                "high": to_float(pick(row, "high")),
                "low": to_float(pick(row, "low")),
                "close": close,
                "volume": to_float(pick(row, "volume")),
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda x: x["date"])
    return grouped


def load_sector_prices(path: Path | None, run_date: str | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_csv(path):
        industry = str(pick(row, "industry") or "").strip()
        row_date = str(pick(row, "date") or "").strip()
        close = to_float(pick(row, "close"))
        if not industry or not row_date or close is None:
            continue
        if run_date and row_date > run_date:
            continue
        grouped[industry].append(
            {
                "date": row_date,
                "open": to_float(pick(row, "open")),
                "high": to_float(pick(row, "high")),
                "low": to_float(pick(row, "low")),
                "close": close,
                "volume": to_float(pick(row, "volume")),
            }
        )
    for rows in grouped.values():
        rows.sort(key=lambda x: x["date"])
    return grouped


def load_events(path: Path | None, run_date: str | None) -> dict[str, list[dict[str, str]]]:
    if path is None:
        return {}
    events: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(path):
        code = str(pick(row, "code") or "").strip()
        event_date = str(pick(row, "date") or "").strip()
        event = str(pick(row, "event") or "").strip()
        impact = str(pick(row, "impact") or "").strip()
        if not code or not event:
            continue
        if run_date and event_date and event_date > run_date:
            events[code].append({"date": event_date, "event": event, "impact": impact or "upcoming"})
        else:
            events[code].append({"date": event_date, "event": event, "impact": impact})
    return events


def first_indicator(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    for rows in grouped.values():
        if rows:
            return calc_indicators(rows)
    return {}


def enrich_context(
    holdings: list[Holding],
    benchmark_ind: dict[str, Any],
    sector_rows: dict[str, list[dict[str, Any]]],
    events: dict[str, list[dict[str, str]]],
) -> None:
    sector_ind = {name: calc_indicators(rows) for name, rows in sector_rows.items()}
    bench_ret20 = benchmark_ind.get("ret20")
    bench_ret60 = benchmark_ind.get("ret60")
    bench_close = benchmark_ind.get("close")
    bench_ma20 = benchmark_ind.get("ma20")
    for holding in holdings:
        ind = holding.indicators
        if not ind:
            continue
        if bench_ret20 is not None and ind.get("ret20") is not None:
            ind["rs20"] = ind["ret20"] - bench_ret20
        if bench_ret60 is not None and ind.get("ret60") is not None:
            ind["rs60"] = ind["ret60"] - bench_ret60
        if bench_close and bench_ma20:
            ind["market_state"] = "强" if bench_close >= bench_ma20 else "弱"
        sector = sector_ind.get(holding.industry)
        if sector:
            ind["sector_ret20"] = sector.get("ret20")
            ind["sector_ret60"] = sector.get("ret60")
            if sector.get("ret20") is not None and bench_ret20 is not None:
                ind["sector_rs20"] = sector["ret20"] - bench_ret20
            if sector.get("close") and sector.get("ma20"):
                ind["sector_state"] = "强" if sector["close"] >= sector["ma20"] else "弱"
        if events.get(holding.code):
            joined = "；".join(
                f"{item.get('date') or '未知日期'} {item.get('event')}({item.get('impact') or '未分级'})"
                for item in events[holding.code][:3]
            )
            ind["event_risk"] = joined
            ind["event_risk_level"] = event_level(events[holding.code])


def event_level(items: list[dict[str, str]]) -> str:
    text = " ".join(f"{x.get('event', '')} {x.get('impact', '')}" for x in items)
    severe_words = ["高", "重大", "严重", "减持", "解禁", "亏损", "问询", "处罚", "退市", "立案"]
    medium_words = ["中", "业绩预告", "股东大会", "财报", "限售", "波动"]
    if any(word in text for word in severe_words):
        return "高"
    if any(word in text for word in medium_words):
        return "中"
    return "低"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_holding(h: Holding) -> tuple[int, str, int, str, str]:
    ind = h.indicators
    price = h.latest_price or ind.get("close")
    score = 0.0
    reasons: list[str] = []

    trend = 10.0
    if price and ind:
        trend = 4.0
        if ind.get("ma5") and price >= ind["ma5"]:
            trend += 3
        if ind.get("ma10") and price >= ind["ma10"]:
            trend += 3
        if ind.get("ma20") and price >= ind["ma20"]:
            trend += 4
        if ind.get("ma60") and price >= ind["ma60"]:
            trend += 3
        if ind.get("ma5") and ind.get("ma10") and ind.get("ma20") and ind["ma5"] >= ind["ma10"] >= ind["ma20"]:
            trend += 3
    score += clamp(trend, 0, 20)

    weight = h.weight
    if weight is None:
        position = 10
    elif weight <= 0.15:
        position = 15
    elif weight <= 0.20:
        position = 12
    elif weight <= 0.30:
        position = 7
    else:
        position = 3
        reasons.append("单票仓位过高")
    score += position

    pnl = h.unrealized_pct
    drawdown = ind.get("drawdown20")
    if pnl is None:
        pnl_score = 8
    elif pnl >= 0.08 and (drawdown is None or drawdown > -0.08):
        pnl_score = 15
    elif pnl >= 0:
        pnl_score = 12
    elif pnl >= -0.05:
        pnl_score = 9
    elif pnl >= -0.12:
        pnl_score = 6
    else:
        pnl_score = 2
        reasons.append("浮亏较深")
    if drawdown is not None and drawdown < -0.15:
        pnl_score = min(pnl_score, 7)
        reasons.append("从20日高点回撤较大")
    score += pnl_score

    vol_ratio = ind.get("vol_ratio")
    today_pct = h.today_pct
    volume_score = 8
    if vol_ratio is not None:
        if today_pct is not None and today_pct < -0.03 and vol_ratio > 1.8:
            volume_score = 3
            reasons.append("放量下跌")
        elif 0.6 <= vol_ratio <= 1.8:
            volume_score = 14
        elif vol_ratio > 2.5:
            volume_score = 7
            reasons.append("量能异常放大")
        else:
            volume_score = 10
    score += volume_score

    support = ind.get("support")
    invalidation = ind.get("invalidation")
    support_score = 8
    if price and support:
        dist = price / support - 1
        if price < support:
            support_score = 2
            reasons.append("跌破支撑")
        elif dist <= 0.08:
            support_score = 15
        elif dist <= 0.15:
            support_score = 10
        else:
            support_score = 6
            reasons.append("距离支撑较远")
    score += support_score

    momentum = 5
    rsi14 = ind.get("rsi14")
    hist = ind.get("macd_hist")
    k = ind.get("kdj_k")
    d = ind.get("kdj_d")
    if rsi14 is not None and 45 <= rsi14 <= 70:
        momentum += 2
    if hist is not None and hist > 0:
        momentum += 2
    if k is not None and d is not None and k >= d and k < 85:
        momentum += 1
    if rsi14 is not None and rsi14 > 78:
        momentum -= 3
        reasons.append("RSI偏热")
    if k is not None and d is not None and k < d and k > 75:
        momentum -= 2
        reasons.append("KDJ高位转弱")
    score += clamp(momentum, 0, 10)

    thesis = 8 if (h.industry or h.note) else 6
    risk_words = ["减持", "解禁", "亏损", "问询", "处罚", "退市", "暴雷", "业绩下滑"]
    if any(word in h.note for word in risk_words):
        thesis = 2
        reasons.append("备注含风险事件")
    score += thesis

    rs20 = ind.get("rs20")
    if rs20 is not None:
        if rs20 >= 0.05:
            score += 4
        elif rs20 >= 0:
            score += 2
        elif rs20 <= -0.08:
            score -= 6
            reasons.append("显著跑输大盘")
        elif rs20 <= -0.03:
            score -= 3
            reasons.append("相对大盘偏弱")

    sector_rs20 = ind.get("sector_rs20")
    sector_state = ind.get("sector_state")
    if sector_rs20 is not None:
        if sector_rs20 >= 0.03:
            score += 3
        elif sector_rs20 <= -0.05:
            score -= 4
            reasons.append("所属板块弱于大盘")
    if sector_state == "弱":
        score -= 2
        reasons.append("板块在MA20下方")

    atr14_pct = ind.get("atr14_pct")
    if atr14_pct is not None:
        if atr14_pct >= 0.08:
            score -= 5
            reasons.append("ATR波动过高")
        elif atr14_pct >= 0.05:
            score -= 2
            reasons.append("波动偏高")
        elif atr14_pct <= 0.03:
            score += 1

    event_risk_level = ind.get("event_risk_level")
    if event_risk_level == "高":
        score -= 8
        reasons.append("存在高风险事件")
    elif event_risk_level == "中":
        score -= 4
        reasons.append("存在事件窗口")

    if ind.get("market_state") == "弱":
        score -= 2
        reasons.append("大盘环境偏弱")

    score = clamp(score, 0, 100)

    raw_action = "只观察不操作"
    rounded = int(round(score))
    if rounded >= 82:
        raw_action = "加仓观察"
    elif rounded >= 75:
        raw_action = "继续持有"
    elif rounded >= 55:
        raw_action = "减仓"
    else:
        raw_action = "清仓/退出观察"

    ma20 = ind.get("ma20")
    ma60 = ind.get("ma60")
    ma20_dev = ind.get("ma20_dev")
    if not price or h.cost_price is None:
        raw_action = "只观察不操作"
        reasons.append("关键价格/成本数据缺失")
    if weight is not None and weight > 0.30 and raw_action == "加仓观察":
        raw_action = "减仓"
    if ma20_dev is not None and ma20_dev > 0.25:
        raw_action = "减仓" if raw_action in {"加仓观察", "继续持有"} else raw_action
        reasons.append("价格明显远离MA20")
    if price and ma20 and price < ma20 and pnl is not None and pnl <= -0.08:
        raw_action = "清仓/退出观察" if pnl <= -0.15 else "减仓"
    if price and ma60 and price < ma60 and ma20 and price < ma20:
        raw_action = "清仓/退出观察" if rounded < 65 else "减仓"
        reasons.append("MA20/MA60同时失守")
    if ind.get("market_state") == "弱" and raw_action == "加仓观察":
        raw_action = "继续持有"
        reasons.append("大盘弱势时不主动加仓")
    if ind.get("sector_state") == "弱" and raw_action == "加仓观察":
        raw_action = "继续持有"
        reasons.append("板块弱势时不主动加仓")
    if ind.get("event_risk_level") == "高" and raw_action in {"加仓观察", "继续持有"}:
        raw_action = "减仓"
        reasons.append("高风险事件优先降风险")

    priority = {"清仓/退出观察": 1, "减仓": 2, "加仓观察": 3, "继续持有": 4, "只观察不操作": 5}[raw_action]
    trigger = build_trigger(raw_action, h, support, invalidation)
    status = build_status(h)
    return rounded, raw_action, priority, status, "；".join(dict.fromkeys(reasons)) or trigger


def build_status(h: Holding) -> str:
    ind = h.indicators
    price = h.latest_price or ind.get("close")
    parts: list[str] = []
    if price and ind.get("ma20"):
        parts.append("站上MA20" if price >= ind["ma20"] else "跌破MA20")
    if ind.get("ma20_dev") is not None:
        parts.append(f"MA20偏离{pct(ind['ma20_dev'])}")
    if ind.get("vol_ratio") is not None:
        parts.append(f"量比{ind['vol_ratio']:.2f}")
    if ind.get("rsi14") is not None:
        parts.append(f"RSI{ind['rsi14']:.1f}")
    if ind.get("rs20") is not None:
        parts.append(f"RS20{pct(ind['rs20'])}")
    if ind.get("sector_state"):
        parts.append(f"板块{ind['sector_state']}")
    if ind.get("atr14_pct") is not None:
        parts.append(f"ATR{pct(ind['atr14_pct'])}")
    if ind.get("event_risk_level"):
        parts.append(f"事件{ind['event_risk_level']}")
    return "，".join(parts) if parts else "技术数据不足"


def build_trigger(action: str, h: Holding, support: float | None, invalidation: float | None) -> str:
    support_text = f"{support:.2f}" if support else "关键支撑"
    invalid_text = f"{invalidation:.2f}" if invalidation else "失效位"
    if action == "加仓观察":
        return f"仅在缩量企稳并守住{support_text}后加现仓20%-30%，总仓位不超过15%-20%"
    if action == "继续持有":
        return f"维持原仓，若有效跌破{invalid_text}则降级处理"
    if action == "减仓":
        return f"先降20%-50%，若收复{support_text}且量价修复再评估剩余仓位"
    if action == "清仓/退出观察":
        return f"退出或降至观察仓，重新站回{support_text}/MA20后再复盘"
    return "补齐最新价格、成本和K线后再给动作"


def make_report(
    holdings: list[Holding],
    rows: list[dict[str, Any]],
    run_date: str,
    holdings_path: Path,
    prices_path: Path | None,
    benchmark_path: Path | None,
    sectors_path: Path | None,
    events_path: Path | None,
) -> str:
    total_value = sum(h.market_value or 0 for h in holdings)
    sector_values: dict[str, float] = defaultdict(float)
    for h in holdings:
        sector_values[h.industry or "未分类"] += h.market_value or 0
    top_weight = max((h.weight or 0 for h in holdings), default=0)
    top_sector = max(sector_values.items(), key=lambda x: x[1], default=("未分类", 0))
    sorted_rows = sorted(rows, key=lambda x: (x["priority"], -x["score"]))

    buckets: dict[str, list[str]] = defaultdict(list)
    for row in sorted_rows:
        buckets[row["action"]].append(f"{row['name']}({row['code']})")

    lines = [
        "# A股每日持仓体检报告",
        f"体检日期：{run_date}",
        "执行技能：ashare-holdings-check",
        "结果类型：持仓风控体检，不构成个性化投资建议",
        "",
        "## 数据说明",
        f"- 持仓数据：{holdings_path}",
        f"- 行情/K线数据：{prices_path if prices_path else '未提供，技术判断受限'}",
        f"- 大盘/板块/事件数据：benchmark={benchmark_path or '未提供'}；sectors={sectors_path or '未提供'}；events={events_path or '未提供'}。",
        f"- 数据完整性：持仓 {len(holdings)} 只；技术数据覆盖 {sum(1 for h in holdings if h.indicators)} 只；相对强度覆盖 {sum(1 for h in holdings if h.indicators.get('rs20') is not None)} 只；事件覆盖 {sum(1 for h in holdings if h.indicators.get('event_risk'))} 只。",
        "- 指标口径：MA5/10/20/60、MA20偏离、20日回撤、量比、RSI14、MACD、KDJ、ATR14、相对强度RS20/RS60、板块强弱、事件风险、支撑/失效位、仓位集中度。",
        "- 主要限制：脚本不联网抓取行情；若输入数据滞后，结论只能作为下一次复盘草案。",
        "",
        "## 一、组合结论",
        f"- 总市值/现金/仓位：持仓市值约 {money(total_value)}；现金未提供时不估算总仓位。",
        f"- 集中度：最大单票仓位 {pct(top_weight)}；最大行业为 {top_sector[0]}，约 {pct(top_sector[1] / total_value) if total_value else '-'}。",
        f"- 环境与事件：{summarize_context(holdings)}",
        f"- 今日主要风险：{summarize_risk(sorted_rows)}",
        f"- 明日优先动作：优先处理 {', '.join(buckets.get('清仓/退出观察', []) + buckets.get('减仓', [])) or '无强制降仓项'}。",
        "",
        "## 二、持仓体检表",
        "| 操作建议 | 优先级 | 标的 | 代码 | 仓位 | 浮盈浮亏 | 趋势状态 | 量价/动量 | 支撑/失效 | 评分 | 具体动作 |",
        "|---|---:|---|---:|---:|---:|---|---|---|---:|---|",
    ]
    for row in sorted_rows:
        h = row["holding"]
        support = h.indicators.get("support")
        invalidation = h.indicators.get("invalidation")
        support_text = f"{support:.2f}/{invalidation:.2f}" if support and invalidation else "-"
        lines.append(
            f"| {row['action']} | {row['priority']} | {h.name or '-'} | {h.code or '-'} | "
            f"{pct(h.weight)} | {pct(h.unrealized_pct)} | {row['status']} | {row['momentum']} | "
            f"{support_text} | {row['score']} | {row['trigger']} |"
        )

    lines.extend(["", "## 三、逐个点评"])
    for row in sorted_rows:
        h = row["holding"]
        lines.append(
            f"- **{h.name or h.code}**：{row['action']}。仓位{pct(h.weight)}，浮盈浮亏{pct(h.unrealized_pct)}；"
            f"{row['status']}。{row['trigger']}。主要原因：{row['reason']}。"
        )

    lines.extend(
        [
            "",
            "## 四、组合调整清单",
            "```text",
            f"继续持有：{', '.join(buckets.get('继续持有', [])) or '无'}",
            f"加仓观察：{', '.join(buckets.get('加仓观察', [])) or '无'}",
            f"减仓：{', '.join(buckets.get('减仓', [])) or '无'}",
            f"清仓/退出观察：{', '.join(buckets.get('清仓/退出观察', [])) or '无'}",
            f"只观察不操作：{', '.join(buckets.get('只观察不操作', [])) or '无'}",
            "```",
            "",
            "## 五、风险提示",
            "以上为基于输入数据的研究型持仓体检。若次日出现跳空、停牌、重大公告、业绩预告、监管问询、解禁减持或市场系统性风险，应重新评估，不应机械执行旧结论。",
            "",
        ]
    )
    return "\n".join(lines)


def summarize_risk(rows: list[dict[str, Any]]) -> str:
    risky = [r for r in rows if r["action"] in {"清仓/退出观察", "减仓"}]
    if risky:
        return f"{len(risky)} 只触发降风险动作，先处理清仓/减仓项"
    add_count = sum(1 for r in rows if r["action"] == "加仓观察")
    if add_count:
        return f"{add_count} 只可观察加仓，但需等待确认信号"
    return "组合暂无强制风险动作，继续跟踪支撑位和仓位集中度"


def summarize_context(holdings: list[Holding]) -> str:
    states = [h.indicators.get("market_state") for h in holdings if h.indicators.get("market_state")]
    market = states[0] if states else "未提供大盘数据"
    sector_weak = sum(1 for h in holdings if h.indicators.get("sector_state") == "弱")
    event_high = sum(1 for h in holdings if h.indicators.get("event_risk_level") == "高")
    high_vol = sum(1 for h in holdings if (h.indicators.get("atr14_pct") or 0) >= 0.08)
    parts = [f"大盘环境{market}"]
    if sector_weak:
        parts.append(f"{sector_weak} 只处于弱板块")
    if high_vol:
        parts.append(f"{high_vol} 只ATR波动过高")
    if event_high:
        parts.append(f"{event_high} 只存在高风险事件")
    return "；".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a daily A-share position health report.")
    parser.add_argument("--holdings", required=True, type=Path, help="Holdings CSV")
    parser.add_argument("--prices", type=Path, help="Optional daily price history CSV")
    parser.add_argument("--benchmark", type=Path, help="Optional benchmark/index daily CSV, same columns as prices")
    parser.add_argument("--sectors", type=Path, help="Optional sector daily CSV with industry,date,open,high,low,close,volume")
    parser.add_argument("--events", type=Path, help="Optional event calendar CSV with code,date,event,impact")
    parser.add_argument("--date", default=date.today().isoformat(), help="Report/trading date")
    parser.add_argument("--runs-dir", default=Path("runs"), type=Path, help="Output runs directory")
    parser.add_argument("--output", type=Path, help="Optional explicit output markdown path")
    args = parser.parse_args()

    holdings = load_holdings(args.holdings)
    price_rows = load_prices(args.prices, args.date)
    benchmark_rows = load_prices(args.benchmark, args.date)
    sector_rows = load_sector_prices(args.sectors, args.date)
    events = load_events(args.events, args.date)
    for holding in holdings:
        rows = price_rows.get(holding.code, [])
        if rows:
            holding.indicators = calc_indicators(rows)
            if holding.latest_price is None:
                holding.latest_price = holding.indicators.get("close")
    enrich_context(holdings, first_indicator(benchmark_rows), sector_rows, events)

    report_rows = []
    for holding in holdings:
        score, action, priority, status, reason = score_holding(holding)
        report_rows.append(
            {
                "holding": holding,
                "score": score,
                "action": action,
                "priority": priority,
                "status": status,
                "momentum": status,
                "trigger": build_trigger(action, holding, holding.indicators.get("support"), holding.indicators.get("invalidation")),
                "reason": reason,
                "name": holding.name,
                "code": holding.code,
            }
        )

    report = make_report(holdings, report_rows, args.date, args.holdings, args.prices, args.benchmark, args.sectors, args.events)
    output = args.output or args.runs_dir / "ashare-holdings-check" / args.date / f"{args.date}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
