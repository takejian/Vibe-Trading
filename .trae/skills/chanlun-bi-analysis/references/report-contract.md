# 7 段报告解析契约（parse_chanlun_report）

实现：`agent/src/watchlist/chanlun_parser.py`。入库前**必须**通过该解析器；返回 `None` 时改报告，不要以 `structured=false` 入库。

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

## 前端渲染约束

- 历史记录在 `frontend/src/components/watch/ChanlunHistory.tsx` 以 `<MarkdownContent>` 渲染：支持 GFM 表格与代码块高亮，**不支持 mermaid、不支持图片**——图形只能是 ```` ```text ```` 里的 ASCII。
- 每个 ASCII 图前后留空行，代码块闭合后再写解读文字。
- 中文字段在表格中对齐即可，不要求等宽完美。

## 入库事实

- 表：`chanlun_analysis`；`insert_chanlun_record(run_id, symbol, conn, dims, score, confidence, structured, raw_report, analyzed_at)`。
- `dims` 即解析器返回的 7 键字典；`confidence` 传 0-1 浮点；`symbol` 带交易所后缀（`300014.SZ`）。
- run_id 约定：`manual-role-chanlun-YYYYMMDDHHMMSS-<6位数字代码>`。
- DuckDB 的 DELETE/UPDATE rowcount 常返回 -1，不代表失败；以 SELECT 回查为准。
