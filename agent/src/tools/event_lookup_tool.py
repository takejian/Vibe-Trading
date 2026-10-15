"""Read-only radar event lookup tool for agents.

Lets the breaking-news scanner (and Task Force scouts) deduplicate against
the persisted event library: search by entity keyword, optional event type
and a recency window. Auto-discovered from ``src/tools/`` like every other
local tool; the implementation itself lives in ``src.eventradar`` so the
business package is not imported from scattered places.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool


class EventLookupTool(BaseTool):
    """Search the local radar event library (dedup / similar-event lookup)."""

    name = "event_lookup"
    description = (
        "Search the local breaking-news event library for prior events by "
        "entity keyword, event type and recency window. Use this BEFORE "
        "declaring a new event to deduplicate: if the same real-world event "
        "exists, return a merge action with its event_id instead of creating "
        "a duplicate. Also useful for finding similar historical events. "
        'Example: {"keyword": "厄尔尼诺", "event_type": "climate_disaster", '
        '"window_hours": 168}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Entity / theme keyword matched against title, "
                               "summary and entities (Chinese or English).",
            },
            "event_type": {
                "type": "string",
                "description": "Optional ten-class filter: geopolitical / "
                               "monetary_fiscal / trade / public_health / "
                               "climate_disaster / technology / regulation / "
                               "politics / financial_credit / commodity_supply.",
            },
            "window_hours": {
                "type": "integer",
                "description": "Recency window in hours (default 168 = 7 days).",
                "default": 168,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum events to return (default 20, max 50).",
                "default": 20,
            },
        },
        "required": [],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        from src.eventradar import db as event_db

        keyword = str(kwargs.get("keyword") or "").strip()
        event_type = kwargs.get("event_type")
        if event_type is not None and not isinstance(event_type, str):
            event_type = None
        try:
            window_hours = int(kwargs.get("window_hours", 168))
        except (TypeError, ValueError):
            window_hours = 168
        try:
            limit = min(50, max(1, int(kwargs.get("limit", 20))))
        except (TypeError, ValueError):
            limit = 20

        conn = event_db.event_connection()
        try:
            event_db.initialize_schema(conn)
            rows = event_db.search_events(
                conn,
                keyword=keyword,
                event_type=event_type,
                window_hours=window_hours,
                limit=limit,
            )
        finally:
            conn.close()

        events = [
            {
                "event_id": row["event_id"],
                "title": row["title"],
                "event_type": row["event_type"],
                "entities": row["entities"],
                "regions": row["regions"],
                "novelty_class": row["novelty_class"],
                "verify_status": row["verify_status"],
                "impact_level": row["impact_level"],
                "source_count": row["source_count"],
                "first_seen_at": row["first_seen_at"],
                "last_update_at": row["last_update_at"],
                "summary": row["summary"],
            }
            for row in rows
        ]
        return json.dumps(
            {"status": "ok", "count": len(events), "events": events},
            ensure_ascii=False,
        )
