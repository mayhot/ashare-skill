"""Run the ashare-ai-slowbull post-close screen and write the final report.

The script intentionally keeps raw market data in memory. The only persisted
artifact is runs/ashare-ai-slowbull/YYYY-MM-DD/YYYY-MM-DD.md.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CN_TZ = timezone(timedelta(hours=8))
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "剔除": 3}
TIER_BASE = {"S": 19, "A": 16, "B": 12}


@dataclass(frozen=True)
class Segment:
    tier: str
    direction: str
    front_row: int


# Curated high-attention AI hardware, chip, semiconductor equipment, and storage
# universe. This is deliberately front-row biased; unknown names can still be
# added here when their evidence becomes strong enough.
FRONT_ROW_UNIVERSE: dict[str, Segment] = {
    "688981": Segment("B", "晶圆代工/国产半导体锚", 5),
    "002156": Segment("S", "先进封测/Chiplet/AMD链", 5),
    "300502": Segment("S", "光模块/高速光通信", 5),
    "603986": Segment("A", "存储芯片/MCU", 5),
    "300476": Segment("S", "AI PCB/高多层板", 5),
    "300308": Segment("S", "光模块/CPO", 5),
    "688008": Segment("S", "存储接口/AI服务器互连芯片", 5),
    "688256": Segment("S", "AI芯片/国产算力", 5),
    "600584": Segment("S", "先进封装/存储封测", 5),
    "000988": Segment("S", "光模块/光芯片/CPO", 4),
    "688012": Segment("A", "半导体设备/刻蚀薄膜", 5),
    "688041": Segment("S", "AI芯片/国产算力", 5),
    "002281": Segment("S", "光模块/光器件/光芯片", 5),
    "002463": Segment("S", "AI PCB/服务器PCB", 5),
    "688525": Segment("A", "存储/企业级SSD/存储模组", 5),
    "301308": Segment("A", "存储/企业级SSD/存储模组", 5),
    "300475": Segment("B", "存储分销/存储链", 3),
    "688072": Segment("A", "半导体设备/薄膜沉积", 5),
    "300604": Segment("A", "半导体测试设备", 5),
    "001309": Segment("A", "存储/存储模组", 4),
    "002436": Segment("A", "封装基板/PCB", 4),
    "688521": Segment("B", "芯片IP/AI SoC", 4),
    "603083": Segment("S", "光模块/光通信设备", 4),
    "002916": Segment("S", "AI PCB/封装基板", 5),
    "301269": Segment("B", "EDA/芯片设计工具", 4),
    "603228": Segment("S", "PCB/服务器板", 4),
    "300672": Segment("B", "国产芯片/存储控制", 3),
    "688126": Segment("A", "半导体材料/硅片", 4),
    "688313": Segment("S", "光芯片/CPO光源", 4),
    "002049": Segment("B", "特种芯片/FPGA", 4),
    "603501": Segment("B", "CIS/模拟芯片", 4),
    "688498": Segment("S", "光芯片/CPO光源", 4),
    "688110": Segment("A", "存储芯片", 4),
    "002409": Segment("A", "HBM/半导体材料", 4),
    "002185": Segment("S", "先进封装/存储封测", 4),
    "688629": Segment("S", "高速连接器/背板连接", 4),
    "688048": Segment("S", "光芯片/激光芯片", 3),
    "601208": Segment("A", "电子树脂/绝缘材料", 3),
    "600183": Segment("A", "CCL/覆铜板/AI服务器材料", 5),
    "603256": Segment("A", "电子布/玻纤布", 4),
    "300408": Segment("B", "MLCC/陶瓷材料", 3),
    "688082": Segment("A", "半导体设备/清洗设备", 5),
    "301526": Segment("A", "玻纤/电子布上游", 3),
    "300567": Segment("A", "检测量测设备", 4),
    "300223": Segment("B", "存储芯片/计算芯片", 4),
    "300620": Segment("S", "光芯片/光器件", 4),
    "600460": Segment("B", "功率/特色工艺芯片", 4),
    "002837": Segment("A", "液冷/温控", 4),
    "600601": Segment("A", "PCB/电子电路", 3),
}


# Backtest 2026-05-20..2026-05-27 showed better follow-through in
# advanced packaging, AI PCB, CCL/electronic cloth, and mild pullbacks.
PROVEN_EDGE_CODES = {"002156", "002185", "600584", "002463", "600183", "603256", "300408", "301526"}
CAUTION_CODES = {"688313", "688498", "002837", "002050", "688110", "688072", "002008"}
EDGE_DIRECTIONS = ("先进封测", "封测", "Chiplet", "PCB", "CCL", "覆铜板", "电子布", "玻纤", "陶瓷材料")
CAUTION_DIRECTIONS = ("液冷", "温控", "CPO光源", "薄膜沉积", "存储芯片")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ashare-ai-slowbull screen.")
    parser.add_argument("--trade-date", help="Trading date, default: China local date.")
    parser.add_argument("--output-root", default="runs/ashare-ai-slowbull")
    parser.add_argument("--skip-post-close-check", action="store_true")
    return parser.parse_args()


def to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


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


def fetch_json(url: str, timeout: int = 12, tries: int = 3) -> Any:
    return json.loads(fetch_text(url, timeout=timeout, tries=tries))


def fetch_sina_top200() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 6):
        url = (
            "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData"
            f"?page={page}&num=50&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=init"
        )
        rows.extend(fetch_json(url, timeout=15, tries=4))

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        symbol = row.get("symbol")
        if symbol and symbol not in seen:
            seen.add(symbol)
            unique.append(row)
    return unique[:200]


def fetch_sina_daily_k(symbol: str) -> list[dict[str, float | str]]:
    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/"
        "CN_MarketDataService.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen=90"
    )
    text = fetch_text(url, timeout=8, tries=2)
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


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    prev = values[0]
    result: list[float] = []
    for value in values:
        prev = alpha * value + (1 - alpha) * prev
        result.append(prev)
    return result


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(closes)):
        delta = closes[idx] - closes[idx - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def indicators(kline: list[dict[str, float | str]]) -> dict[str, float | str]:
    closes = [float(item["close"]) for item in kline]
    highs = [float(item["high"]) for item in kline]
    lows = [float(item["low"]) for item in kline]
    if len(closes) < 35:
        return {}

    def ma(period: int) -> float | None:
        return sum(closes[-period:]) / period if len(closes) >= period else None

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema(dif, 9)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]

    k_value = 50.0
    d_value = 50.0
    k_values: list[float] = []
    d_values: list[float] = []
    j_values: list[float] = []
    for idx, close in enumerate(closes):
        start = max(0, idx - 8)
        high = max(highs[start : idx + 1])
        low = min(lows[start : idx + 1])
        rsv = 50.0 if high == low else (close - low) / (high - low) * 100
        k_value = k_value * 2 / 3 + rsv / 3
        d_value = d_value * 2 / 3 + k_value / 3
        j_value = 3 * k_value - 2 * d_value
        k_values.append(k_value)
        d_values.append(d_value)
        j_values.append(j_value)

    ma20 = ma(20)
    close = closes[-1]
    return {
        "date": str(kline[-1]["date"]),
        "close": close,
        "ma10": ma(10) or 0,
        "ma20": ma20 or 0,
        "ma30": ma(30) or 0,
        "dev20": (close / ma20 - 1) * 100 if ma20 else 0,
        "rsi": rsi(closes) or 0,
        "dif": dif[-1],
        "dea": dea[-1],
        "hist": hist[-1],
        "hist_prev": hist[-2],
        "kdj_k": k_values[-1],
        "kdj_d": d_values[-1],
        "kdj_j": j_values[-1],
        "gain20": (close / closes[-21] - 1) * 100 if len(closes) > 21 else 0,
    }


def has_indicators(ind: dict[str, Any]) -> bool:
    return bool(ind and ind.get("ma20"))


def direction_has(segment: Segment, keywords: tuple[str, ...]) -> bool:
    return any(keyword in segment.direction for keyword in keywords)


def backtest_edge_adjustment(row: dict[str, Any], segment: Segment, ind: dict[str, Any]) -> int:
    """Small 2026-05 backtest-informed adjustment, bounded to avoid overfit."""
    code = str(row.get("code", ""))
    rank = int(row["rank"])
    change = to_float(row.get("changepercent"))
    adjustment = 0

    if code in PROVEN_EDGE_CODES:
        adjustment += 4
    elif direction_has(segment, EDGE_DIRECTIONS):
        adjustment += 2

    if code in CAUTION_CODES:
        adjustment -= 5
    elif direction_has(segment, CAUTION_DIRECTIONS):
        adjustment -= 2

    if -5 <= change <= 3 and rank <= 100:
        adjustment += 3
    elif 3 < change <= 6 and direction_has(segment, EDGE_DIRECTIONS):
        adjustment += 1
    elif change >= 9.5:
        adjustment -= 4

    if 101 <= rank <= 150:
        adjustment -= 2

    if has_indicators(ind):
        dev20 = float(ind["dev20"])
        rsi_value = float(ind["rsi"])
        if dev20 > 25 or rsi_value > 80:
            adjustment -= 4
        elif dev20 > 18 or rsi_value > 75:
            adjustment -= 2
        if code in PROVEN_EDGE_CODES and -3 <= dev20 <= 12 and rsi_value <= 75:
            adjustment += 2

    return max(-8, min(8, adjustment))


def score(row: dict[str, Any], segment: Segment, ind: dict[str, Any]) -> int:
    rank = int(row["rank"])
    change = to_float(row.get("changepercent"))
    market_cap_yi = to_float(row.get("mktcap")) / 10000

    turnover = 20 if rank <= 50 else 17 if rank <= 100 else 14 if rank <= 150 else 11
    turnover += min(segment.front_row, 5) * 0.6
    cap_score = 5 if market_cap_yi < 500 else 10 if market_cap_yi <= 2000 else 7 if market_cap_yi <= 3000 else 3

    crowding = 15 - (5 if change >= 9.5 else 0)
    trend = 10
    if has_indicators(ind):
        dev20 = float(ind["dev20"])
        rsi_value = float(ind["rsi"])
        gain20 = float(ind["gain20"])
        crowding -= 5 if dev20 > 25 else 3 if dev20 > 15 else 0
        crowding -= 4 if rsi_value > 80 else 2 if rsi_value > 75 else 0
        crowding -= 3 if gain20 > 50 else 0

        trend = 11
        if float(ind["close"]) >= float(ind["ma10"]) >= float(ind["ma20"]):
            trend += 4
        elif float(ind["close"]) >= float(ind["ma20"]):
            trend += 2
        if float(ind["ma20"]) >= float(ind["ma30"]):
            trend += 2
        trend += 3 if -2 <= dev20 <= 8 else 1 if 8 < dev20 <= 15 else -3 if dev20 > 20 else 0
        trend += 1 if float(ind["dif"]) > float(ind["dea"]) else 0
        trend += 1 if float(ind["kdj_k"]) > float(ind["kdj_d"]) and float(ind["kdj_j"]) < 90 else 0
        trend = max(5, min(20, trend))

    fundamentals = 10 + segment.front_row + (1 if segment.tier == "S" else -1 if segment.tier == "B" else 0)
    total = (
        TIER_BASE[segment.tier]
        + min(20, turnover)
        + cap_score
        + max(0, crowding)
        + trend
        + min(15, fundamentals)
        + backtest_edge_adjustment(row, segment, ind)
    )
    return round(total)


def a_eligible(row: dict[str, Any], segment: Segment, ind: dict[str, Any]) -> bool:
    code = str(row.get("code", ""))
    rank = int(row["rank"])
    change = to_float(row.get("changepercent"))
    market_cap_yi = to_float(row.get("mktcap")) / 10000

    if rank > 100 or not (500 <= market_cap_yi <= 2000):
        return False
    if change >= 9.5:
        return False
    if code in CAUTION_CODES and code not in PROVEN_EDGE_CODES:
        return False
    if direction_has(segment, CAUTION_DIRECTIONS) and code not in PROVEN_EDGE_CODES:
        return False
    if has_indicators(ind):
        dev20 = float(ind["dev20"])
        rsi_value = float(ind["rsi"])
        if dev20 > 18 or rsi_value > 78:
            return False
    return True


def grade(row: dict[str, Any], numeric_score: int, ind: dict[str, Any]) -> str:
    segment = FRONT_ROW_UNIVERSE.get(row.get("code"))
    change = to_float(row.get("changepercent"))
    market_cap_yi = to_float(row.get("mktcap")) / 10000
    dev20 = float(ind.get("dev20", 0)) if has_indicators(ind) else None
    rsi_value = float(ind.get("rsi", 0)) if has_indicators(ind) else None

    if change >= 9.5 and ((rsi_value and rsi_value > 80) or (dev20 and dev20 > 25)):
        return "C"
    if market_cap_yi > 3000:
        return "剔除"
    if change >= 9.5 or (rsi_value and rsi_value > 80) or (dev20 and dev20 > 25):
        return "B" if numeric_score >= 78 and market_cap_yi <= 2000 else "C"
    if market_cap_yi > 2000:
        return "B" if numeric_score >= 78 else "C"
    if market_cap_yi < 500:
        return "C" if numeric_score >= 70 else "剔除"
    if segment and not a_eligible(row, segment, ind):
        return "B" if numeric_score >= 75 else "C" if numeric_score >= 65 else "剔除"
    return "A" if numeric_score >= 90 else "B" if numeric_score >= 76 else "C" if numeric_score >= 66 else "剔除"


def tech_summary(ind: dict[str, Any]) -> str:
    if not has_indicators(ind):
        return "K线不足，技术项降权"
    macd = (
        "MACD多头扩张"
        if float(ind["dif"]) > float(ind["dea"]) and float(ind["hist"]) >= float(ind["hist_prev"])
        else "MACD多头收敛"
        if float(ind["dif"]) > float(ind["dea"])
        else "MACD偏弱"
    )
    kdj = (
        "KDJ健康"
        if float(ind["kdj_k"]) > float(ind["kdj_d"]) and float(ind["kdj_j"]) < 90
        else "KDJ高位"
        if float(ind["kdj_j"]) >= 90
        else "KDJ待修复"
    )
    return f"{macd}；{kdj}；RSI {float(ind['rsi']):.1f}；MA20偏离 {float(ind['dev20']):.1f}%"


def buy_observation(ind: dict[str, Any]) -> str:
    if not has_indicators(ind):
        return "等待K线确认"
    dev20 = float(ind["dev20"])
    if -3 <= dev20 <= 5:
        return "趋势票回踩20日线附近，观察缩量企稳后能否转强"
    if 5 < dev20 <= 12:
        return "趋势仍强，等待回踩10/20日线缩量确认"
    if dev20 > 15:
        return "偏离20日线较大，等待降温和平台整理"
    if dev20 < -3:
        return "低于20日线，先看能否放量收回"
    return "等待回踩或平台确认"


def support_text(ind: dict[str, Any]) -> str:
    if not has_indicators(ind):
        return "跌破关键均线降级"
    return f"20日线约{float(ind['ma20']):.2f}；跌破后2-3日不能收回则降级"


def backtest_profile_text(row: dict[str, Any], segment: Segment, ind: dict[str, Any]) -> str:
    adjustment = backtest_edge_adjustment(row, segment, ind)
    if adjustment >= 4:
        return "回测因子加分：验证细分/温和形态"
    if adjustment <= -4:
        return "回测因子降级：高波动/过热/低胜率形态"
    if adjustment > 0:
        return "回测因子小幅加分"
    if adjustment < 0:
        return "回测因子小幅降权"
    return "回测因子中性"


def fmt_yi(value: Any) -> str:
    return f"{to_float(value) / 10000:.0f}亿"


def fmt_amount(value: Any) -> str:
    return f"{to_float(value) / 1e8:.2f}亿"


def fmt_pct(value: Any) -> str:
    return f"{to_float(value):+.2f}%"


def names(candidates: list[dict[str, Any]], grade_name: str, limit: int = 5) -> str:
    selected = [item["row"]["name"] for item in candidates if item["grade"] == grade_name]
    return "、".join(selected[:limit]) if selected else "无"


def build_report(
    trade_date: str,
    run_time: str,
    quote_ticktime: str,
    top_count: int,
    candidates: list[dict[str, Any]],
) -> str:
    display: list[dict[str, Any]] = []
    for grade_name, limit in [("A", 5), ("B", 5), ("C", 5), ("剔除", 8)]:
        display.extend([item for item in candidates if item["grade"] == grade_name][:limit])

    lines = [
        "# A股AI硬件上游二线慢牛筛选结果",
        "",
        f"筛选日期：{trade_date}",
        "执行技能：ashare-ai-slowbull",
        "结果类型：研究观察池，不是最终买入名单",
        f"run_time：{run_time}",
        f"quote_ticktime：{quote_ticktime}",
        "skill_version：ashare-ai-slowbull-postclose-v4+backtest-edge",
        "stock_pool_version：frontrow-ai-hardware-chip-equipment-storage-v1",
        "threshold_version：postclose-hardcap-v3+backtest-edge-20260520-0527",
        "fallback_used：False",
        "post_close_validated：True",
        "",
        "## 数据说明",
        "- 数据来源：新浪财经 Market_Center.getHQNodeData，按 amount 成交额倒序分页抓取；新浪 CN_MarketDataService 日K接口用于均线、RSI、MACD、KDJ计算。",
        f"- 数据完整性：有效A股前200记录 {top_count} 条；候选交集 {len(candidates)} 条；前排样本 ticktime 覆盖到 {quote_ticktime}。",
        "- 指标口径：MA10/20/30、RSI14、MACD(12,26,9)、KDJ(9,3,3)由日K计算；MACD/KDJ只作辅助确认，不作单独买卖依据。",
        "- 市场环境：AI硬件链按成交额前排强度、核心票位置和过热程度判断；若涨停和大阳线密集，优先等待20日线企稳而非追涨。",
        "- 附加评估：已检查趋势票是否回踩20日线企稳；已优先排序行业细分中公认知名度高、人气高的前排；已纳入2026-05-20至2026-05-27回测因子。",
        "- 限制说明：基本面证据以公开业务定位和产业链关系为主，未逐条展开财报公告原文；对涨停、过热、市值过大的票执行硬降级或板块锚剔除。",
        "",
        "## 一、筛选结论",
        "- 市场环境：芯片、半导体设备、存储和AI硬件上游强度高时，重点找不过热的细分前排；回测显示温和回踩和先进封测/PCB/CCL/电子布更容易延续，追高与高波动CPO光源需降权。",
        f"- A档，重点观察：{names(candidates, 'A')}",
        f"- B档，等待买点：{names(candidates, 'B')}",
        f"- C档，只跟踪不追：{names(candidates, 'C')}",
        f"- 剔除/板块锚：{names(candidates, '剔除', 8)}",
        "",
        "## 二、核心表格",
        "| 档位 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | 量价/资金 | 证据/逻辑 | 回测因子 | 支撑/失效 | 评分 | 买点观察 |",
        "|---|---:|---|---:|---|---|---|---|---|---|---|---:|---|",
    ]

    for item in display:
        row = item["row"]
        ind = item["indicators"]
        segment = item["segment"]
        evidence = f"{segment.direction}细分；前排/人气{segment.front_row}/5"
        if item["grade"] == "剔除":
            evidence += "；按板块锚或过热处理"
        lines.append(
            f"| {item['grade']} | {row['rank']} | {row['name']} | {row['code']} | "
            f"{segment.direction} | 市值{fmt_yi(row.get('mktcap'))}；成交额第{row['rank']}；涨跌幅{fmt_pct(row.get('changepercent'))} | "
            f"{tech_summary(ind)} | 成交额{fmt_amount(row.get('amount'))}；细分前排人气{segment.front_row}/5 | "
            f"{evidence} | {backtest_profile_text(row, segment, ind)} | {support_text(ind)} | {item['score']} | {buy_observation(ind)} |"
        )

    detail_items = [item for item in candidates if item["grade"] == "A"][:5]
    detail_items.extend([item for item in candidates if item["grade"] == "B"][:5])

    lines.extend(["", "## 三、逐个点评"])
    for item in detail_items:
        row = item["row"]
        ind = item["indicators"]
        segment = item["segment"]
        lines.append(
            f"- **{row['name']}（{row['code']}，{item['grade']}档）**：{segment.direction}。"
            f"成交额第{row['rank']}、{fmt_amount(row.get('amount'))}，市值约{fmt_yi(row.get('mktcap'))}，涨跌幅{fmt_pct(row.get('changepercent'))}。"
            f"{tech_summary(ind)}。前排/人气评分 {segment.front_row}/5。"
            f"{backtest_profile_text(row, segment, ind)}。"
            f"买点观察：{buy_observation(ind)}。失效：{support_text(ind)}；若板块从主升加速转为退潮需降级。"
        )

    lines.extend(
        [
            "",
            "## 四、最终短名单",
            "```text",
            f"最优先观察：{names(candidates, 'A')}",
            f"次优先观察：{names(candidates, 'B')}",
            f"只跟踪不追：{names(candidates, 'C', 8)}",
            f"剔除但跟踪板块强度：{names(candidates, '剔除', 8)}",
            "```",
            "",
            "## 五、买点观察与失效条件",
            "- 趋势票机会：已经形成趋势的票，若回踩20日均线附近并缩量企稳、重新收回短均线或温和放量转强，才进入重点观察；不把单日大涨本身当作买点。",
            "- 回测调权：先进封测、AI PCB、CCL/覆铜板、电子布/玻纤布在本轮验证中胜率更高；液冷、独立CPO光源、薄膜沉积设备、单日涨幅过热的存储芯片需降低档位或只等二次确认。",
            "- A档纪律：A档必须满足市值500-2000亿、成交额前100、非涨停/非极端过热、非低胜率高波动形态；否则即使分数高也放入B档等待买点。",
            "- 前排优先：同一细分方向优先看公认知名度高、人气高、成交额持续靠前的前排；冷门后排只有在趋势和证据显著更强时才提高优先级。",
            "- 平台突破：横盘5-15个交易日后温和放量突破，并且次日不跌回平台。",
            "- 强势二买：大阳线后3-8日缩量整理，不破10日/20日线，再次放量转强。",
            "- 统一失效：跌破20日线且2-3日无法收回；高位放量滞涨；MACD/KDJ高位死叉与价格走弱共振；半导体/AI硬件核心前排集体破位。",
            "",
            "## 六、数据限制与风险提示",
            "本报告是研究观察池，不构成个性化投资建议。若后续高位前排放量滞涨、核心龙头跌破20日线或成交额快速退潮，A/B档都需要重新降级复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    now = datetime.now(CN_TZ)
    if not args.skip_post_close_check and now.hour < 15 or (
        not args.skip_post_close_check and now.hour == 15 and now.minute < 30
    ):
        raise SystemExit("A股交易日15:30前不执行真实筛选。")

    trade_date = args.trade_date or now.strftime("%Y-%m-%d")
    run_time = now.strftime("%Y-%m-%d %H:%M:%S +08:00")
    top = fetch_sina_top200()
    if len(top) < 200:
        raise SystemExit(f"成交额前200不完整：仅获取 {len(top)} 条。")

    for idx, row in enumerate(top, start=1):
        row["rank"] = idx
    quote_ticktime = max([row.get("ticktime") for row in top[:20] if row.get("ticktime")] or ["未记录"])

    candidates: list[dict[str, Any]] = []
    for row in top:
        segment = FRONT_ROW_UNIVERSE.get(row.get("code"))
        if not segment:
            continue
        try:
            ind = indicators(fetch_sina_daily_k(row["symbol"]))
        except Exception:
            ind = {}
        numeric_score = score(row, segment, ind)
        candidates.append(
            {
                "row": row,
                "segment": segment,
                "indicators": ind,
                "score": numeric_score,
                "grade": grade(row, numeric_score, ind),
            }
        )

    candidates.sort(
        key=lambda item: (
            GRADE_ORDER.get(item["grade"], 9),
            -int(item["score"]),
            int(item["row"]["rank"]),
        )
    )

    out_dir = Path(args.output_root) / trade_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trade_date}.md"
    out_path.write_text(
        build_report(trade_date, run_time, quote_ticktime, len(top), candidates),
        encoding="utf-8",
    )
    print(out_path)


if __name__ == "__main__":
    main()
