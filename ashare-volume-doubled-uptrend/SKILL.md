---
name: ashare-volume-doubled-uptrend
description: Screen the full A-share market for research candidates whose latest 6-month daily K-line structure is in an uptrend, with at least one confirmed volume-doubling up day in the latest 5 trading days and the next trading day holding above half of that up day's gain. Use when the user asks for 全A筛选、近6个月K线上升趋势、近5日成交量翻倍、放量后次日不跌破涨幅一半、量价确认、趋势放量守涨 or similar A股研究观察池 tasks.
---

# 全A上升趋势放量守涨筛选

本 skill 用于从全 A 市场筛选“中期趋势向上、短期出现放量上涨、次日守住涨幅半分位”的研究观察池。输出必须是条件化研究表达，不得写成直接买入建议，也不得编造行情、K 线、成交量或财务数据。

## 首选脚本

优先运行同目录脚本，保证趋势和量价口径一致：

```powershell
python ashare-volume-doubled-uptrend/scripts/run_volume_doubled_uptrend.py --trade-date YYYY-MM-DD
```

- Default market-cap filter: `--min-market-cap-yuan 20000000000`, which excludes companies below 20bn yuan total market cap. Set `--min-market-cap-yuan 0` to disable.

常用参数：

- `--trade-date YYYY-MM-DD`：筛选基准日；默认使用本地当前日期。
- `--runs-dir runs`：报告输出根目录。
- `--refresh-cache`：强制重新一次性拉取近 6 个月全 A 日 K，并覆盖共享缓存。
- `--cache-dir PATH`：自定义 K 线缓存目录；默认 `runs/ashare-volume-doubled-uptrend/kline-cache/`。
- `--market-cache-db runs/ashare-kline-sqlite-cache/ashare_kline.sqlite`：优先读取 `ashare-kline-sqlite-cache` 的中央 SQLite；股票池用 `stock_universe`，日 K 用 `daily_kline`，不足时再按原逻辑联网补。
- `--ignore-market-cache`：诊断本 skill 自有缓存或公网源时跳过中央 SQLite。
- `--initial-lookback-days 430`：缓存为空或强制刷新时的全量拉取自然日跨度。
- `--incremental-lookback-days 12`：缓存存在时的增量更新自然日跨度；正常每日运行只补最近/当日日 K。
- `--batch-size 100`：首次全量或续跑全量缓存时，每完成一批股票就持久化一次缓存；默认每 100 只落盘。
- `--request-timeout 8`：单个行情请求超时时间，默认 8 秒，避免接口长时间挂起。
- `--no-baostock-fallback`：禁用 BaoStock 第三数据源补采；默认会对主源仍未完成的代码做 BaoStock 串行补采。
- `--kline-csv PATH`：使用本地日 K CSV 离线筛选，适合用户已提供全 A 或自选池 K 线。
- `--symbols 000001,600000`：只扫描指定股票，适合调试或小样本复核。
- `--no-network`：禁用联网；必须配合 `--kline-csv`。
- `--volume-base prev|ma5|ma20`：成交量翻倍基准；默认 `prev`，即放量日成交量不低于前一交易日 2 倍。
- `--hold-by close|low`：次日守涨判断使用次日收盘或最低价；默认 `close`。
- `--min-6m-return-pct 8`：6 个月窗口最低涨幅；默认 8%。
- `--max-results 50`：报告表格最多展示数量；默认 50。

脚本必须保存：

```text
runs/ashare-volume-doubled-uptrend/YYYY-MM-DD/YYYY-MM-DD.md
```

正式报告位置参考 `ashare-trend-buy`：每个交易日只在对应日期目录保存同名 Markdown 报告。共享 K 线缓存单独保存在 skill 的结果根目录：

```text
runs/ashare-volume-doubled-uptrend/kline-cache/daily_kline_6m.sqlite
runs/ashare-volume-doubled-uptrend/kline-cache/daily_kline_6m.meta.json
runs/ashare-volume-doubled-uptrend/kline-cache/failed_kline_codes.csv
```

SQLite cache update:
- Shared network cache now uses `runs/ashare-volume-doubled-uptrend/kline-cache/daily_kline_6m.sqlite`.
- If old `daily_kline_6m.csv` exists and SQLite cache does not, the script migrates it automatically once.
- New K-line rows are persisted with `(code,date)` upsert instead of rewriting one large CSV.
- Each run trims old rows by `--cache-calendar-days`, so the cache window stays bounded.
- Local `--kline-csv` remains an offline input mode and does not update the shared SQLite cache.

缓存目录用于后续每日增量执行，不放入日期报告目录。除上述缓存和最终报告外，原始接口响应、过程 JSON、临时脚本副本不归档到 `runs/`。

## K线缓存策略

1. 首次执行时，脚本先尝试读取 `runs/ashare-kline-sqlite-cache/ashare_kline.sqlite` 的 `stock_universe` 和 `daily_kline` 作为中央缓存种子，并写入本 skill 的 `kline-cache/daily_kline_6m.sqlite`；中央缓存、本地 SQLite 或旧 `daily_kline_6m.csv` 都不足时，才一次性拉取全 A 近 6 个月所需日 K。
2. 后续每天执行时，优先读取中央 SQLite 和本 skill 共享缓存，只对缺失或过期的代码联网拉取最近/当日 K 线窗口，用新数据与缓存按 `code,date` 去重合并。
3. 首次全量或 `--refresh-cache` 续跑时必须分批持久化；默认每 100 只股票增量写入 `daily_kline_6m.sqlite` 并更新 `daily_kline_6m.meta.json`。
4. 如果全量抓取中断，下一次带 `--refresh-cache` 运行时读取已有缓存，跳过已经有上市后 K 线且最新日期达标的股票，只继续补剩余标的；上市时间不足导致不足 90 根的股票不再反复补采。
5. 每次增量后裁剪缓存，只保留约 6 个月分析所需窗口，避免缓存无限增长。
6. 若发现缓存过旧、缺大量股票、最新 K 线日期异常或用户要求重建，运行 `--refresh-cache` 做一次全量刷新或续跑补齐。
7. 将单请求超时控制在较短范围，默认 `--request-timeout 8`；接口抖动时不要让单只股票请求长时间阻塞整批。
8. 对腾讯/东方财富仍未返回 K 线的代码，默认使用 BaoStock 做第三数据源补采；补采后仍失败的代码写入 `failed_kline_codes.csv`。
9. 报告的数据说明必须写明缓存路径、失败清单路径、更新模式（首次全量/每日增量/离线 CSV）、最新 K 线日期和失败数量。
10. 离线 CSV 模式不更新共享缓存，除非用户明确要求把本地数据导入缓存。

## 数据纪律

1. 先确认 `trade_date`，不要硬编码日期。
2. 真实全 A 筛选优先使用 `ashare-kline-sqlite-cache` 的 `stock_universe`；本地不可用时再使用东方财富全 A 列表，若东方财富列表接口不可用，回退到新浪全 A 列表。日 K 优先读取 `ashare-kline-sqlite-cache.daily_kline`，不足时再使用腾讯接口，失败时再尝试东方财富日 K，最后用 BaoStock 补采失败代码。先维护共享 K 线缓存，再从缓存参与筛选；如果接口不可用，明确说明数据缺口。
3. 本地 CSV 必须至少包含：`code,date,open,high,low,close,volume`；可选 `name,amount,pct_chg`。
4. 缓存层面对上市时间不足的股票，只要能抓到上市后的日 K 且最新日期到达筛选日即可保留；筛选层仍至少需要 90 根日 K 才能判断 6 个月趋势。
5. 最新 K 线日期如果早于 `trade_date`，必须在报告中说明，不得静默当作当日完整结果。
6. 剔除名称含 `ST`、`*ST`、退市或明显无效价格/成交量的记录，除非用户明确要求保留。
7. 不得把没有次日确认的最近一个交易日放量事件列为合格；可以单独说明为“待次日确认”。

## 规则口径

### 6个月上升趋势

默认用最近约 126 个交易日判断。至少满足以下趋势条件中的 4 项，且最新收盘价必须在 60 日均线上方：

- 近 6 个月收盘涨幅不低于 `--min-6m-return-pct`。
- 最新收盘价高于 60 日均线。
- 20 日均线高于 60 日均线。
- 60 日均线较 20 个交易日前上行。
- 最近 63 日最高价不低于前 63 日最高价，说明上方空间在抬升。

趋势条件是初筛门槛，不代表买点确认。若用户要求更严格，可把最低 6 个月涨幅、均线条件或 `--hold-by low` 调严。

### 近5日成交量翻倍

默认只认“放量上涨日”：

```text
放量日成交量 >= 前一交易日成交量 * 2
且放量日收盘价 > 前一交易日收盘价
且放量日位于最新5个交易日内
```

如果用户说“较5日均量翻倍”或“较20日均量翻倍”，改用 `--volume-base ma5` 或 `--volume-base ma20`。

### 次日不跌破当日涨幅一半

放量日涨幅按收盘价计算：

```text
放量日涨幅金额 = 放量日收盘价 - 前一交易日收盘价
半幅防线 = 前一交易日收盘价 + 放量日涨幅金额 * 0.5
```

默认合格条件：

```text
放量次日收盘价 >= 半幅防线
```

如果用户要求盘中也不能跌破，使用 `--hold-by low`：

```text
放量次日最低价 >= 半幅防线
```

## 输出格式

报告必须包含：

- `run_time`、`trade_date`、最新 K 线日期、数据来源、筛选范围、参数口径。
- 合格数量、待次日确认数量、因趋势不足或守涨失败而剔除的概况。
- 核心表格，至少包含：排名、标的、代码、最新收盘、最新 K 线日期、6个月涨幅、趋势条件、放量日、量能倍数、放量日涨幅、半幅防线、次日表现、守涨余量、观察状态。
- 逐个点评，说明趋势结构、放量性质、次日承接、支撑/失效位和主要风险。
- 数据限制与风险提示。

最后必须补充：

```text
以上为研究观察池，不构成个性化投资建议，实际交易需结合自身风险承受能力和最新行情。
```

## 输出自检

保存前检查：

- 中文 Markdown 必须为 UTF-8，不得乱码。
- 表格中的放量日必须在最近 5 个交易日内，且有次日 K 线确认。
- 放量日必须是上涨日；下跌放量不算合格。
- 次日守涨线必须使用“前收 + 当日涨幅一半”，不能误用放量日最高价回撤一半。
- 若使用本地 CSV，报告要写明是离线数据，不得声称完成实时全 A 扫描。
- 联网模式报告必须写明 `runs/ashare-volume-doubled-uptrend/kline-cache/` 下的缓存文件和本次更新模式。
- 联网模式必须生成 `failed_kline_codes.csv`，列出仍未补齐的代码、名称、缓存行数、最新 K 线日期和失败原因。
- 结果保存到 `runs/ashare-volume-doubled-uptrend/YYYY-MM-DD/YYYY-MM-DD.md`，展示给用户的内容与保存文件一致。

## 示例提示

```text
使用 $ashare-volume-doubled-uptrend，
扫描全A市场中近6个月K线处于上升趋势的标的，
要求近5个交易日内出现过成交量较前一日翻倍及以上的上涨日，
且放量后次日收盘不跌破放量日涨幅的一半。
输出研究观察池、核心表格、逐个点评、失效条件和风险提示，
首次运行时在 runs/ashare-volume-doubled-uptrend/kline-cache/ 一次性缓存近6个月日K，
后续每日运行只增量抓取当前/最近日K，
并保存到 runs/ashare-volume-doubled-uptrend/YYYY-MM-DD/YYYY-MM-DD.md。
```
