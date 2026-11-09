"""Business logic for the investment celebrity module."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.celebrity import db
from src.celebrity.db import celebrity_connection, initialize_schema

logger = logging.getLogger(__name__)


class CelebrityError(Exception):
    """Base error for celebrity module."""


class CelebrityNotFoundError(CelebrityError):
    pass


class CelebrityLLMError(CelebrityError):
    pass


class CelebrityValidationError(CelebrityError):
    pass


# ---------------------------------------------------------------------------
# Investor management
# ---------------------------------------------------------------------------

def list_investors() -> list[dict[str, Any]]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        return db.list_investors(conn)


def add_investor(name: str, invest_style: str, remark: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise CelebrityValidationError("投资人名称为必填项")
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv_id = db.add_investor(conn, name, invest_style or "", remark or "")
        conn.commit()
    return {"id": inv_id, "name": name}


def delete_investor(investor_id: int) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        ok = db.delete_investor(conn, investor_id)
        if not ok:
            inv = db.get_investor(conn, investor_id)
            if inv is None:
                raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
            raise CelebrityValidationError("预置投资人不可删除")
        conn.commit()
    return {"deleted": True, "id": investor_id}


def update_invest_style(investor_id: int, invest_style: str) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        db.update_invest_style(conn, investor_id, invest_style or "")
        conn.commit()
    return {"id": investor_id, "updated": True}


# ---------------------------------------------------------------------------
# Investor card
# ---------------------------------------------------------------------------

def get_investor_card(investor_id: int) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        positions = db.list_positions(conn, investor_id)
        opinions = db.list_opinions(conn, investor_id)
        adjusts = db.list_adjusts(conn, investor_id)
        performance = db.get_performance(conn, investor_id)

    latest_opinion = next((o for o in opinions if o.get("is_latest")), None)
    if latest_opinion is None and opinions:
        latest_opinion = opinions[0]
    history_opinions = [o for o in opinions if o is not latest_opinion]

    return {
        "investor": inv,
        "positions": positions,
        "latest_opinion": latest_opinion,
        "history_opinions": history_opinions,
        "adjusts": adjusts,
        "performance": performance,
    }


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str | None:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return text
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("{") or block.startswith("["):
                return block
            if "\n" in block:
                block = block.split("\n", 1)[1]
                if block.startswith("{") or block.startswith("["):
                    return block
    return None


def _call_llm(system_prompt: str, user_prompt: str, timeout: int = 60) -> Any:
    from src.providers.chat import ChatLLM

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        llm = ChatLLM()
        response = llm.chat(messages, timeout=timeout)
        content = getattr(response, "content", str(response))
    except Exception as exc:
        raise CelebrityLLMError(f"LLM 调用失败: {exc}") from exc

    json_str = _extract_json(content)
    if not json_str:
        raise CelebrityLLMError(f"LLM 返回非 JSON: {content[:200]}")
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise CelebrityLLMError(f"LLM JSON 解析失败: {exc}") from exc


def _get_prompt_content(key: str) -> str:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        prompt = db.get_prompt(conn, key)
    if prompt is None:
        raise CelebrityError(f"提示词 {key} 未配置")
    return prompt["content"]


# ---------------------------------------------------------------------------
# Refresh (latest dynamics)
# ---------------------------------------------------------------------------

def refresh_investor(investor_id: int) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        investor_name = inv["name"]

    prompt = _get_prompt_content("latest_dynamics").replace("{{investor_name}}", investor_name)
    data = _call_llm(prompt, f"请整理 {investor_name} 的最新持仓、观点与调仓动向。")

    positions = data.get("current_positions") or []
    opinions = data.get("history_opinions") or []
    adjusts = data.get("adjust_trend") or []
    latest_op = data.get("latest_opinion")

    # Treat empty response as no new info
    if not positions and not opinions and not adjusts and not latest_op:
        return {"status": "no_new_info", "message": "暂无新公开信息"}

    if latest_op:
        opinions = opinions + [latest_op]

    from datetime import datetime

    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    with celebrity_connection() as conn:
        initialize_schema(conn)
        n_pos, snapshot_saved = db.overwrite_positions(conn, investor_id, positions, snapshot_date)
        n_op = db.append_opinions(conn, investor_id, opinions, set_latest=True)
        n_adj = db.append_adjusts(conn, investor_id, adjusts)
        conn.commit()

    return {
        "status": "ok",
        "inserted": {"positions": n_pos, "opinions": n_op, "adjusts": n_adj},
        "snapshot_saved": snapshot_saved,
        "message": "刷新成功",
    }


# ---------------------------------------------------------------------------
# Backfill history
# ---------------------------------------------------------------------------

def backfill_history(investor_id: int) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        investor_name = inv["name"]

    prompt = _get_prompt_content("history_backfill").replace("{{investor_name}}", investor_name)
    data = _call_llm(prompt, f"请整理 {investor_name} 近 3-5 年的历史持仓与公开发言。")

    history_positions = data.get("history_positions") or []
    history_opinions = data.get("history_opinions") or []

    if not history_positions and not history_opinions:
        return {"status": "no_data", "message": "未获取到历史数据"}

    from datetime import datetime

    default_date = datetime.now().strftime("%Y-%m-%d")
    with celebrity_connection() as conn:
        initialize_schema(conn)
        n_pos = db.append_position_snapshots(conn, investor_id, history_positions, default_date)
        n_op = db.append_opinions(conn, investor_id, history_opinions)
        conn.commit()

    return {
        "status": "ok",
        "inserted": {"positions": n_pos, "opinions": n_op},
        "message": "历史回灌完成",
    }


# ---------------------------------------------------------------------------
# Performance evaluation
# ---------------------------------------------------------------------------

def generate_performance(investor_id: int) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        investor_name = inv["name"]

    prompt = _get_prompt_content("performance").replace("{{investor_name}}", investor_name)
    data = _call_llm(prompt, f"请评估 {investor_name} 的客观投资绩效。")

    with celebrity_connection() as conn:
        initialize_schema(conn)
        db.save_performance(conn, investor_id, data)
        conn.commit()
    return {"status": "ok", "performance": data}


def get_performance(investor_id: int) -> dict[str, Any] | None:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        return db.get_performance(conn, investor_id)


def save_performance(investor_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        db.save_performance(conn, investor_id, data)
        conn.commit()
    return {"status": "ok", "updated": True}


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

def review_opinions(investor_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Review selected opinions. items: [{id, publish_time, content}]."""
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        investor_name = inv["name"]

    check_list = [
        {"publish_time": it.get("publish_time", ""), "content": it.get("content", "")}
        for it in items
    ]
    prompt = (
        _get_prompt_content("opinion_review")
        .replace("{{investor_name}}", investor_name)
        .replace("{{check_opinion_list}}", json.dumps(check_list, ensure_ascii=False))
    )
    results = _call_llm(prompt, f"请核验以下观点。")

    if not isinstance(results, list):
        results = [results] if isinstance(results, dict) else []

    updated = 0
    with celebrity_connection() as conn:
        initialize_schema(conn)
        for i, item in enumerate(items):
            result = results[i] if i < len(results) else {}
            opinion_id = str(item.get("id", ""))
            if not opinion_id:
                continue
            confidence = str(result.get("confidence", "") or "")
            review_result = str(result.get("review_result", "") or "")
            db.update_opinion_review(conn, opinion_id, confidence, review_result)
            updated += 1
        conn.commit()
    return {"status": "ok", "updated": updated}


def review_adjusts(investor_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Review selected adjust records. items: [{id, time, action, target}]."""
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        investor_name = inv["name"]

    check_list = [
        {"time": it.get("time", ""), "action": it.get("action", ""), "target": it.get("target", "")}
        for it in items
    ]
    prompt = (
        _get_prompt_content("adjust_review")
        .replace("{{investor_name}}", investor_name)
        .replace("{{check_adjust_list}}", json.dumps(check_list, ensure_ascii=False))
    )
    results = _call_llm(prompt, f"请核验以下调仓记录。")

    if not isinstance(results, list):
        results = [results] if isinstance(results, dict) else []

    updated = 0
    with celebrity_connection() as conn:
        initialize_schema(conn)
        for i, item in enumerate(items):
            result = results[i] if i < len(results) else {}
            adjust_id = str(item.get("id", ""))
            if not adjust_id:
                continue
            profit_desc = str(result.get("profit_desc", "") or "")
            review_result = str(result.get("review_result", "") or "")
            db.update_adjust_review(conn, adjust_id, profit_desc, review_result)
            updated += 1
        conn.commit()
    return {"status": "ok", "updated": updated}


# ---------------------------------------------------------------------------
# Weekly dynamics
# ---------------------------------------------------------------------------

def get_weekly_dynamics() -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        items = db.get_weekly_dynamics(conn)
    return {"items": items}


# ---------------------------------------------------------------------------
# Position snapshots (read-only grouping by snapshot_date)
# ---------------------------------------------------------------------------

def get_position_snapshots(investor_id: int) -> dict[str, Any]:
    """Return historical position snapshots of one investor, grouped by snapshot_date.

    Each group (same snapshot_date) represents one historical full portfolio
    captured on that refresh. Returns snapshots ordered by date descending.
    """
    with celebrity_connection() as conn:
        initialize_schema(conn)
        inv = db.get_investor(conn, investor_id)
        if inv is None:
            raise CelebrityNotFoundError(f"投资人 {investor_id} 不存在")
        rows = db.list_position_snapshots(conn, investor_id)

    # Group rows by snapshot_date
    from collections import OrderedDict

    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        key = str(row.get("snapshot_date", ""))
        if key not in grouped:
            grouped[key] = []
        grouped[key].append({
            "id": row["id"],
            "target": row.get("target", ""),
            "percentage": row.get("percentage"),
            "source": row.get("source"),
            "confidence": row.get("confidence"),
        })

    snapshots = [
        {"snapshot_date": date, "positions": positions}
        for date, positions in grouped.items()
    ]
    return {"investor_id": investor_id, "snapshots": snapshots}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def get_prompt(key: str) -> dict[str, Any]:
    with celebrity_connection() as conn:
        initialize_schema(conn)
        prompt = db.get_prompt(conn, key)
    if prompt is None:
        raise CelebrityNotFoundError(f"提示词 {key} 不存在")
    return prompt


def update_prompt(key: str, content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if not content:
        raise CelebrityValidationError("提示词内容不能为空")
    with celebrity_connection() as conn:
        initialize_schema(conn)
        db.update_prompt(conn, key, content)
        conn.commit()
    return {"key": key, "updated": True}


def reset_prompt(key: str) -> dict[str, Any]:
    """Reset a prompt to its built-in default and clear the user-edit flag."""
    with celebrity_connection() as conn:
        initialize_schema(conn)
        try:
            content = db.reset_prompt_to_default(conn, key)
        except ValueError as exc:
            raise CelebrityNotFoundError(str(exc)) from exc
        conn.commit()
    return {"key": key, "content": content, "reset": True}


# ---------------------------------------------------------------------------
# Scheduled batch refresh
# ---------------------------------------------------------------------------

def refresh_all_investors() -> dict[str, Any]:
    """Refresh every investor. Failures are isolated and logged."""
    investors = list_investors()
    results: list[dict[str, Any]] = []
    for inv in investors:
        try:
            res = refresh_investor(inv["id"])
            results.append({"investor_id": inv["id"], "name": inv["name"], **res})
        except Exception as exc:
            logger.warning("Scheduled refresh failed for %s: %s", inv["name"], exc)
            results.append({"investor_id": inv["id"], "name": inv["name"], "status": "error", "error": str(exc)})
    return {"results": results}
