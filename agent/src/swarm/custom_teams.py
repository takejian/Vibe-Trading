"""User-owned, reusable custom team definitions ("my teams").

A custom team is a canvas graph the investor explicitly saved with
"另存为我的团队". Unlike the one-off ``custom`` payload (which lives only on
the run snapshot), a custom team is a reusable JSON file under
``<runtime_root>/swarm/custom_teams/``.

Ownership model: the product is a loopback single-user application, so files
under the runtime root are already private to the local operator — matching
the "仅本人可见" rule for evaluation history. Built-in presets are never
modified; deleting a team never touches run snapshots (runs embed their own
full agent/task graph).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.config.paths import get_custom_teams_dir
from src.swarm.custom_spec import validate_custom_spec_graph

_TEAM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_NAME_LEN = 80
_MAX_DESCRIPTION_LEN = 400


class DuplicateTeamNameError(ValueError):
    """Raised when a team name collides with another of the owner's teams."""


class CustomTeam(BaseModel):
    """One saved reusable team definition."""

    id: str
    name: str
    description: str = ""
    source_preset: str
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CustomTeamStore:
    """File-backed CRUD for custom teams."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self._dir = base_dir if base_dir is not None else get_custom_teams_dir()

    # ------------------------------------------------------------------
    def _path_for(self, team_id: str) -> str:
        if not _TEAM_ID_RE.match(team_id or ""):
            raise ValueError(f"团队标识不合法: {team_id!r}")
        return os.path.join(self._dir, f"{team_id}.json")

    def _write(self, team: CustomTeam) -> None:
        os.makedirs(self._dir, exist_ok=True)
        target = self._path_for(team.id)
        fd, tmp_name = tempfile.mkstemp(prefix=".team-", suffix=".json", dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(team.model_dump(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    def list_teams(self) -> list[CustomTeam]:
        if not os.path.isdir(self._dir):
            return []
        teams: list[CustomTeam] = []
        for entry in os.listdir(self._dir):
            if not entry.endswith(".json") or entry.startswith("."):
                continue
            try:
                with open(os.path.join(self._dir, entry), encoding="utf-8") as handle:
                    teams.append(CustomTeam.model_validate(json.load(handle)))
            except (OSError, json.JSONDecodeError, ValueError):
                # Skip corrupt rows rather than failing the whole gallery.
                continue
        teams.sort(key=lambda team: team.updated_at, reverse=True)
        return teams

    def get_team(self, team_id: str) -> CustomTeam:
        path = self._path_for(team_id)
        try:
            with open(path, encoding="utf-8") as handle:
                return CustomTeam.model_validate(json.load(handle))
        except FileNotFoundError:
            raise FileNotFoundError(f"自定义团队不存在: {team_id}") from None

    def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        target = name.strip()
        return any(
            team.name == target and team.id != exclude_id for team in self.list_teams()
        )

    # ------------------------------------------------------------------
    def _validate_payload(
        self,
        name: str,
        description: str,
        source_preset: str,
        nodes: object,
        edges: object,
    ) -> tuple[str, str, list[dict], list[dict]]:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("团队名称不能为空")
        if len(clean_name) > _MAX_NAME_LEN:
            raise ValueError(f"团队名称不能超过 {_MAX_NAME_LEN} 个字符")
        clean_desc = (description or "").strip()
        if len(clean_desc) > _MAX_DESCRIPTION_LEN:
            raise ValueError(f"适用场景简介不能超过 {_MAX_DESCRIPTION_LEN} 个字符")
        if not isinstance(source_preset, str) or not source_preset.strip():
            raise ValueError("缺少来源内置团队预设")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("至少需要一个角色节点")
        if not isinstance(edges, list):
            raise ValueError("协作连线必须为列表")
        # Authoritative graph check (same rules as launching an evaluation).
        validate_custom_spec_graph(
            source_preset.strip(), {"nodes": nodes, "edges": edges}
        )
        return clean_name, clean_desc, list(nodes), list(edges)

    def save_team(
        self,
        *,
        name: str,
        description: str,
        source_preset: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> CustomTeam:
        """Create a new team; rejects duplicate names of existing teams."""
        clean_name, clean_desc, clean_nodes, clean_edges = self._validate_payload(
            name, description, source_preset, nodes, edges
        )
        if self.name_exists(clean_name):
            raise DuplicateTeamNameError(f"已存在同名自定义团队: {clean_name!r}，请更换名称")
        now = datetime.now(timezone.utc).isoformat()
        team = CustomTeam(
            id=f"team-{uuid.uuid4().hex[:12]}",
            name=clean_name,
            description=clean_desc,
            source_preset=source_preset.strip(),
            nodes=clean_nodes,
            edges=clean_edges,
            created_at=now,
            updated_at=now,
        )
        self._write(team)
        return team

    def update_team(
        self,
        team_id: str,
        *,
        name: str,
        description: str,
        source_preset: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> CustomTeam:
        """Replace an existing team in place; duplicate names (other self) rejected."""
        existing = self.get_team(team_id)
        clean_name, clean_desc, clean_nodes, clean_edges = self._validate_payload(
            name, description, source_preset, nodes, edges
        )
        if self.name_exists(clean_name, exclude_id=team_id):
            raise DuplicateTeamNameError(f"已存在同名自定义团队: {clean_name!r}，请更换名称")
        updated = existing.model_copy(
            update={
                "name": clean_name,
                "description": clean_desc,
                "source_preset": source_preset.strip(),
                "nodes": clean_nodes,
                "edges": clean_edges,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write(updated)
        return updated

    def delete_team(self, team_id: str) -> None:
        """Delete a team; run snapshots are intentionally untouched."""
        path = self._path_for(team_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"自定义团队不存在: {team_id}") from None
