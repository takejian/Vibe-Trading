"""Global skill-approval registry backing the Skill Square.

A skill becomes *approved* once any investor runs a standalone Skill Square
trial that finishes successfully (a qualified conclusion). Approval is global
— every investor afterwards sees the skill in the orchestration "add skill"
catalog. Trial *history* stays private per local runtime owner; only the
approval bit lives here.

Persistence: a single JSON file at
``<runtime_root>/skills/approvals.json``::

    {
      "chanlun-analysis": {
        "approved": true,
        "approved_at": "2026-09-29T08:00:00+00:00",
        "source_run_id": "swarm-20260929-...-ab12cd34"
      }
    }

A later failed trial never flips an approved skill back to unapproved; callers
simply do not call :meth:`SkillApprovalStore.revoke` from the trial path.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from pydantic import BaseModel

from src.config.paths import get_skill_approvals_file


class SkillApproval(BaseModel):
    """Approval state for one assembled skill."""

    approved: bool = False
    approved_at: str | None = None
    source_run_id: str | None = None


class SkillApprovalStore:
    """File-backed, process-safe-enough mapping of skill name → approval."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = path if path is not None else get_skill_approvals_file()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------
    def _read(self) -> dict[str, dict]:
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            # Corrupt file must not take the Skill Square down; start empty and
            # rewrite on the next approval.
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(name): dict(payload)
            for name, payload in data.items()
            if isinstance(name, str) and isinstance(payload, dict)
        }

    def _write(self, data: dict[str, dict]) -> None:
        directory = os.path.dirname(os.fspath(self._path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".approvals-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def all(self) -> dict[str, SkillApproval]:
        """Return the full approval map (unapproved entries may be omitted)."""
        with self._lock:
            raw = self._read()
        return {
            name: SkillApproval.model_validate(payload)
            for name, payload in raw.items()
        }

    def approved_names(self) -> set[str]:
        """Names currently approved."""
        return {name for name, item in self.all().items() if item.approved}

    def is_approved(self, skill_name: str) -> bool:
        return bool(self.all().get(skill_name, SkillApproval()).approved)

    def mark_approved(self, skill_name: str, source_run_id: str | None = None) -> SkillApproval:
        """Approve a skill. Idempotent; keeps the first approval provenance."""
        if not skill_name or not isinstance(skill_name, str):
            raise ValueError("skill name must be a non-empty string")
        with self._lock:
            data = self._read()
            existing = data.get(skill_name)
            if isinstance(existing, dict) and existing.get("approved"):
                return SkillApproval.model_validate(existing)
            record = SkillApproval(
                approved=True,
                approved_at=datetime.now(timezone.utc).isoformat(),
                source_run_id=source_run_id,
            )
            data[skill_name] = record.model_dump()
            self._write(data)
            return record
