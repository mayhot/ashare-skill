# A-Share Codex Skills

本仓库是一组面向 A 股研究工作流的 Codex skills，用于生成盘后研究观察池、持仓体检、短线纪律计划、推荐结果回测和多策略合并报告。

所有输出均为研究观察与风控辅助，不构成个性化投资建议。实际交易需结合个人风险承受能力、最新行情、账户约束和独立判断。

## 项目结构

```text
.
├── ashare-ai-slowbull/              # AI 硬件上游二线慢牛筛选
├── ashare-trend-buy/                # A 股右侧趋势买点观察池
├── ashare-holdings-check/           # 每日持仓体检与风控检查
├── ashare-super-shortline-system/   # 超短线交易纪律与候选计划
├── ashare-merged-report/            # 合并 slowbull 与 trend-buy 同日报告
├── ashare-recommendation-returns/   # 推荐结果收益跟踪与历史回测
├── commit-code/                     # 提交代码时的分支与 changelog 规范
├── runs/                            # 各 skill 的历史运行报告
└── CHANGELOG.md                     # 项目变更记录
```

每个 skill 目录通常包含：

- `SKILL.md`：Codex skill 说明、触发场景、规则和输出规范。
- `scripts/`：可直接运行的 Python 脚本。
- `agents/openai.yaml`：agent 配置。

## Skills 概览

| Skill | 用途 | 常见输出 |
|---|---|---|
| `ashare-ai-slowbull` | 从当日 A 股成交额前 200 中筛选 AI 硬件上游、芯片、半导体设备、存储等二线慢牛候选 | `runs/ashare-ai-slowbull/YYYY-MM-DD/YYYY-MM-DD.md` |
| `ashare-trend-buy` | 按右侧趋势买入标准筛选 A/B/C 档研究观察池 | `runs/ashare-trend-buy/YYYY-MM-DD/YYYY-MM-DD.md` |
| `ashare-holdings-check` | 对已有持仓做每日健康检查、仓位风险和失效条件判断 | `runs/ashare-holdings-check/YYYY-MM-DD/YYYY-MM-DD.md` |
| `ashare-super-shortline-system` | 将超短线纪律规则转为候选股计划、交易权限门和复盘清单 | 自定义输出路径，通常放在 `runs/ashare-super-shortline-system/` |
| `ashare-merged-report` | 合并同一日期的 slowbull 与 trend-buy 报告，找共识、冲突和降级项 | `runs/ashare-merged-report/YYYY-MM-DD/report.md` |
| `ashare-recommendation-returns` | 跟踪 A/B 推荐后的 1/5/10/20 交易日收益，生成回测报告 | 源 skill 日期目录下的 `*_backtest_report.*` |
| `commit-code` | 规范提交：`runs/` 进 runs 分支，skill/source 变更进 skill 分支，并更新 changelog | Git 提交流程说明 |

## 快速开始

在仓库根目录运行脚本：

```powershell
cd D:\Code\q-skills\ashare-skill
python ashare-trend-buy/scripts/run_trend_buy.py --date 2026-06-01
```

AI 硬件上游慢牛筛选：

```powershell
python ashare-ai-slowbull/scripts/run_slowbull.py --trade-date 2026-06-01
```

持仓体检：

```powershell
python ashare-holdings-check/scripts/check_positions.py `
  --holdings path/to/holdings.csv `
  --prices path/to/prices.csv `
  --benchmark path/to/benchmark.csv `
  --sectors path/to/sectors.csv `
  --events path/to/events.csv `
  --date 2026-06-01
```

合并同日报告：

```powershell
python ashare-merged-report/scripts/merge_reports.py --runs-dir runs --date 2026-06-01
```

推荐结果收益跟踪：

```powershell
python ashare-recommendation-returns/scripts/calc_recommendation_returns.py --repo-root . --as-of 2026-06-01
```

超短线计划：

```powershell
python ashare-super-shortline-system/scripts/build_shortline_plan.py `
  --symbols 300308,300502,603986 `
  --market-phase rising `
  --money-effect strong `
  --broad-index-month-pct 5.8 `
  --leading-themes CPO,AI `
  --account-month-return 8.5 `
  --account-week-return 2.0 `
  --max-single-position 25% `
  --trader-state calm `
  --output runs/ashare-super-shortline-system/2026-06-01/2026-06-01.md
```

## 数据与运行约定

- 实盘筛选应优先在 A 股收盘后运行，并记录 `run_time`、`trade_date`、行情时间戳和数据源。
- 不要编造成交额排名、价格、K 线、财报、公告、资金流或客户信息。
- 如果行情接口不可用，应明确说明数据缺口；可以使用本地 CSV 或 `--no-network` / `--no-fetch` 做离线验证。
- `runs/` 目录只保存最终报告和必要回测结果，不保存临时抓取响应、原始接口数据或过程性中间表，除非用户明确要求。
- 回测和推荐收益跟踪应从推荐日后的交易日开始计算，不把推荐当日涨跌当成后验收益。

## 常用输入格式

持仓 CSV 建议字段：

```text
code,name,quantity,cost_price,latest_price,market_value,portfolio_weight,today_pct,unrealized_pct,hold_days,industry,note
```

日 K CSV 建议字段：

```text
code,date,open,high,low,close,volume,amount,turnover,pct_chg
```

事件 CSV 建议字段：

```text
code,date,event,impact
```

## 开发与维护

- 新增或调整 skill 时，优先更新对应目录下的 `SKILL.md` 和脚本。
- 重要变更需要记录到 `CHANGELOG.md`。
- 提交代码时可参考 `commit-code/SKILL.md`：运行报告归 `runs` 分支，skill/source/docs 变更归 `skill` 分支，最后合并回 `main`。
- 修改脚本后建议至少运行对应脚本的 `--dry-run`、`--no-fetch` 或小样本输入，确认输出路径和字段没有破坏。

## 免责声明

本项目用于 A 股研究、筛选、复盘和风控辅助。报告中的分档、评分、仓位比例和买点观察均为条件化研究表达，不代表确定收益，也不构成个性化投资建议或交易指令。
