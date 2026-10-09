# 报告解析契约（parse_chanlun_report + parse_action_card）

报告 = 1–7 分析段 + 第 8 段操作结论卡。入库前**必须同时**通过两个解析器：`agent/src/watchlist/chanlun_parser.py`（7 段正文，返回 `None` 时改报告，不要以 `structured=false` 入库）与 `agent/src/watchlist/action_card.py`（第 8 段卡片，新报告必须 `parse == "ok"`）。

## 维度键（固定顺序，不可调）

| # | 标题关键词（CN/EN，任一即可） | dims 键 |
|---|---|---|
| 1 | 结构 / structure | `structure_read` |
| 2 | 支点 / 中枢 / pivot / zhongshu | `active_pivots` |
| 3 | 背驰 / divergence | `divergence` |
| 4 | 买卖 / buy / sell | `buy_sell_points` |
| 5 | 多级别 / multi-level / multilevel / plan | `multi_level_plan` |
| 6 | 艾略特 / elliott | `elliott_corroboration` |
| 7 | 打分 / 评分 / score | `chanlun_score` |

## 标题识别规则

正则：`^[\s>#]{0,6}\**\s*([1-7]|[一二三四五六七])\s*[.、)）：:．]\s*(标题文字)$`

- 编号必须**按 1→7 顺序**出现；编号对不上或标题不含该段关键词的行会被跳过（所以正文里不要写独立的 `3. 背驰…` 这类伪标题）。
- 推荐统一写法：`## 1. 结构读取 Structure read（…）`。
- 7 段正文都必须非空（第 7 段也不能只有标题）。

## 分数 / 置信度

- 分数正则取第 7 段**最后一个**匹配：`(缠论打分|…|score)\s*[:：=]\s*([+-−]?\d)(\s*/\s*5)?`
  - 整数、范围 -5..+5；`+1` 与 `1` 等价（存储去符号）。全角/半角冒号均可。
  - 推荐固定行文：`缠论打分 Chanlun score：+1 / 5`
- 置信度：先找百分比 `(结构置信度|confidence)…(\d+(\.\d+)?)%`（0-100 → 自动 /100）；找不到再接受 0-1 小数。
  - 推荐固定行文：`结构置信度 Confidence：58%`

## 第 8 段：操作结论卡（parse_action_card）

实现：`agent/src/watchlist/action_card.py`，入口 `parse_action_card(report) -> {"parse", "card", "error"}`，三态：

| parse | 含义 | 处置 |
|---|---|---|
| `ok` | JSON 合法且通过全部一致性校验，`card` 为归一化字典 | 随报告入库 |
| `no_card` | 报告没有第 8 段标题/没有 fenced JSON（仅契约上线前的老报告可能出现） | 新报告不允许；补卡片再入库 |
| `contract_violation` | 有第 8 段但 JSON 非法、非 object 或违反硬规则，`error` 给原因 | 按 error 改卡，禁止用假数字"修复" |

### 标题与正文识别

- 标题正则与 1–7 段同形：`^[\s>#]{0,6}\**\s*(8|八)\s*[.、)）：:．]\s*(标题)$`，标题必须含关键词 `操作结论卡/结论卡/action card/action/卡片` 之一。推荐固定写法：`## 8. 操作结论卡 / Action Card`。
- 正文取该标题之后的全部文本；`parse_action_card` 抓其中**第一个** fenced 代码块（```` ```json ```` 或裸 ```` ``` ````，围栏后必须换行），所以第 8 段正文里**只放一个** JSON 块，不要贴范例/解释。
- `chanlun_parser` 切第 7 段正文时会在第 8 段标题处截断——卡片里的 `confidence_pct` 等数字绝不会污染第 7 段 score/confidence 正则；反过来，不要把卡片内容写进第 7 段。

### 字段与硬规则（机械校验）

- 枚举：`direction ∈ bullish|bearish|neutral`；`action ∈ buy|add|hold|reduce|sell|wait`；`setup_class ∈ 1买|2买|3买|1卖|2卖|3卖|none`。
- 数值：`base_price` 正数；`base_date` 真实日期 `YYYY-MM-DD`；`confidence_pct` 0–100（且须与第 7 段 Confidence 同值）；`horizon_days` 整数 1–120；`target_prices` 1–3 个正数；`rr_at_t1` ≥0（解析器四舍五入到 2 位）；文本 `invalidation` 非空、`key_risks` 可空、`one_liner` 非空（解析器长度上限分别 400/400/120 字符；角色提示词要求 one_liner ≤60 汉字，按提示词从严）。
- `neutral` 或 `wait`：`trigger_price/stop_price/target_prices/rr_at_t1` 必须全为 `null`，且 `setup_class="none"`。
- `bullish`：action ∈ {buy, add, hold, wait} 且 setup 为买点或 none；`bearish`：action ∈ {sell, reduce, hold, wait} 且 setup 为卖点或 none。
- 任一价位非 null 即"有价卡片"：trigger/stop 必须同时存在；多头 stop < trigger、targets 全部 >trigger 且严格递增；空头镜像。
- JSON 必须是 object、可被 `json.loads` 解析；多余字段允许但会被忽略。

## 前端渲染约束

- 历史记录在 `frontend/src/components/watch/ChanlunHistory.tsx` 以 `<MarkdownContent>` 渲染：支持 GFM 表格与代码块高亮，**不支持 mermaid、不支持图片**——图形只能是 ```` ```text ```` 里的 ASCII。
- 每个 ASCII 图前后留空行，代码块闭合后再写解读文字。
- 中文字段在表格中对齐即可，不要求等宽完美。

## 入库事实

- 表：`chanlun_analysis`；`insert_chanlun_record(run_id, symbol, conn, dims, score, confidence, structured, raw_report, analyzed_at, card=None, card_parse=None)`。
- `dims` 即解析器返回的 7 键字典；`confidence` 传 0-1 浮点；`symbol` 带交易所后缀（`300014.SZ`）。
- `card` 传 `parse_action_card` 返回的归一化字典（`ok` 时），`card_parse` 传 `ok/no_card/contract_violation`；表中对应展开列：`base_price/base_date/direction/action/setup_class/card_confidence/horizon_days/trigger_price/stop_price/target_prices/rr_at_t1/invalidation/key_risks/one_liner/card_json/card_parse`。
- run_id 约定：`manual-role-chanlun-YYYYMMDDHHMMSS-<6位数字代码>`。
- DuckDB 的 DELETE/UPDATE rowcount 常返回 -1，不代表失败；以 SELECT 回查为准（回查时带上 `card_parse/direction/action`）。
