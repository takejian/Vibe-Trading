---
name: wallstreetcn-news
description: "Wallstreetcn (华尔街见闻) news skill: real-time 7x24 global flash wires, global in-depth articles, important-event filtering and historical lookup through the official api-one.wallstcn.com JSON API."
category: tool
---
# Wallstreetcn News

华尔街见闻官方资讯能力（只读），已接入事件雷达全球源
（`src/eventradar/sources.py`），与 `investment-news-collector`
互补：前者偏 A 股深度，本技能偏全球宏观、美股、央行与大宗商品。

## 四大能力

| 能力 | 接口 |
| --- | --- |
| 最新快讯 | `GET https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=40` |
| 全球深读 | `GET https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global&accept=article&limit=25` |
| 重要筛选 | 标题优先事件评分（见 `investment-news-collector`）+ 雷达范式/核验门 |
| 历史回溯 | 单篇：`GET https://api-one.wallstcn.com/apiv1/content/articles/{id}`；库内：`event_lookup(keyword=…)` |

返回结构：`{"code":20000,"data":{"items":[…]}}`。快讯取
`content_text`/`highlight_title` 为标题、`display_time`（秒级 epoch）
为时间、`uri` 为链接；深读条目外层为
`{resource_type, resource:{…}}`，取 `resource` 内的 `title`、
`content_short`、`uri`。

## 使用规则

1. 只读 GET，禁止高频轮询；雷达每日 04:00 全量扫描一次，手动扫描
   间隔自行克制。
2. 快讯是**线索不是结论**：单源（T2）永远不能自动 confirmed，需
   另一独立 T1/T2 源交叉，或用户人工证实。
3. 引用具体数字（利率、价格、伤亡）时保留快讯链接与时间戳。
4. 事件入库前先 `event_lookup` 判重；宏观影响分析转
   `macro_event_task_force` 预设。
