"""LLM structured extraction for radar candidates, with a deterministic fallback.

The scanner sends title/snippet batches to the existing chat LLM and asks
for a strict JSON event list (new/merge actions against known events). When
the LLM is unavailable, unconfigured, or returns invalid JSON, a keyword
heuristic extractor takes over so the radar still works offline and unit
tests never need a model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from src.eventradar import scoring

logger = logging.getLogger(__name__)

BATCH_SIZE = 25

_SYSTEM_PROMPT = """你是事件驱动对冲基金的突发新闻情报官。把新闻候选条目聚类为"真实世界事件"，严格输出 JSON。

事件分类（event_type 十选一）：
geopolitical（地缘冲突）/ monetary_fiscal（货币财政）/ trade（贸易关税）/
public_health（疫情公共卫生）/ climate_disaster（气候灾害）/ technology（技术突破）/
regulation（产业监管）/ politics（大选政治）/ financial_credit（金融信用）/
commodity_supply（大宗商品供给冲击）。

规则：
1. 同一事件被不同媒体换词报道时，必须合并为一个事件，evidence_indexes 列出覆盖的全部候选序号。
2. 判重优先对照"已知事件"列表：属于已知事件的后续报道时 action="merge" 并填其 event_id；
   全新事件 action="new"。
3. novelty_class 三选一：
   - known_continuation：同方向重复的已知信息；
   - known_escalation：既有事件扩大、加码、转折；
   - new_paradigm：新实体/新政策范式/新技术路线/新冲突形态。只有当它可能对应长期赛道级
     机会时才可用，且必须给出 paradigm_scores 四项 1-5 分：policy_duration（政策持续性）、
     invest_cycle（投资周期长度）、chain_breadth（产业链波及宽度）、narrative_heat（叙事热度增速）。
4. fact_consistency：各信源对关键事实表述的一致程度 0-1；单条候选给 0.5。
5. impact_direction：positive / negative / uncertain；affected_assets 为对象数组
   [{"asset": "资产或行业", "direction": "positive|negative"}]。
6. 只输出 JSON 数组，不要 markdown 代码块或任何解释文字。广告、软文、纯行情播报、
   重复旧闻且无新信息的条目直接丢弃。"""


def _build_user_message(
    candidates: list[dict[str, Any]], known: list[dict[str, Any]]
) -> str:
    lines = ["【候选新闻】"]
    for idx, item in enumerate(candidates):
        lines.append(
            f"#{idx} 标题：{item['title']}\n"
            f"    来源：{item.get('source_name') or 'unknown'}｜"
            f"摘要：{(item.get('snippet') or '')[:160]}"
        )
    lines.append("\n【已知事件（判重用）】")
    if known:
        for event in known:
            lines.append(
                f"- event_id={event['event_id']}｜{event['event_type']}｜"
                f"{event['title']}（{event['verify_status']}/{event['novelty_class']}）"
            )
    else:
        lines.append("（无）")
    lines.append('\n输出 JSON 数组，每项形如：')
    lines.append(json.dumps({
        "action": "new",
        "event_id": None,
        "title": "事件标题",
        "event_type": "geopolitical",
        "entities": ["实体1"],
        "regions": ["区域"],
        "summary": "一句话摘要",
        "impact_direction": "uncertain",
        "affected_assets": [{"asset": "原油", "direction": "negative"}],
        "novelty_class": "new_paradigm",
        "paradigm_scores": {
            "policy_duration": 4, "invest_cycle": 4,
            "chain_breadth": 3, "narrative_heat": 5,
        },
        "fact_consistency": 0.8,
        "evidence_indexes": [0, 2],
    }, ensure_ascii=False))
    return "\n".join(lines)


def _coerce_item(raw: Any, count: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    event_type = raw.get("event_type")
    if not title or event_type not in scoring.EVENT_TYPES:
        return None
    action = raw.get("action")
    if action not in ("new", "merge"):
        action = "new"
    indexes = raw.get("evidence_indexes")
    if not isinstance(indexes, list) or not indexes:
        return None
    valid_indexes = [i for i in indexes if isinstance(i, int) and 0 <= i < count]
    if not valid_indexes:
        return None
    novelty = raw.get("novelty_class")
    if novelty not in scoring.NOVELTY_CLASSES:
        novelty = "known_continuation"
    try:
        consistency = float(raw.get("fact_consistency", 0.5))
    except (TypeError, ValueError):
        consistency = 0.5
    consistency = max(0.0, min(1.0, consistency))
    assets = raw.get("affected_assets")
    if not isinstance(assets, list):
        assets = []
    assets = [
        {"asset": str(a.get("asset", "")).strip(),
         "direction": a.get("direction") if a.get("direction") in
         ("positive", "negative") else "uncertain"}
        for a in assets if isinstance(a, dict) and a.get("asset")
    ]
    return {
        "action": action,
        "event_id": str(raw["event_id"]) if raw.get("event_id") else None,
        "title": title,
        "event_type": event_type,
        "entities": [str(e) for e in raw.get("entities", []) if e][:8]
        if isinstance(raw.get("entities"), list) else [],
        "regions": [str(r) for r in raw.get("regions", []) if r][:8]
        if isinstance(raw.get("regions"), list) else [],
        "summary": str(raw.get("summary") or "")[:400],
        "impact_direction": raw.get("impact_direction")
        if raw.get("impact_direction") in ("positive", "negative", "uncertain")
        else "uncertain",
        "affected_assets": assets,
        "novelty_class": novelty,
        "paradigm_scores": raw.get("paradigm_scores")
        if isinstance(raw.get("paradigm_scores"), dict) else None,
        "fact_consistency": consistency,
        "evidence_indexes": valid_indexes,
    }


def parse_extraction(raw: str, candidate_count: int) -> list[dict[str, Any]]:
    """Strict parse of model output; raises ValueError on contract violation."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty model output")
    text = raw.strip()
    if text.startswith("```"):
        # Tolerate one fence violation by stripping it; the prompt forbids it.
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("top-level JSON must be an array")
    events: list[dict[str, Any]] = []
    for item in data:
        coerced = _coerce_item(item, candidate_count)
        if coerced is not None:
            events.append(coerced)
    return events


def heuristic_extract(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic fallback: one event per near-unique candidate.

    Same-repost candidates get collapsed later by SimHash clustering; here
    we just give every surviving candidate a well-formed event skeleton.
    """
    events: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        text = f"{item['title']} {item.get('snippet') or ''}"
        event_type = item.get("query_type")
        if event_type not in scoring.EVENT_TYPES:
            event_type = scoring.guess_event_type(text)
        entities = scoring.extract_entities_heuristic(item["title"], event_type)
        themes = scoring.map_themes(text)
        events.append({
            "action": "new",
            "event_id": None,
            "title": item["title"].strip()[:120],
            "event_type": event_type,
            "entities": entities,
            "regions": [],
            "summary": (item.get("snippet") or "")[:200],
            "impact_direction": "uncertain",
            "affected_assets": [],
            "novelty_class": "new_paradigm" if themes else "known_escalation",
            # Heuristic paradigm hint: medium scores, threshold decides.
            "paradigm_scores": {
                "policy_duration": 4, "invest_cycle": 4,
                "chain_breadth": 4, "narrative_heat": 4,
            } if themes else None,
            "fact_consistency": 0.5,
            "evidence_indexes": [idx],
            "heuristic": True,
        })
    return events


def _default_llm():
    from src.providers.chat import ChatLLM

    return ChatLLM()


def extract_events(
    candidates: list[dict[str, Any]],
    known: list[dict[str, Any]],
    *,
    llm_factory: Callable[[], Any] | None = _default_llm,
) -> tuple[list[dict[str, Any]], bool]:
    """Extract structured events for one candidate batch.

    Returns ``(events, used_llm)``. Never raises for model reasons — the
    heuristic fallback always produces a result.
    """
    if not candidates:
        return [], False
    if llm_factory is None:
        return heuristic_extract(candidates), False
    try:
        from src.config.accessor import get_env_config

        timeout = int(get_env_config().llm.timeout_seconds)
    except Exception:
        timeout = 120
    try:
        llm = llm_factory()
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_message(candidates, known)},
        ]
        response = llm.chat(messages, timeout=timeout)
        content = getattr(response, "content", "")
        events = parse_extraction(content, len(candidates))
        if not events:
            raise ValueError("model returned no valid events")
        return events, True
    except Exception as exc:
        logger.warning("radar LLM extraction failed, using heuristic: %s", exc)
        return heuristic_extract(candidates), False


def extract_all(
    candidates: list[dict[str, Any]],
    known: list[dict[str, Any]],
    *,
    llm_factory: Callable[[], Any] | None = _default_llm,
    batch_size: int = BATCH_SIZE,
) -> tuple[list[dict[str, Any]], bool]:
    """Run extraction over all candidates in bounded batches."""
    all_events: list[dict[str, Any]] = []
    used_llm = False
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        events, batch_used_llm = extract_events(
            batch, known, llm_factory=llm_factory
        )
        used_llm = used_llm or batch_used_llm
        # Remap batch-local indexes to global candidate indexes.
        for event in events:
            event["evidence_indexes"] = [start + i for i in event["evidence_indexes"]]
            all_events.append(event)
    return all_events, used_llm
