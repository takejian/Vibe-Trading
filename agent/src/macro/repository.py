"""Persistence port and MySQL adapter for the macro analysis module."""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional, Protocol, runtime_checkable

from src.macro.db import MacroDataAccessError, macro_connection
from src.macro.models import MacroJudgment, PromptDef

logger = logging.getLogger(__name__)

_JUDGMENT_COLUMNS = (
    "id",
    "economy",
    "statistics_date",
    "current_cycle",
    "judgment_result",
    "dimension_check",
    "meso_verify",
    "history_cycle_anchor",
    "judgment_confidence",
    "core_support",
    "core_risk",
    "extended_remark",
    "create_time",
)

_PROMPT_COLUMNS = (
    "id",
    "code",
    "name",
    "prompt_text",
    "enabled",
    "sort_order",
    "orchestration_config",
    "create_time",
    "update_time",
)


def _iso(value: object) -> Optional[str]:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    return str(value) if value is not None else None


def _row_to_judgment(row: dict) -> MacroJudgment:
    return MacroJudgment(
        id=row.get("id"),
        economy=row["economy"],
        statistics_date=row["statistics_date"],
        current_cycle=row.get("current_cycle") or "",
        judgment_result=row.get("judgment_result") or "",
        dimension_check=row.get("dimension_check") or "",
        meso_verify=row.get("meso_verify") or "",
        history_cycle_anchor=row.get("history_cycle_anchor") or "",
        judgment_confidence=row.get("judgment_confidence") or "",
        core_support=row.get("core_support") or "",
        core_risk=row.get("core_risk") or "",
        extended_remark=row.get("extended_remark") or "",
        create_time=_iso(row.get("create_time")),
    )


def _row_to_prompt(row: dict) -> PromptDef:
    return PromptDef(
        id=row.get("id"),
        code=row["code"],
        name=row["name"],
        prompt_text=row.get("prompt_text") or "",
        enabled=bool(row.get("enabled")),
        sort_order=row.get("sort_order") or 0,
        orchestration_config=row.get("orchestration_config"),
        create_time=_iso(row.get("create_time")),
        update_time=_iso(row.get("update_time")),
    )


@runtime_checkable
class MacroRepository(Protocol):
    """Persistence port; the service depends only on this interface."""

    def get_judgment(self, economy: str, statistics_date: str) -> Optional[MacroJudgment]: ...

    def insert_judgment(self, judgment: MacroJudgment) -> MacroJudgment: ...

    def list_judgments(self, economy: str, limit: int = 100) -> list[MacroJudgment]: ...

    def list_prompts(self) -> list[PromptDef]: ...

    def get_prompt(self, code: str) -> Optional[PromptDef]: ...

    def update_prompt_text(self, code: str, prompt_text: str) -> Optional[PromptDef]: ...


class MySQLMacroRepository:
    """MySQL-backed implementation using short-lived connections."""

    def _query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with macro_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return list(cur.fetchall())
        except MacroDataAccessError:
            raise
        except Exception as exc:
            raise MacroDataAccessError("宏观分析数据库查询失败。") from exc

    def get_judgment(self, economy: str, statistics_date: str) -> Optional[MacroJudgment]:
        rows = self._query_all(
            f"SELECT {', '.join(_JUDGMENT_COLUMNS)} FROM macro_cycle_judgment "
            "WHERE economy = %s AND statistics_date = %s ORDER BY id DESC LIMIT 1",
            (economy, statistics_date),
        )
        return _row_to_judgment(rows[0]) if rows else None

    def list_judgments(self, economy: str, limit: int = 100) -> list[MacroJudgment]:
        limit = max(1, min(int(limit or 100), 500))
        rows = self._query_all(
            f"SELECT {', '.join(_JUDGMENT_COLUMNS)} FROM macro_cycle_judgment "
            "WHERE economy = %s ORDER BY statistics_date DESC, id DESC LIMIT %s",
            (economy, limit),
        )
        return [_row_to_judgment(row) for row in rows]

    def insert_judgment(self, judgment: MacroJudgment) -> MacroJudgment:
        sql = (
            "INSERT INTO macro_cycle_judgment "
            "(economy, statistics_date, current_cycle, judgment_result, dimension_check, "
            "meso_verify, history_cycle_anchor, judgment_confidence, core_support, "
            "core_risk, extended_remark) VALUES "
            "(%(economy)s, %(statistics_date)s, %(current_cycle)s, %(judgment_result)s, "
            "%(dimension_check)s, %(meso_verify)s, %(history_cycle_anchor)s, "
            "%(judgment_confidence)s, %(core_support)s, %(core_risk)s, %(extended_remark)s)"
        )
        params = {
            "economy": judgment.economy,
            "statistics_date": judgment.statistics_date,
            "current_cycle": judgment.current_cycle,
            "judgment_result": judgment.judgment_result,
            "dimension_check": judgment.dimension_check,
            "meso_verify": judgment.meso_verify,
            "history_cycle_anchor": judgment.history_cycle_anchor,
            "judgment_confidence": judgment.judgment_confidence,
            "core_support": judgment.core_support,
            "core_risk": judgment.core_risk,
            "extended_remark": judgment.extended_remark,
        }
        try:
            with macro_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    new_id = int(cur.lastrowid)
                conn.commit()
        except MacroDataAccessError:
            raise
        except Exception as exc:
            raise MacroDataAccessError("宏观分析结果写入失败。") from exc
        stored = self.get_judgment(judgment.economy, judgment.statistics_date)
        if stored is not None and stored.id == new_id:
            return stored
        # Fallback if the re-read races another write; return the input with id.
        return MacroJudgment(**{**judgment.__dict__, "id": new_id})

    def list_prompts(self) -> list[PromptDef]:
        rows = self._query_all(
            f"SELECT {', '.join(_PROMPT_COLUMNS)} FROM macro_analysis_prompt "
            "ORDER BY sort_order ASC, id ASC"
        )
        return [_row_to_prompt(row) for row in rows]

    def get_prompt(self, code: str) -> Optional[PromptDef]:
        rows = self._query_all(
            f"SELECT {', '.join(_PROMPT_COLUMNS)} FROM macro_analysis_prompt WHERE code = %s",
            (code,),
        )
        return _row_to_prompt(rows[0]) if rows else None

    def update_prompt_text(self, code: str, prompt_text: str) -> Optional[PromptDef]:
        try:
            with macro_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE macro_analysis_prompt SET prompt_text = %s WHERE code = %s",
                        (prompt_text, code),
                    )
                    affected = cur.rowcount
                conn.commit()
        except MacroDataAccessError:
            raise
        except Exception as exc:
            raise MacroDataAccessError("提示词保存失败。") from exc
        if not affected:
            return None
        return self.get_prompt(code)
