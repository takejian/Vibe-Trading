---
name: chanlun-bi-analysis
description: Run the chanlun_analyst pipeline for an A-share symbol — objective_kline, czsc bi/zhongshu/divergence, gap-free ASCII bi charts, strict 8-section report (7 analytical sections + machine-readable Action Card JSON) to DuckDB. Use for 缠论/笔/中枢/背驰/买卖点 analysis by stock code. Not for fundamentals or live orders.
---

# 缠论（Chanlun）个股多级别分析流程

你在本流程中扮演 `technical_analysis_panel:chanlun_analyst` 角色里的"分析师大模型"。角色权威提示词：[technical_analysis_panel.yaml](file:///home/ai/Vibe-Trading/agent/src/swarm/presets/technical_analysis_panel.yaml)（chanlun_analyst.system_prompt，含图形、7 段正文规范与第 8 段机读操作结论卡契约）；本技能是该角色的可复跑操作手册。输入一个 A 股代码（如 `300014.SZ`），输出一份 **8 段报告**（7 段分析正文 + 第 8 段操作结论卡 JSON）并入库。**全程只做技术分析，不做下单/持仓操作。**

## 流程总览

1. objective_kline 取「客观数据」存档（6 级别，缺/旧自动联网补抓）
2. czsc 结构扫描（去包含→分型→笔→中枢→每笔 MACD 红绿柱面积）
3. 你做分析师裁决：背驰 → 三类买卖点 → 多级别联立 → Elliott 次级验证 → 打分
4. 生成「笔为核心、笔笔连续连线、一笔不缺」的 ASCII 图
5. 按固定 8 段契约写报告（1–7 分析段 + 第 8 段机读操作结论卡，先过两个解析器）
6. 两个解析器都通过后写入 DuckDB `chanlun_analysis` 历史表（含操作结论卡字段）并回查

一律用仓库根目录的 `/home/ai/Vibe-Trading/.venv/bin/python`（czsc 1.0.1 装在其中）。

## 1. 取数（必须走项目工具，禁止外部脚本直连行情）

- 工作目录约定 `/tmp/vt_analysis/<slug>/`（slug 如 `eve`），每个级别存档为 `<level>.json`。
- 调用项目工具 `agent/src/tools/objective_kline_tool.py`（ObjectiveKlineTool），级别 `30m/1d/1w/1mo/1q/1y`，`refresh` 保持默认 `auto`：
  - 冷启动（`not_fetched`/0 根）或过期时**自动联网抓取并 upsert 本地存档**，返回里 `refreshed=true`；抓不到时工具报错而不是给假数据——**绝不编造价格**。
  - 把每个级别返回的完整 payload（含 `bars/level_status/source/bars_count`）原样存 JSON。
  - 若标的不在关注列表导致取数失败，先加入 watchlist 再取。
- 必须在报告开头如实记录：每级别状态、source、根数、起止日期。30m 数据源窗口差异大（eastmoney 往往只回溯数周），窗口受限时在图注与正文**显式声明**；30m 不按新鲜度卡门。
- 季线：czsc 1.0.1 **没有季线 Freq**，1q 只做原始极值读取；月/年若 <12 根同样只做 raw read。

## 2. 结构扫描（确定性脚本）

```bash
cd /home/ai/Vibe-Trading && .venv/bin/python \
  .trae/skills/chanlun-bi-analysis/scripts/czsc_scan.py \
  /tmp/vt_analysis/<slug> --levels 30m,1d,1w,1mo,1y --last 30 --symbol 300014.SZ
```

输出：每级别中枢（zg/zd/zz/gg/dd、笔数、起止）、全部近期笔（端点价/方向/该笔 MACD 柱面积/endDIF）、未完成笔根数与 live 红绿柱面积、最新 DIF/hist；日线另给 MA5/10/20/60/120/250、量比、RSI6、一年区间。另存档完整输出（如 `<slug>_scan.txt`）供写报告引用。**面积/DIF 数字必须来自该扫描输出，不得手算臆造。**

## 3. 分析师裁决（你的核心职责，脚本不替代）

- **背驰判定**：同级别同向笔之间比较——价格创新低/高，而 MACD 柱面积收缩（最好 endDIF 同步抬高/压低）。区分：
  - *趋势背驰*：跨两个以上同向移动中枢的同向笔面积逐级衰减 → 一买/一卖候选，质量最高；
  - *盘整背驰*：围绕单个中枢 → 按缠论定理**只保证回拉中枢**，不保证反转；面积收缩但 DIF 不配合时要明确写"可靠性打折"。
  - 次级别最近下笔面积放大 = 无背驰，区间套不成立，如实写。
- **成笔确认纪律**：只有反向分型、反向笔未成 = 信号标记「待确认/形成中」，不得直接说一买成立；给出确认触发价与失效价。
- **三类买卖点**：1 类＝背驰极值点；2 类＝1 类后的第一次反向回抽不破前极值；3 类＝突破中枢后回抽不回中枢。无信号的级别明确写「无买卖点」。下跌途中已兑现的三卖可列出。
- **多级别联立**：周线＝高级别 regime，日线＝本级别结构，30m＝次级别择时；月/年定大背景。给出区间套是否成立、激进/稳健/右侧三套方案（入场区、T1..Tn、总止损、仓位上限、复核条件），结尾注明"技术分析非投资建议"。
- **Elliott 仅次级验证**：自行用存档价算 W1-W4 幅度与 Fib 回撤（0.382/0.5/0.618/0.786），检查三铁律（2 不破 1 起点、3 非最短、4 不进 1 价格区）；任一 FAIL 要写明，结论与缠论冲突时**以缠论为准**。
- **打分**：score 为 -5..+5 整数，confidence 0-100%。第 7 段列出加分明细（背驰质量/多级别共振/次级别结构/均线）与减分明细（未确认/DIF 不配合/大级别无背书/均线空头/上方套牢压制），让分数可追溯。

## 4. 图形：笔为核心、笔笔连续、一笔不缺

图形库：[scripts/bi_charts.py](file:///home/ai/Vibe-Trading/.trae/skills/chanlun-bi-analysis/scripts/bi_charts.py)。硬性要求（与角色提示词一致）：

- 笔折线是**一条无断点连续链**：平段 `─`、陡段纵向补 `│`、对角 `╱╲`、未完成笔 `╌╎`；每个 ● 节点两侧都必须有连线汇入；**笔线无条件覆盖中枢底色**（穿 `░`/`═` 不得间断）。
- 每级别都要有「全部笔一行序列（↗↘，含日期/价格/未完成笔）」；笔数多时再加当前走势段的价格轴网格。任何笔不得省略或合并。
- 每张网格配：标题（级别+笔数+日期窗口）、图例、中枢 ZG/ZD 说明、**带日期价格的节点明细表**；标记 ▲1买/▼1卖 等打在准确节点上；`┈` 现价虚线；30m 窗口短要在图注声明。

生产报告时写一个临时 driver 脚本（curated pivots/markers 比自动识别准确），最小形态：

```python
import json, sys
sys.path.insert(0, '.trae/skills/chanlun-bi-analysis/scripts')
from bi_charts import build_czsc, bi_chains, bi_grid, node_table
c, _ = build_czsc(json.load(open('/tmp/vt_analysis/<slug>/1w.json')), '1w')
g, _, _ = bi_grid(c,
    pivots=[('ZS-W2', 75.72, 57.90), ('ZS-W1', 41.77, 31.88)],  # (label, zg, zd)
    markers={9: '▼', 12: '▲'}, current_price=49.81,
    width=104, height=20, tail=None, title='周线…全部N笔+未完成笔')
print(g)
print('节点明细：' + '；'.join(f'{i+1}={d} {p:.2f}({k})'
      for i, (d, p, k) in enumerate(node_table(c))))
```

CLI 快速预览（自动取 `c.zs_list` 当中枢、无标记）：`.venv/bin/python .../bi_charts.py <payload.json> 1d --tail 20`。图形嵌入报告时一律用 ```` ```text ```` 代码块——前端 MarkdownContent 只渲染 GFM（表格/代码块），**不支持 mermaid/图片**。

## 5. 八段报告契约（7 分析段 + 第 8 段操作结论卡）

模板：[assets/report_template.md](file:///home/ai/Vibe-Trading/.trae/skills/chanlun-bi-analysis/assets/report_template.md)；解析器完整规则与踩坑：[references/report-contract.md](file:///home/ai/Vibe-Trading/.trae/skills/chanlun-bi-analysis/references/report-contract.md)。要点：

- 7 个编号标题按序出现、标题含约定关键词（1 结构 / 2 中枢或支点 / 3 背驰 / 4 买卖 / 5 多级别 / 6 艾略特 / 7 打分），每段非空。
- 第 7 段必须含且只以该段最后出现的数字为准：
  - `缠论打分 Chanlun score：+1 / 5`（整数 -5..+5）
  - `结构置信度 Confidence：58%`
- 报告开头写明流程、取数实测（冷启动自动抓数的级别/source/根数/窗口）、截止收盘价与量能背景；所有价位用存档前复权价。

### 第 8 段：操作结论卡 / Action Card（机读，必需）

7 段正文之后**必须**追加标题 `## 8. 操作结论卡 / Action Card`，标题正文里**有且仅有一个** ```` ```json ```` 代码块——无注释、无尾逗号、代码块外不写任何散文。卡片是给软件/前端直接渲染用的"现在该怎么做"，每个数字同样必须来自存档 K 线/扫描输出，算不出就填 `null`，绝不臆造。字段契约（与角色提示词逐字一致）：

| 字段 | 约束 |
|---|---|
| `schema_version` | 整数 `1` |
| `base_price` / `base_date` | 分析时点最新收盘价（number）/ 交易日 `YYYY-MM-DD` |
| `direction` | `bullish` / `bearish` / `neutral` |
| `action` | `buy` / `add` / `hold` / `reduce` / `sell` / `wait` |
| `confidence_pct` | 0–100 整数，**必须与第 7 段 Confidence 同值** |
| `setup_class` | `1买`/`2买`/`3买`/`1卖`/`2卖`/`3卖`/`none` |
| `horizon_days` | 整数 1–120（短线 10–20，波段 20–60） |
| `trigger_price` | 触发/入场价，number 或 null（未触发突破单挂计划价，别假设按 base_price 成交） |
| `stop_price` | 失效/止损价，number 或 null（多头必须低于 trigger，空头高于） |
| `target_prices` | 1–3 个严格递增（多头）/递减（空头）数字数组，或 null |
| `rr_at_t1` | `(T1-trigger)/(trigger-stop)` 保留 2 位小数，或 null |
| `invalidation` | 一行字符串：什么价格/结构杀掉本结论 |
| `key_risks` | 一行字符串：主要风险（含数据盲区） |
| `one_liner` | 一句话 headline，≤60 个汉字 |

一致性硬规则（解析器机械校验，违反即 `contract_violation`）：

- `direction=neutral` 或 `action=wait` → `trigger_price/stop_price/target_prices/rr_at_t1` 全部 null 且 `setup_class="none"`。
- `bullish`：action ∈ {buy, add, hold, wait}，setup 只能是买点或 none；`bearish` 镜像（sell/reduce + 卖点）。
- 一旦给出任一价位，trigger 与 stop 必须同时存在，且多空方向、目标价排序必须自洽。

提示词中的两个范例（bullish / neutral）见 YAML 的 `Action Card contract` 段，只学形状不要照抄价格。

## 6. 先解析、后入库

写临时入库脚本（参照历史 `/tmp/vt_analysis/save_eve_report.py` 模式）：

```python
import sys; sys.path.insert(0, '/home/ai/Vibe-Trading/agent/src')
from datetime import datetime
from src.watchlist.db import watchlist_connection, initialize_schema, insert_chanlun_record
from src.watchlist.chanlun_parser import parse_chanlun_report
from src.watchlist.action_card import parse_action_card
parsed = parse_chanlun_report(REPORT)
assert parsed, 'ABORT: 7 段契约不满足，回去改报告，不要 structured=false 兜底'
card_result = parse_action_card(REPORT)
assert card_result['parse'] == 'ok', (
    f"ABORT: 第 8 段操作结论卡不合规({card_result['parse']}): {card_result['error']}，回去改卡")
run_id = f"manual-role-chanlun-{datetime.now():%Y%m%d%H%M%S}-300014"
conn = watchlist_connection(); initialize_schema(conn)
insert_chanlun_record(run_id=run_id, symbol='300014.SZ', conn=conn,
    dims=parsed['dims'], score=parsed['score'],
    confidence=parsed['confidence'], structured=True,
    raw_report=REPORT, analyzed_at=datetime.now(),
    card=card_result['card'], card_parse=card_result['parse'])
```

- API：`agent/src/watchlist/db.py`（`watchlist_connection/initialize_schema/insert_chanlun_record`），7 段解析器 `agent/src/watchlist/chanlun_parser.py`，操作结论卡解析器 `agent/src/watchlist/action_card.py`（返回 `ok` / `no_card` / `contract_violation` 三态；新报告必须 `ok`）。
- 入库时卡片字段随报告一起落库（`base_price/direction/action/setup_class/trigger_price/stop_price/target_prices/...` 与 `card_parse` 状态列）。
- 每次运行生成新 run_id；入库后用 SELECT 回查最新行（score/confidence/structured/card_parse/direction/action/长度）。
- DuckDB DELETE rowcount 显示 -1 是正常现象。
- 未改前端代码时无需跑 vitest/tsc；若改了渲染组件，跑 `frontend` 下 ChanlunHistory 测试与 `npx tsc -b`。

## 环境硬约束与已踩过的坑

- czsc **1.0.1**：无 `Freq.Q`（季线 raw-only）；中枢属性小写 `zg/zd/zz/gg/dd`；`int(bi.direction)==0` 为向上；pandas 行用 `row['dt']` 字典访问（`.dt` 属性会报错）；未完成笔在 `c.bars_ubi`。
- 所有 Python 用 `/home/ai/Vibe-Trading/.venv/bin/python`，命令从仓库根目录发起。
- MACD 口径固定 (12,26,9)：DIF=EMA12−EMA26，hist=DIF−DEA9；向上笔取区间正柱和、向下笔取负柱和。
- 数字（面积/DIF/价位/均线）只引用扫描输出与存档 K 线，不同数据源窗口不可混用为背驰证据。
- 正文里避免出现形如 `3. 背驰…` 的独立编号行（可能被解析器误判为标题）；标题级别统一用 `##`。
- 报告完成后自查：① 7 段齐全且 `parse_chanlun_report` 返回非 None；② 三个时间级别全笔序列与网格齐备、节点数=笔数+1(+未完成笔)；③ 每个买卖点都有触发价/失效价；④ 30m/季线窗口限制已声明；⑤ 第 8 段操作结论卡 `parse_action_card` 返回 `ok`（JSON 合法、confidence_pct 与第 7 段一致、价位方向自洽、neutral/wait 全 null）；⑥ 入库回查成功（含 card_parse=ok）。
