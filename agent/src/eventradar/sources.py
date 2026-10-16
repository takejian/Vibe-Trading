"""Curated professional-source news collection for the breaking-news radar.

Two editorially-curated sources, each backed by a bundled skill, replace
the MVP search-engine casting net:

* ``investment-news-collector`` — 财联社深度 (CLS depth) 头条/环球 columns
  fetched directly from cls.cn with the same request-signing scheme
  RSSHub uses (no local RSSHub/Node runtime required);
* ``wallstreetcn-news`` — 华尔街见闻 7x24 全球快讯 (lives) + 全球深读
  (articles) through the official ``api-one.wallstcn.com`` JSON API.

Both feeds are professional wires with editorial filtering, so the radar
ingests a small high-grade stream (~80 items per full scan) instead of
hundreds of search hits; downstream extraction/clustering/verification
and the Top-5 presentation do the rest. Each source is failure-isolated.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Default editorial head cut per channel (v1.2: four channels x head-N).
_DEFAULT_HEAD_N = 5
#: Wire fetch sizes (always >= head-N so the editorially-ranked head exists).
_FETCH_SIZE = 40

#: URL patterns that are not articles (chart pages, pure quote/calendar tools).
_NON_ARTICLE_URL_RE = re.compile(r"/charts?/|/quote[s]?/|/calendar/", re.IGNORECASE)

#: CLS depth columns mirroring RSSHub ``/cls/depth/:category``.
_CLS_DEPTH_CATEGORIES: dict[str, str] = {
    "1000": "财联社·头条",
    "1007": "财联社·环球",
}

#: Fixed signing envelope used by cls.cn web API (same values as RSSHub's
#: lib/routes/cls/utils.ts).
_CLS_APP_PARAMS = {"appName": "CailianpressWeb", "os": "web", "sv": "8.7.9"}

#: Navigational/quote/encyclopedia pages that never carry breaking events.
_JUNK_TITLE_RE = re.compile(
    r"实时行情|期货行情|今日.*(?:价格|报价|行情)|最新价格|走势图表|历史数据|"
    r"行情$|报价|股吧|百度百科|百科|加群|荐群|荐股|软文|广告|"
    r"民法典|条款(?:规定|解读)?$|第[0-9一二三四五六七八九十百千]+条|"
    r"登录|注册|首页|官网下载|期货频道|股票频道",
)


def is_junk(title: str, snippet: str | None = None,
            url: str | None = None) -> None | bool:
    """True for chart/quote pages, encyclopedia entries and obvious ads."""
    if url and _NON_ARTICLE_URL_RE.search(url):
        return True
    head = title or ""
    if _JUNK_TITLE_RE.search(head):
        return True
    blob = f"{head} {snippet or ''}"
    if ("加群" in blob or "荐股" in blob or "免费领取" in blob) and \
            "风险提示" in blob:
        return True
    return False


def feed_head_n() -> int:
    """Per-channel editorial head count (``VIBE_EVENT_FEED_HEAD_N``)."""
    try:
        from src.config.accessor import get_env_config

        return int(get_env_config().event_radar.vibe_event_feed_head_n)
    except Exception:  # config unavailable (offline unit tests)
        return _DEFAULT_HEAD_N


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get_json(url: str, *, params: dict[str, str] | None = None,
                   headers: dict[str, str] | None = None,
                   timeout: int = 15) -> dict[str, Any] | None:
    """GET JSON via the project-standard requests session; None on failure."""
    import requests

    hdrs = {"User-Agent": "Mozilla/5.0 (vibe-trading event radar)"}
    if headers:
        hdrs.update(headers)
    try:
        resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # source failure is a status, not a scan crash
        logger.warning("radar source GET failed %s: %s", url, exc)
        return None


def _clean_text(value: Any) -> str:
    """Strip HTML tags and collapse whitespace in feed text."""
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _epoch_to_str(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 财联社深度 (investment-news-collector primary source)
# ---------------------------------------------------------------------------

def _cls_signed_params(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Replicate RSSHub's cls.cn signing: sort params, SHA1 then MD5."""
    merged = {**_CLS_APP_PARAMS, **(extra or {})}
    encoded = "&".join(f"{k}={v}" for k, v in sorted(merged.items()))
    sha1 = hashlib.sha1(encoded.encode("utf-8")).hexdigest()
    merged["sign"] = hashlib.md5(sha1.encode("utf-8")).hexdigest()
    return merged


def _normalize_cls_depth(payload: dict[str, Any], source_name: str) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    items = [*(data.get("top_article") or []), *(data.get("depth_list") or [])]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        title = _clean_text(item.get("title") or item.get("brief"))
        if item_id is None or not title or item_id in seen:
            continue
        seen.add(item_id)
        out.append({
            "url": f"https://www.cls.cn/detail/{item_id}",
            "title": title,
            "snippet": _clean_text(item.get("brief"))[:280],
            "source_name": item.get("source") or source_name,
            "published_at": _epoch_to_str(item.get("ctime")),
            "language": "zh",
            "origin": "investment-news-collector",
        })
    return out


def _cls_channel(
    category: str, label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch one full 财联社深度 column (head-N cut happens in collect())."""
    params = _cls_signed_params()
    payload = _http_get_json(
        f"https://www.cls.cn/v3/depth/home/assembled/{category}",
        params=params,
        headers={"Referer": f"https://www.cls.cn/depth?id={category}"},
    )
    if payload is None:
        return {"name": label, "status": "error", "count": 0}, []
    articles = _normalize_cls_depth(payload, label)
    return (
        {"name": label, "status": "ok", "count": len(articles)},
        articles,
    )


# ---------------------------------------------------------------------------
# 华尔街见闻 (wallstreetcn-news)
# ---------------------------------------------------------------------------

def _normalize_wsc_lives(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = (payload.get("data") or {}).get("items") or []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        title = _clean_text(item.get("highlight_title") or item.get("content_text"))
        uri = item.get("uri") or (
            f"https://wallstreetcn.com/livenews/{item_id}" if item_id else ""
        )
        if not uri or not title:
            continue
        out.append({
            "url": uri,
            "title": title[:120],
            "snippet": _clean_text(item.get("content_text"))[:280],
            "source_name": "华尔街见闻·7x24",
            "published_at": _epoch_to_str(item.get("display_time")),
            "language": "zh",
            "origin": "wallstreetcn-news",
        })
    return out


def _normalize_wsc_articles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # The information-flow endpoint wraps each article in {resource, …}.
    raw_items = (payload.get("data") or {}).get("items") or []
    items = [
        it.get("resource") if isinstance(it.get("resource"), dict) else it
        for it in raw_items if isinstance(it, dict)
    ]
    out: list[dict[str, Any]] = []
    for item in items:
        item_id = item.get("id")
        title = _clean_text(item.get("title"))
        if item_id is None or not title:
            continue
        out.append({
            "url": item.get("uri") or f"https://wallstreetcn.com/articles/{item_id}",
            "title": title,
            "snippet": _clean_text(item.get("content_short"))[:280],
            "source_name": "华尔街见闻",
            "published_at": _epoch_to_str(item.get("display_time")),
            "language": "zh",
            "origin": "wallstreetcn-news",
        })
    return out


def _wsc_lives_channel() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch the full 7x24 全球快讯 channel (head-N cut happens in collect())."""
    payload = _http_get_json(
        "https://api-one.wallstcn.com/apiv1/content/lives",
        params={"channel": "global-channel", "limit": str(_FETCH_SIZE)},
    )
    if payload is None:
        return {"name": "华尔街见闻·7x24", "status": "error", "count": 0}, []
    articles = _normalize_wsc_lives(payload)
    return (
        {"name": "华尔街见闻·7x24", "status": "ok", "count": len(articles)},
        articles,
    )


def _wsc_articles_channel() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch the full 全球深读 channel (head-N cut happens in collect())."""
    payload = _http_get_json(
        "https://api-one.wallstcn.com/apiv1/content/information-flow",
        params={"channel": "global", "accept": "article",
                "limit": str(_FETCH_SIZE)},
    )
    if payload is None:
        return {"name": "华尔街见闻·全球", "status": "error", "count": 0}, []
    articles = _normalize_wsc_articles(payload)
    return (
        {"name": "华尔街见闻·全球", "status": "ok", "count": len(articles)},
        articles,
    )


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------

#: One zero-arg callable per channel → (source status, raw articles).
#: ``collect()`` is the single place that applies the editorial head-N cut.
ChannelFetcher = Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]]

_CHINA_CHANNELS: tuple[ChannelFetcher, ...] = tuple(
    functools.partial(_cls_channel, category, label)
    for category, label in _CLS_DEPTH_CATEGORIES.items()
)
_GLOBAL_CHANNELS: tuple[ChannelFetcher, ...] = (
    _wsc_lives_channel,
    _wsc_articles_channel,
)


def collect(scope: str = "all", head_n: int | None = None) -> dict[str, Any]:
    """Collect curated candidates. Returns ``{sources, candidates}``.

    ``china`` pulls the two 财联社深度 columns; ``global`` pulls the two
    华尔街见闻 channels; ``all`` pulls all four. Each channel contributes
    only its editorially-ranked head-N items (default 5 → at most 20
    candidates per scan). URL-dedup and the junk/chart filter remove leftovers.
    """
    if head_n is None:
        head_n = feed_head_n()
    channels: tuple[ChannelFetcher, ...] = ()
    if scope in ("china", "all"):
        channels += _CHINA_CHANNELS
    if scope in ("global", "all"):
        channels += _GLOBAL_CHANNELS

    sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for fetch in channels:
        status, articles = fetch()
        articles = articles[:head_n]
        status = {**status, "count": len(articles)}
        sources.append(status)
        for article in articles:
            url = article["url"]
            if url in seen_urls or is_junk(article["title"],
                                           article.get("snippet"), url):
                continue
            seen_urls.add(url)
            candidates.append(article)

    return {
        "sources": sources,
        "candidates": candidates,
    }
