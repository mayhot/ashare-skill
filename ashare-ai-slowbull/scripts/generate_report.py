import argparse
import csv
import json
from pathlib import Path


GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "剔除": 3, "EX": 3}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fmt_yi(value):
    try:
        return f"{float(value):.0f}亿"
    except Exception:
        return str(value)


def fmt_amount(value):
    try:
        return f"{float(value):.2f}亿"
    except Exception:
        return str(value)


def fmt_pct(value):
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return str(value)


def names(rows, grade, limit=None):
    items = [row["name"] for row in rows if row.get("grade") == grade]
    if limit:
        items = items[:limit]
    return "、".join(items) if items else "无"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="runs/ashare-ai-slowbull/YYYY-MM-DD")
    parser.add_argument("--skill-version", default="ashare-ai-slowbull-postclose-v2")
    parser.add_argument("--stock-pool-version", default="local-universe-v1")
    parser.add_argument("--threshold-version", default="postclose-hardcap-v1")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    data_dir = run_dir / "data"
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    candidates = read_csv(data_dir / "candidates.csv")
    candidates.sort(key=lambda row: (GRADE_ORDER.get(row.get("grade"), 9), -float(row.get("score") or 0)))

    trade_date = meta.get("trade_date") or run_dir.name
    quote_ticktime = meta.get("quote_ticktime") or meta.get("top_ticktime_sample") or "未记录"
    fallback = meta.get("fallback_used", False)
    post_close_ok = meta.get("post_close_validated", "需人工确认")

    lines = [
        "# A股AI硬件上游二线慢牛筛选结果",
        "",
        f"筛选日期：{trade_date}",
        "执行技能：ashare-ai-slowbull",
        "结果类型：研究观察池，不是最终买入名单",
        f"run_time：{meta.get('run_time') or meta.get('fetched_at') or '未记录'}",
        f"quote_ticktime：{quote_ticktime}",
        f"skill_version：{args.skill_version}",
        f"stock_pool_version：{args.stock_pool_version}",
        f"threshold_version：{args.threshold_version}",
        f"fallback_used：{fallback}",
        f"post_close_validated：{post_close_ok}",
        "",
        "## 数据说明",
        f"- 数据来源：{meta.get('source', '未记录')}；排序字段：{meta.get('sort', 'amount desc')}。",
        f"- 数据完整性：有效A股前200记录 {meta.get('top200_count', '未知')} 条；候选交集 {meta.get('candidate_count', len(candidates))} 条。",
        "- 指标口径：使用保存的候选CSV和技术指标CSV；MACD/KDJ只作辅助确认，不作单独买卖依据。",
        "",
        "## 一、筛选结论",
        f"- A档，重点观察：{names(candidates, 'A')}",
        f"- B档，等待买点：{names(candidates, 'B')}",
        f"- C档，只跟踪不追：{names(candidates, 'C')}",
        f"- 剔除/暂不追：{names(candidates, '剔除', 20)}",
        "",
        "## 二、核心表格",
        "| 档位 | 排名 | 标的 | 代码 | 方向/主线 | 关键数据 | 技术状态 | MACD/KDJ | 量价/资金 | 证据/逻辑 | 支撑/失效 | 评分 | 买点观察 |",
        "|---|---:|---|---:|---|---|---|---|---|---|---|---:|---|",
    ]

    for row in candidates:
        if row.get("grade") == "剔除":
            continue
        key = (
            f"市值{fmt_yi(row.get('mktcap_yi'))}；成交额第{row.get('rank')}；"
            f"涨跌幅{fmt_pct(row.get('changepercent'))}"
        )
        funds = f"成交额{fmt_amount(row.get('amount_yi'))}"
        invalid = "跌破20日线且2-3日无法收回则降级"
        observation = "等待回踩或平台确认"
        lines.append(
            "| {grade} | {rank} | {name} | {code} | {direction} | {key} | {tech} | {tech} | {funds} | {evidence} | {invalid} | {score} | {observation} |".format(
                grade=row.get("grade", ""),
                rank=row.get("rank", ""),
                name=row.get("name", ""),
                code=row.get("code", ""),
                direction=row.get("direction", ""),
                key=key,
                tech=row.get("tech_summary", ""),
                funds=funds,
                evidence=row.get("evidence", "需核验"),
                invalid=invalid,
                score=row.get("score", ""),
                observation=observation,
            )
        )

    lines.extend(
        [
            "",
            "## 三、逐个点评",
            "详评应在自动表格基础上补充产业链位置、基本面证据、买点观察和失效条件；A/B档必须逐只写清。",
            "",
            "## 四、最终短名单",
            "```text",
            f"最优先观察：{names(candidates, 'A')}",
            f"次优先观察：{names(candidates, 'B', 5)}",
            f"只跟踪不急买：{names(candidates, 'C', 12)}",
            f"剔除但跟踪板块强度：{names(candidates, '剔除', 12)}",
            "```",
            "",
            "## 五、买点观察与失效条件",
            "- A/B档共同纪律：不追单日大涨或涨停，优先等回踩10日/20日线缩量企稳。",
            "- 平台突破：横盘5-15个交易日后温和放量突破，并且次日不跌回平台。",
            "- 强势二买：大阳线后3-8日缩量整理，不破10日/20日线，再次放量转强。",
            "- 统一失效：跌破20日线且2-3日无法收回；高位放量滞涨；MACD/KDJ高位死叉与价格走弱共振；AI硬件核心龙头集体破位。",
            "",
            "## 六、数据限制与风险提示",
            "这是研究观察池，不构成个性化投资建议。若收盘后校验、基本面证据或行情源存在缺口，应在正式报告中明确降级说明。",
        ]
    )

    out_path = run_dir / f"{trade_date}.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
