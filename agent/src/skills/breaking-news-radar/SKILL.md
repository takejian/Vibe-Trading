---
name: breaking-news-radar
description: "Breaking-news radar workflow: multi-source collection, entity×type×time-window dedup, source-tier verification, novelty/paradigm classification for macro events, and strict JSON event output."
category: tool
---
# Breaking-News Radar

## Purpose

Turn a noisy stream of financial news into a small set of **verified real-world
macro events**, each with an evidence chain, a verification status and a
novelty verdict — with special emphasis on detecting **new paradigms** (new
things that map to long-horizon investment opportunities).

## Mandatory Workflow

1. **Dedup first.** Before declaring any event, call `event_lookup` with the
   main entities and event type. If the event already exists, output a
   `merge` action carrying its `event_id`; never create a duplicate.
2. **Collect from professional wires.** The radar ingests curated feeds
   only — `investment-news-collector` (财联社深度 头条/环球) and
   `wallstreetcn-news` (华尔街见闻 7x24 快讯 + 全球深读), daily 04:00
   Asia/Shanghai or via `POST /events/scan`; use `read_url` for
   high-value primaries when deeper context is needed.
3. **Verify before trusting.** Apply the source-tier gate below; a single
   source is never "confirmed".
4. **Classify novelty.** Default to continuation/escalation; only call
   something a new paradigm with the four-score card.
5. Output the strict JSON schema — no prose, no markdown fences.

## Event Taxonomy (exactly one)

| event_type | 含义 |
| --- | --- |
| `geopolitical` | 战争、冲突、制裁、军事行动 |
| `monetary_fiscal` | 央行利率、准备金、财政与国债政策 |
| `trade` | 关税、贸易战、出口管制、脱钩 |
| `public_health` | 疫情、病毒、封锁、世卫紧急事件 |
| `climate_disaster` | 厄尔尼诺/拉尼娜、台风、旱涝、地震 |
| `technology` | 技术突破、芯片、AI、量子、机器人 |
| `regulation` | 监管、反垄断、禁令、调查处罚 |
| `politics` | 大选、政府更迭、政治危机 |
| `financial_credit` | 违约、破产、银行挤兑、债务危机 |
| `commodity_supply` | 减产、断供、油气粮供给冲击 |

## Source Tiers

- **T1 一手源**：央行/财政/监管/交易所/政府公告、WHO/WTO/IMF、NOAA 等
  官方机构。
- **T2 通讯社/权威媒体**：新华社、路透、彭博、华尔街日报、FT、AP、财新、
  一财、证券时报、上证报。
- **T3 一般财经媒体**：东财、新浪、同花顺、21 世纪、澎湃、MarketWatch、
  Barron's、Yahoo Finance。
- **T4 聚合号/自媒体**：默认可信度最低。

转载/同集团改写（"转自""via Reuters"）**不计为独立信源**。

## Verification Gate

- 单源（任何层级）最高只能到 `verifying`。
- 升 `confirmed` 必须同时满足：≥2 个相互独立信源、至少 1 个 T1/T2、
  跨源关键事实一致、综合置信度 ≥ 0.70。
- 关键事实互相冲突 → `disputed`；T1/T2 明确辟谣或证伪 → `rumor`。
- 状态机：`unverified → verifying → confirmed / disputed / rumor → dismissed`。
  人工终态（confirm/rumor/dismiss）之后，自动扫描只能追加证据，不得翻案。

## Novelty Verdict

| novelty_class | 判定 |
| --- | --- |
| `known_continuation` | 同方向重复信息，无新增量 |
| `known_escalation` | 既有事件扩大、加码、转折 |
| `new_paradigm` | 新实体/新政策范式/新技术路线/新冲突形态，可能重塑长期格局 |

`new_paradigm` **必须**附四要素评分（各 1–5），缺一即降级：

- `policy_duration` 政策持续性
- `invest_cycle` 投资周期长度
- `chain_breadth` 产业链波及宽度
- `narrative_heat` 叙事热度增速

总分 ≥ 15/20 才可标记；同时必须映射到长期赛道（AI 与算力 / 能源转型 /
军工安全 / 供应链重构 / 人口与消费 / 国产替代 / 气候与农业 / 货币体系）。

## Output Schema

```json
[
  {
    "action": "new",
    "event_id": null,
    "title": "事件标题",
    "event_type": "climate_disaster",
    "entities": ["NOAA", "美国国家气象局"],
    "regions": ["全球", "中国"],
    "summary": "一句话摘要",
    "impact_direction": "uncertain",
    "affected_assets": [
      {"asset": "农产品", "direction": "negative"},
      {"asset": "水利设施", "direction": "positive"}
    ],
    "novelty_class": "known_escalation",
    "paradigm_scores": null,
    "fact_consistency": 0.8,
    "evidence_indexes": [0, 3, 7]
  }
]
```

- `action`：`new` 或 `merge`（merge 时必须带已知 `event_id`）。
- `evidence_indexes`：该事件覆盖的全部候选新闻序号，换词重写必须合并。
- `impact_direction`：`positive` / `negative` / `uncertain`。
- 广告、软文、纯行情播报、无新增量的旧闻直接丢弃（不输出）。

## Quality Bar

- 宁可不确认，不可假确认：证据不足就留在 `verifying`。
- 数字与日期必须能在证据正文中找到；不允许推测具体伤亡/金额。
- 中文新闻用中文标题，英文新闻可保留英文标题并在 summary 中中文概述。
