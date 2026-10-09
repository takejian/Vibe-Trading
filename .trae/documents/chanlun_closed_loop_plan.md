# 缠论技术面分析闭环（结论卡 → 对比 → 事后验证 → 评价）实施方案

## 一、需求理解（来自用户原话）

在「关注 → 个股详情 → 技术面」tab 中，以 **chanlun（缠论）角色**为核心完成分析，并对分析结果做闭环：

1. **重点突出**：当前报告结论太多、没有重点，用户看不到"现在该干什么"——需要核心结果卡 + 明确操作建议。
2. **跨期对比**：明显看出同一标的不同时期分析结论的区别。
3. **好坏可判**：能判断历史分析结论的质量（事后行情验证 + 用户评价）。
4. **可操作 + 可复盘**：知道怎么操作，且能事后评价分析准确性。

本期范围：**仅围绕 chanlun 角色**（`technical_analysis_panel:chanlun_analyst`），但数据契约设计为未来可扩展到其他技术角色。纯研究/只读功能，不触碰 live 下单、mandate、kill switch 等高风险面。

---

## 二、仓库调研结论（现状）

### 已有的链路（大部分地基已存在）

- 前端技术面 tab：[WatchDetail.tsx](file:///home/ai/Vibe-Trading/frontend/src/pages/WatchDetail.tsx#L328-L339) 依次渲染
  `AnalysisTab`（选角色→发起 role run→历史列表，展开为整篇 Markdown 报告）、`KlineChartPanel`、`ChanlunHistory`（仅 时间/打分/置信度 三列，展开为 7 个维度的 Markdown）。
- chanlun 角色提示词：[technical_analysis_panel.yaml](file:///home/ai/Vibe-Trading/agent/src/swarm/presets/technical_analysis_panel.yaml#L234-L410)，强制 7 段式输出（结构/中枢/背驰/买卖点/多级别计划/艾略特验证/打分 + 置信度）。
- 严格解析器：[chanlun_parser.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/chanlun_parser.py)，7 段或分数/置信度不合规即返回 `None`，降级存档 `structured=false`。
- DuckDB 持久化：[db.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/db.py#L84-L103) 表 `chanlun_analysis`（run_id 唯一幂等，7 个 dim 大文本 + score(-5..5) + confidence(0..1) + raw_report）。
- 归档时机：[analysis.py `persist_run_artifacts`](file:///home/ai/Vibe-Trading/agent/src/watchlist/analysis.py#L359-L442)，在 GET `/objective`、`/analyses`、`/chanlun` 时**懒归档**，按 run_id 幂等；路由见 [watchlist_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/watchlist_routes.py#L467-L492)。
- 行情前提：chanlun 运行前有日/周/月/季/年 K 线齐备性软门禁（412 提示，可跳过）；多级别 K 线已落 `watch_kline_bar`；仓库另有 `daily_bar` 可用于事后验证。
- 可复用先例：[scheduled_research/verdict.py](file:///home/ai/Vibe-Trading/agent/src/scheduled_research/verdict.py) ——「报告尾部机读块 + 严格解析 + 不合规降级 `contract_violation` + 内嵌 previous 做 delta」的成熟模式；DB 侧已有 `ALTER TABLE ADD COLUMN` 式增量迁移先例（[db.py:170](file:///home/ai/Vibe-Trading/agent/src/watchlist/db.py#L170-L179)）。

### 与目标的差距（本方案要补的环）

| 差距 | 现状 | 闭环要求 |
| --- | --- | --- |
| 核心结论 | 只有 score/confidence 两个标量 + 7 段长文 | 机读「操作结论卡」：方向/动作/触发价/止损/目标/有效期/失效条件 |
| 基准价 | 不记录分析时价格 | 存档 base_price/base_date，作为事后验证基准 |
| 操作建议 | 藏在 dim5 长文里 | 卡片置顶、徽章化、给出 R/R 与"等待/可做/失效"状态 |
| 跨期对比 | 单表按时间倒序 | 选 2~N 次分析做字段级 diff + 分数/方向演变时间线 |
| 事后验证 | 无 | 到期按日线行情机械判定：止盈/止损/未触发/方向对错/MFE-MAE |
| 用户评价 | 无 | 准确/部分/错误 + 备注；与机器验证分开保存、合并展示 |
| 质量统计 | 无 | 胜率、目标达成率、分数段校准、按买卖点类型分组 |
| 默认角色 | 技术面角色下拉默认空 | technical 分类下默认选中 chanlun |

---

## 三、目标方案：四段式闭环

```
 ① 分析出卡                ② 看得懂/能操作              ③ 跨期对比
 chanlun run 完成   →     最新结论卡(置顶徽章)    →    选 N 次分析字段级 diff
 尾部追加机读 JSON         触发/止损/目标/R/R           分数·方向演变时间线
 严格解析+降级存档          状态:待触发/有效/失效        中枢/买卖点变化高亮
        │                         │                          │
        └─────────────── ④ 事后复盘（自动+人工）──────────────┘
                  到期用日线机械判定胜负/MFE/MAE
                  + 用户打分评价 → 准确率与校准统计
                  反哺：提示词按失败类型迭代（本方案仅产出数据）
```

### 3.1 提示词改造：新增第 8 段「操作结论卡」

在 [technical_analysis_panel.yaml](file:///home/ai/Vibe-Trading/agent/src/swarm/presets/technical_analysis_panel.yaml) 的 `chanlun_analyst.system_prompt` 中：

- 保留现有 1–7 段与全部 ASCII 图要求不变（兼容已存档数据与现有测试）。
- 新增 **第 8 段（必需）**：固定标题 `8. 操作结论卡 / Action Card`，正文必须且只能是一个 ```json 代码块，schema：

```json
{
  "schema_version": 1,
  "base_price": 23.76,
  "base_date": "2026-10-08",
  "direction": "bullish",            // bullish | bearish | neutral
  "action": "buy",                   // buy | add | hold | reduce | sell | wait
  "confidence_pct": 62,
  "setup_class": "3买",              // 1买/2买/3买/1卖/2卖/3卖/none
  "horizon_days": 20,                // 预计兑现的交易日数
  "trigger_price": 24.10,            // 触发/介入价；wait/neutral 时为 null
  "stop_price": 23.20,               // 失效价（中枢 ZG/ZD 外侧）
  "target_prices": [25.60, 27.20],   // T1/T2
  "rr_at_t1": 1.8,                   // 触发价口径的首目标盈亏比
  "invalidation": "收盘站回中枢下沿23.20下方且30m出现反向分型",
  "key_risks": "大盘系统性回调；30m 数据盲区",
  "one_liner": "日线三买待确认，24.10 放量突破触发，破 23.20 失效"
}
```

硬约束（写进提示词）：

- 所有数字必须来自 `objective_kline`/`czsc` 实读数据，禁止编造（沿用现有 HARD RULE 措辞）。
- `direction=neutral` 或 `action=wait` 时 trigger/stop/target 必须为 `null`，不得硬给价位。
- JSON 不得含注释/尾逗号；`one_liner` 一句话、≤60 字。
- 卡片中的 score 语义与第 7 段一致（方向=分数符号，动作映射由后端做，不让 LLM 自由发挥动作词表）。
- 给 1 个正例 + 1 个 neutral 例（few-shot），降低不合规率。

### 3.2 解析与存储（后端）

**新模块** `agent/src/watchlist/action_card.py`（风格对齐 verdict.py：纯函数、严格、三态）：

- `parse_action_card(report) -> {parse: ok|no_card|contract_violation, card: dict|None}`
- 校验：JSON 可解析、枚举值合法、价格为正数、stop 在触发价错误方向时判 violation、horizon 1~120 交易日、confidence 0~100。
- 与 7 段解析**相互独立**：7 段失败不影响卡片，卡片失败不影响 7 段；两个 parse 标志分别存档。

**改造** [chanlun_parser.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/chanlun_parser.py)：第 7 段正文在 `## 8.` / 卡片标记处截断，避免 JSON 内的 `"score": n` 干扰现有分数/置信度正则；旧报告（无第 8 段）行为不变，旧测试不动。

**DuckDB schema 增量（只加列、只加表，可重复迁移）**，在 [db.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/db.py) `_DDL` + 迁移函数：

`chanlun_analysis` 增列（均可空）：
`base_price, base_date, direction, action, setup_class, confidence_pct, trigger_price, stop_price, target_prices(JSON), rr_at_t1, horizon_days, invalidation, key_risks, one_liner, card_json, card_parse`。

新表 `chanlun_outcome`（1:1，run_id 唯一）：

```
run_id(PK/UQ), symbol, eval_status,            -- pending|insufficient_data|verified|expired
window_end_date, target_hit, stop_hit,
first_event,                                    -- target_first|stop_first|neither
mfe_pct, mae_pct, exit_return_pct,             -- 窗口内最大有利/不利幅度、期末收益
direction_correct, outcome_label,              -- win|loss|partial|timeout_correct|timeout_wrong|neutral
evaluated_at,
user_verdict,                                   -- accurate|partial|wrong|NULL
user_note, user_rated_at
```

- `persist_run_artifacts` 归档 chanlun 时同时解析卡片并写入新列；`base_price` 缺失时用存档日线收盘价回填，仍缺则 NULL（不发起网络请求）。
- 懒验证：列表/统计接口读取时，对 `eval_status in (pending)` 且 `base_date + horizon_days <= 最新可用日线日期` 的记录，用仓库行情机械复算（与懒归档同一套调用风格）；行情不足 → `insufficient_data`，不阻塞页面。验证只读 `daily_bar`/`watch_kline_bar(1d)`，**不触网**。

**机械判定规则（写入代码 docstring + 前端提示文案）：**

1. 仅多/空方向参与胜负；neutral/wait 记 `neutral`（只统计"若跟随"的方向参考价值，不判胜负）。
2. 窗口 = base_date 之后 horizon_days 个交易日（无 horizon 默认 20）。
3. 多头：日内 low≤stop → 止损；high≥target(T1) → 止盈；两者都触及按**先发生者**定胜负，后发生者记入备注；都未触及 → 期末涨跌判方向对错。空头镜像。
4. MFE/MAE 用窗口内最高/最低相对 base_price；`partial` = 先达 T1 后触止损。
5. A 股涨跌停无法成交的偏差在文档注明（当前按"触及即成交"的保守可实现假设），后续版本可用涨跌停标记细化。

**质量统计**（新模块 `agent/src/watchlist/outcome.py`）：样本数、方向准确率、T1 达成率、止损率、平均 MFE/MAE、按 setup_class 分组、按 score 分桶（-5..-1/+1..+5）的实际胜率做**校准表**、人工评价分布；只统计窗口已完结记录。

### 3.3 API（[watchlist_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/watchlist_routes.py) 增量，全部沿用 `require_auth` 与现有错误映射）

| 方法/路径 | 作用 |
| --- | --- |
| `GET /watch/{symbol}/chanlun/cards?limit=` | 结论卡列表（含每张卡的最新 outcome/status），首页用 |
| `GET /watch/{symbol}/chanlun/cards/latest` | 最新一张卡（技术面进入即用） |
| `GET /watch/{symbol}/chanlun/compare?runs=r1,r2[,r3]` | 所选记录的卡片字段 + 7 维原文，服务端标好字段差异类型（up/down/changed/same） |
| `POST /watch/{symbol}/chanlun/{run_id}/rating` | body `{verdict: accurate\|partial\|wrong, note?}`，写 `chanlun_outcome` |
| `GET /watch/{symbol}/chanlun/stats` | 上述质量统计（单股）；全局统计可复用同一 service 加 `scope=global` |
| `POST /watch/{symbol}/chanlun/outcome/refresh` | 强制重算到期记录（可选；默认懒计算已够） |

原有 `/watch/{symbol}/chanlun` 返回中追加卡片字段与 outcome 摘要，保持向后兼容（前端旧字段不动）。

### 3.4 前端改造（React，i18n 需同步 9 个 locale 文件）

1. **默认角色**：[AnalysisTab.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/watch/AnalysisTab.tsx) 加载 agents 后，technical 分类默认选中 is_chanlun 角色。
2. **新组件 `ChanlunActionCard.tsx`（结论卡，置于技术面 tab / 缠论历史顶部）**：
   - 大徽章：方向（红涨绿跌沿用项目配色 [ChanlunHistory.tsx:75](file:///home/ai/Vibe-Trading/frontend/src/components/watch/ChanlunHistory.tsx#L75-L78)）+ 动作（买入/加仓/持有/减仓/卖出/观望）+ 置信度；
   - 关键数字行：现价/触发价/止损/目标 T1·T2/RR/有效期；失效条件一行；一句话结论；
   - 状态 pill：待触发 / 有效 / 已止盈 / 已止损 / 已过期 / 数据不足；已验证记录直接显示胜负结果；
   - 卡片缺失（`card_parse≠ok`）显示"本次未产出合格操作卡"——这本身就是质量信号；
   - 「查看完整报告」进入现有 RunView/7 维展开。
3. **`AnalysisTab` 历史行增强**：chanlun run 的历史行在时间/状态旁显示迷你卡摘要（动作徽章 + 触发/止损），不再只有时间戳与绿勾。
4. **`ChanlunHistory.tsx` 升级**：
   - 行：时间、方向/动作徽章、score、置信度、**状态**、**结局**（胜/负/部分/待验证 + MFE/MAE）、我的评价；
   - 顶部：迷你时间线（echarts 已在工程内：score 折线 + 方向切换标记 + 止盈止损点）；统计条（n 次、胜率、T1 达成率）；
   - **对比模式**：勾选 2~4 行 → 侧并排字段表（数字涨跌着色）、中枢区间/买卖点/分数/方向变化高亮、7 维文本逐段折叠对照（文本做简单差异提示：变更/不变）；
   - **评价操作**：窗口已完结或过期的记录出现 👍准确 / 🟰部分 / 👎错误 + 备注，提交后展示；自动验证结果与用户评价并列（允许不一致，两者都保留）。
5. 类型与请求：[api.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts#L2598-L2621) 增 `ChanlunActionCard / ChanlunOutcome / ChanlunStats / CompareRows` 等类型与 5 个方法；i18n key 挂在现有 `watch.ch.*` 下（`card/compared/verify/rating/stats` 等命名空间）。

### 3.5 不做什么（边界）

- 不自动下单、不接 mandate/kill switch、不产生任何 live 动作；全部为信息展示。
- 本期不做定时自动重跑缠论（手动"开始分析"已满足跨期采样；未来可在 [scheduled_research](file:///home/ai/Vibe-Trading/agent/src/scheduled_research) 体系里加 playbook，届时卡片契约可直接复用）。
- 不改其他 5 个技术角色的提示词；对比/验证 UI 仅消费 chanlun 数据。
- 不做报告正文的 LLM 二次摘要（核心信息靠机读卡，避免再引入一层不确定性）。

---

## 四、涉及文件

**后端**

- [agent/src/swarm/presets/technical_analysis_panel.yaml](file:///home/ai/Vibe-Trading/agent/src/swarm/presets/technical_analysis_panel.yaml)：chanlun 提示词加第 8 段卡片契约 + 示例。
- `agent/src/watchlist/action_card.py`（新）：卡片严格解析/校验。
- [agent/src/watchlist/chanlun_parser.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/chanlun_parser.py)：第 7 段截断兼容第 8 段。
- [agent/src/watchlist/db.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/db.py)：增列迁移、`chanlun_outcome` DDL 与 CRUD。
- `agent/src/watchlist/outcome.py`（新）：日线机械验证 + 统计聚合。
- [agent/src/watchlist/analysis.py](file:///home/ai/Vibe-Trading/agent/src/watchlist/analysis.py)：归档时解析卡片、回填基准价、触发懒验证。
- [agent/src/api/watchlist_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/watchlist_routes.py)：5 个新接口 + 旧接口字段追加。

**前端**

- [frontend/src/lib/api.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts)：类型与方法。
- `frontend/src/components/watch/ChanlunActionCard.tsx`（新）。
- [ChanlunHistory.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/watch/ChanlunHistory.tsx)：状态/结局/评价/对比/时间线/统计。
- [AnalysisTab.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/watch/AnalysisTab.tsx)：默认选中 chanlun + 历史行迷你卡。
- `frontend/src/i18n/locales/*.json`（9 个）：新增文案。

**测试**

- 扩展 `agent/tests/test_chanlun_parser.py`，新增 action card / outcome / routes 测试（参照现有 `test_watchlist_*.py` 风格）；前端扩展 `ChanlunHistory.test.tsx`、`AnalysisTab.test.tsx`。

---

## 五、实施步骤（依赖顺序）

1. 提示词加第 8 段契约（yaml），用真实 run 或离线夹具验证模型输出合规率并微调示例。
2. `action_card.py` 解析器 + 单测（含 no_card / violation / neutral 各路径）。
3. `chanlun_parser.py` 兼容截断 + 旧测试回归。
4. `db.py` 增列/新表迁移与 CRUD；旧 DuckDB 文件升级验证。
5. `analysis.py` 归档链路接入卡片与基准价回填。
6. `outcome.py` 机械判定（合成日线夹具覆盖：止盈先到/止损先到/都不到/数据不足/空头镜像）+ 统计。
7. 新 API 5 个端点 + 旧端点字段追加，路由测试。
8. 前端 api 类型 → 结论卡组件 → 历史升级（状态/评价/统计）→ 对比模式 → 时间线。
9. i18n 9 语言补齐；`npm run build` 与 vitest。
10. 端到端手测：关注一只股票 → 跑缠论 → 出卡 → 再次分析 → 对比 → 构造到期数据验证结局 → 用户评价 → 看统计。

## 六、验证

- `make lint`（层依赖：新模块均在 L2，watchlist 不反向依赖 swarm；`outcome.py` 只读 db/market）。
- `make test-fast`：watchlist 全套（db/analysis/routes/kline/role_filter）+ 新 parser/outcome 测试。
- 前端 `npm run build`、vitest（watch 组件 + 快照）。
- 手工回归：旧格式报告（无第 8 段）仍正常展示且 card 缺失态正确；跳过 K 线门禁的分析也能归档出卡。

## 七、风险与处理

- **模型不按契约输出 JSON**：三态降级 + UI 明确"未产出合格卡片"；提示词 few-shot；用 `card_parse` 合规率作为后续提示词迭代指标，绝不前端/后端补造数字。
- **提示词↔解析器耦合**：卡内带 `schema_version`；解析器对未知字段宽容、对契约字段严格。
- **老库迁移**：仅 `ADD COLUMN`（可空）+ 新表，幂等迁移；沿用现有迁移函数模式。
- **验证行情不足**：`insufficient_data/pending`，页面不报错；只读本地仓库不触网，离线测试稳定。
- **用户评价主观偏差**：自动结局与人工评价分字段存放、并列展示；统计默认以自动结局为准、人工评价单列。
- **涨跌停成交假设**：文档与 UI 注明"触及价"口径，后续用日线涨跌停标记细化，不影响本期上线。
- **i18n 体量**：9 个 locale 必须同步，前端有对应测试约束。
