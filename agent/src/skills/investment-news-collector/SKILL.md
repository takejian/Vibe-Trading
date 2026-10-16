---
name: investment-news-collector
description: "Zero-token investment-news collection pipeline (SkillHub community skill, adapted): 财联社深度 + 华尔街见闻 dual-source ingest, title-first event scoring, size/time factors, three-tier signals, Top-5 daily briefing without any LLM API cost."
category: tool
---
# Investment News Collector

源自 SkillHub 社区 skill（v2.4.0）的零 Token 财经资讯采集管线，已内置到
事件雷达后端（`src/eventradar/sources.py`）：专业双源直连，无需本地
RSSHub。

## 数据源（双源冗余，单源失败不中断）

| 源 | 接口 | 覆盖 |
| --- | --- | --- |
| 财联社深度（主） | `GET https://www.cls.cn/v3/depth/home/assembled/{1000|1007}` | A 股头条、环球宏观；cls.cn 签名：参数排序后 `MD5(SHA1(querystring))` |
| 华尔街见闻（备） | `GET https://api-one.wallstcn.com/apiv1/content/{lives,articles}` | 7x24 全球快讯 + 全球深读 |

两源域名均为事件雷达 T2 级信源；同一事件被两源独立报道即可通过
自动证实门。

## 六步管线

```
双源采集 → URL/指纹去重 → 领域垃圾过滤 → 标题优先事件评分
→ 话题聚类（雷达 SimHash + Jaccard）→ 结构化入库（证据链 + 信源分级）
```

## 标题优先事件评分（10 类）

标题命中给全分，仅正文命中降权至 1/3，避免"市值报道"误标 IPO：

| 类型 | 权重 | 类型 | 权重 |
| --- | --- | --- | --- |
| IPO/上市 | 25 | 业务里程碑 | 14 |
| 并购重组 | 24 | 合作战略 | 12 |
| 风险预警 | 22 | 产品发布 | 11 |
| 融资估值 | 20 | 财报业绩 | 9 |
| 政策监管 | 18 | 市场表现 | 8 |

```
最终分 = (10 + 事件类型分 + 公司加分 + 创新加分) × 金额规模因子 × 时效衰减
```

- 金额规模：≥100 亿/10 亿美元 ×1.30；≥10 亿/1 亿 ×1.15；含百分比 ×1.10
- 时效：<6h ×1.00；6–12h ×0.95；12–24h ×0.85；>24h ×0.70
- 信号档：🔴 头条 ≥42｜🟠 重要 ≥32｜🟡 关注 ≥22｜⚪ 常规 <22

## 在本系统中的使用

1. 雷达默认每日 04:00（Asia/Shanghai，`VIBE_EVENT_DAILY_SCAN_AT`）自动
   全量扫描；也可 `POST /events/scan {"scope":"all"}` 手动触发。
2. 判定事件前**必须**先调 `event_lookup` 判重，已存在则走 merge。
3. 雷达默认只展示**最重要的 5 条**（证实状态 → 新范式 → 置信度 →
   信源数 → 时效）；宏观研判与持仓影响交给 `breaking-news-radar`
   的核验/范式框架，不要直接转述未证实快讯。
