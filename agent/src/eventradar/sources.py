"""Multi-source news collection for the breaking-news radar.

All outbound access reuses the existing, throttled tool implementations —
this module never opens a socket itself:

* ``get_stock_news`` (scope=global) — Eastmoney broad finance headlines;
* ``web_search`` — ddgs multi-engine search over a 10-type keyword matrix,
  Chinese and/or English depending on scan scope.

Each source is failure-isolated: a throttled/empty source records its
status and the scan continues.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Per-language breaking-news query per event category. Kept terse on
#: purpose: search engines already rank recent items, and the extractor
#: does the classification/scoring downstream.
_ZH_QUERIES: dict[str, str] = {
    "geopolitical": "突发 地缘 冲突 制裁",
    "monetary_fiscal": "央行 货币政策 财政 最新",
    "trade": "关税 贸易 出口管制 最新",
    "public_health": "疫情 突发 公共卫生",
    "climate_disaster": "厄尔尼诺 极端天气 灾害 最新",
    "technology": "技术突破 芯片 AI 人工智能 发布",
    "regulation": "监管 反垄断 禁令 处罚",
    "politics": "大选 选举 政治 突发",
    "financial_credit": "违约 破产 债务危机 银行",
    "commodity_supply": "原油 减产 粮食 供给冲击",
}

_EN_QUERIES: dict[str, str] = {
    "geopolitical": "breaking geopolitical conflict sanctions",
    "monetary_fiscal": "central bank rate decision fiscal policy breaking",
    "trade": "tariff trade war export controls breaking",
    "public_health": "pandemic outbreak health emergency breaking",
    "climate_disaster": "el nino extreme weather disaster breaking",
    "technology": "AI chip breakthrough unveils breaking",
    "regulation": "antitrust regulator ban probe breaking",
    "politics": "election political crisis breaking",
    "financial_credit": "default bankruptcy debt crisis bank breaking",
    "commodity_supply": "oil OPEC output cut supply disruption grain",
}

_MAX_PER_QUERY = 5
_MAX_TOTAL_CANDIDATES = 200

#: Navigational/quote/encyclopedia pages that are not breaking events.
#: Conservative on purpose — only drop patterns that never carry news.
_JUNK_TITLE_RE = re.compile(
    r"实时行情|期货行情|今日.*(?:价格|报价|行情)|最新价格|走势图表|历史数据|"
    r"行情$|报价|股吧|百度百科|百科|加群|荐群|荐股|软文|广告|"
    r"民法典|条款(?:规定|解读)?$|第[0-9一二三四五六七八九十百千]+条|"
    r"登录|注册|首页|官网下载|期货频道|股票频道",
)


def is_junk(title: str, snippet: str | None = None) -> bool:
    """True for quote pages, encyclopedia entries and obvious ads."""
    head = title or ""
    if _JUNK_TITLE_RE.search(head):
        return True
    blob = f"{head} {snippet or ''}"
    if ("加群" in blob or "荐股" in blob or "免费领取" in blob) and             "风险提示" in blob:
        return True
    return False


def _run_tool(tool: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        raw = tool.execute(**kwargs)
        return json.loads(raw)
    except Exception as exc:  # tool failure is a source status, not a crash
        logger.warning("radar source tool failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _clean_text(value: Any) -> str:
    """Strip search highlight tags (<em>…) left in headlines/snippets."""
    return re.sub(r"</?em>", "", str(value or "")).strip()


def _normalize_articles(payload: dict[str, Any], source_name: str) -> list[dict[str, Any]]:
    # StockNewsTool nests its payload under {"ok", "data": {"articles": [...]}}.
    data = payload.get("data")
    if isinstance(data, dict):
        payload = data
    articles = payload.get("articles")
    if not isinstance(articles, list):
        results = payload.get("results")
        if isinstance(results, list):
            articles = results
        else:
            return []
    out: list[dict[str, Any]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("link") or ""
        title = _clean_text(item.get("title"))
        if not url or not title:
            continue
        out.append({
            "url": url,
            "title": title,
            "snippet": _clean_text(item.get("snippet") or item.get("summary"))[:280],
            "source_name": item.get("source") or source_name,
            "published_at": item.get("published") or item.get("published_at") or item.get("date"),
            "language": item.get("language", ""),
            "origin": source_name,
        })
    return out


def collect(scope: str = "all") -> dict[str, Any]:
    """Collect raw candidates. Returns ``{sources, candidates}``.

    ``scope`` is ``china`` (Chinese queries + Eastmoney), ``global``
    (English queries only) or ``all`` (both).
    """
    # Local imports: tool construction is cheap but keeps the package
    # importable even if optional tool deps are missing.
    from src.tools.stock_news_tool import StockNewsTool
    from src.tools.web_search_tool import WebSearchTool

    sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def _absorb(articles: list[dict[str, Any]]) -> None:
        for article in articles:
            url = article["url"]
            if url in seen_urls or is_junk(article["title"],
                                           article.get("snippet")):
                continue
            seen_urls.add(url)
            candidates.append(article)

    # --- Eastmoney broad headlines (china/all only) ---
    if scope in ("china", "all"):
        news_tool = StockNewsTool()
        payload = _run_tool(news_tool, scope="global", limit=30)
        articles = _normalize_articles(payload, "eastmoney")
        sources.append({
            "name": "eastmoney", "status": payload.get("status", "ok"),
            "count": len(articles),
        })
        _absorb(articles)

    # --- Web search matrix ---
    search_tool = WebSearchTool()
    matrices: list[tuple[str, dict[str, str], str]] = []
    if scope in ("china", "all"):
        matrices.append(("zh", _ZH_QUERIES, "ddgs"))
    if scope in ("global", "all"):
        matrices.append(("en", _EN_QUERIES, "ddgs"))

    for language, matrix, source_name in matrices:
        for event_type, query in matrix.items():
            if len(candidates) >= _MAX_TOTAL_CANDIDATES:
                break
            payload = _run_tool(search_tool, query=query, max_results=_MAX_PER_QUERY)
            articles = _normalize_articles(payload, source_name)
            for article in articles:
                article["language"] = article.get("language") or language
                article["query_type"] = event_type
            sources.append({
                "name": f"{source_name}:{language}:{event_type}",
                "status": payload.get("status", "ok"),
                "count": len(articles),
            })
            _absorb(articles)

    return {"sources": sources, "candidates": candidates[:_MAX_TOTAL_CANDIDATES]}
