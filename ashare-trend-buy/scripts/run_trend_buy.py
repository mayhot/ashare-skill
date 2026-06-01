import csv
import argparse
import json
import math
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = None
RUNS_ROOT = None
SOURCE_TOP200 = None
SCREENING_DATE = None
NO_NETWORK = False


KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php/"
    "CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=300"
)
TOP_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData?page={page}&num=80&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=page"
)


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


def fetch_json(url: str):
    if NO_NETWORK:
        raise RuntimeError("network disabled by --no-network")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def read_top200():
    if SOURCE_TOP200 is None:
        return fetch_sina_top200()
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


def fetch_kline(symbol: str):
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
    front_row = main_theme and row["rank"] <= FRONT_ROW_RANK and row["amount_yi"] >= FRONT_ROW_AMOUNT_YI
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

    theme_score = 15 if front_row and primary_theme else 13 if primary_theme else 11 if main_theme else 8
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
    if not front_row and not main_theme and row["rank"] > 120:
        flags.append("细分前排/人气不足")
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
    if SOURCE_TOP200 is None:
        return "新浪实时成交额排名"
    try:
        return str(SOURCE_TOP200.relative_to(ROOT))
    except ValueError:
        return str(SOURCE_TOP200)


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
    lines.append(f"- 数据来源：候选池 `{source_label}`；日K来自新浪 240 分钟日线接口；结果保存到 `runs/ashare-trend-buy/{SCREENING_DATE}/`。")
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
    lines.append("- K线与指标：新浪 240 分钟日线接口；本地脚本计算 MA、量比、MACD、KDJ。")
    return "\n".join(lines) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="Run ashare-trend-buy screening.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Screening date, YYYY-MM-DD.")
    parser.add_argument("--runs-dir", default="runs", help="Run artifact root directory.")
    parser.add_argument("--top200", help="Optional verified same-day turnover top-200 CSV.")
    parser.add_argument("--no-network", action="store_true", help="Disable network access.")
    return parser.parse_args()


def configure(args):
    global RUN_DIR, RUNS_ROOT, SOURCE_TOP200, SCREENING_DATE, NO_NETWORK
    SCREENING_DATE = args.date
    NO_NETWORK = bool(args.no_network)
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
    candidates = read_top200()
    results = []
    for row in candidates:
        try:
            krows, _payload = fetch_kline(row["symbol"])
            ind = indicators(krows)
            results.append(score_candidate(row, ind))
        except Exception as exc:
            results.append({**row, "tier": "初筛观察池", "error": str(exc)})

    calculated = [r for r in results if not r.get("error")]
    summary = {
        "screening_date": SCREENING_DATE,
        "source_top200": candidate_source_label(),
        "candidate_count": len(candidates),
        "calculated_count": len(calculated),
        "latest_kline_dates": dict(Counter(r["date"] for r in calculated)),
        "tier_counts": dict(Counter(r["tier"] for r in calculated)),
    }
    enrich_relative_context(results)
    report = generate_report(results, summary)
    (RUN_DIR / f"{SCREENING_DATE}.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    tier_order = {"A": 5, "B": 4, "C": 3, "过热跟踪": 2, "剔除": 1}
    for row in sorted(calculated, key=lambda r: (tier_order.get(r["tier"], 0), r["score"]), reverse=True)[:25]:
        print(row["tier"], row["score"], row["code"], row["name"], row["theme"], row["date"])

if __name__ == "__main__":
    main()
