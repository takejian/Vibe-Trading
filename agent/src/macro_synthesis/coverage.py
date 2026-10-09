"""四支宏观团队当期结论的覆盖归集与材料加载。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.config.paths import get_swarm_runs_dir
from src.swarm.models import RunStatus, SwarmRun
from src.swarm.store import SwarmStore

from .models import MACRO_TEAMS, TEAM_TITLES, TeamCoverage

_SCAN_LIMIT = 200
_CONCLUSION_LEN = 200
_MAX_MATERIAL = 4000

_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+$")


def _clean_line(raw: str) -> str:
    """剥除 markdown 标记，返回可读文本行（与前端提取口径近似）。"""
    line = raw.strip()
    if not line or _TABLE_SEPARATOR_RE.match(line):
        return ""
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = re.sub(r"^>\s*", "", line)
    line = line.replace("**", "").replace("`", "")
    if "|" in line:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        line = " · ".join(cells)
    return line.strip()


def lead_conclusion(markdown: str | None, limit: int = _CONCLUSION_LEN) -> str:
    """从 markdown 报告提取首个实质行作为摘要。"""
    if not markdown:
        return ""
    candidates = [
        cleaned
        for raw in markdown.splitlines()
        if (cleaned := _clean_line(raw))
    ]
    if not candidates:
        return ""
    lead = next((c for c in candidates if len(c) >= 14), candidates[0])
    return lead if len(lead) <= limit else lead[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class TeamMaterial:
    """一支团队的完整结论材料（供 LLM 汇总）。"""

    team: str
    title: str
    run_id: str
    date: str
    report: str


def _load_store(store: SwarmStore | None) -> SwarmStore:
    return store or SwarmStore(get_swarm_runs_dir())


def collect(
    period_type: str,
    period: str,
    store: SwarmStore | None = None,
) -> list[TeamCoverage]:
    """归集四支团队在指定期次的结论覆盖情况。

    每支团队取该期内最近一条已完成的团队 run；``list_runs`` 已按创建时间
    倒序，故遍历时每个团队的第一条命中即为最新结论。
    """
    store = _load_store(store)
    runs = store.list_runs(limit=_SCAN_LIMIT)

    latest_team: dict[str, SwarmRun] = {}
    for run in runs:
        if run.kind != "team" or run.status != RunStatus.completed:
            continue
        if run.preset_name not in MACRO_TEAMS or run.preset_name in latest_team:
            continue
        stamp = run.completed_at or run.created_at
        from .periods import run_belongs

        if run_belongs(stamp, period_type, period):
            latest_team[run.preset_name] = run

    coverage: list[TeamCoverage] = []
    for team in MACRO_TEAMS:
        run = latest_team.get(team)
        if run is None:
            coverage.append(
                TeamCoverage(team=team, title=TEAM_TITLES[team], present=False)
            )
        else:
            coverage.append(
                TeamCoverage(
                    team=team,
                    title=TEAM_TITLES[team],
                    present=True,
                    run_id=run.id,
                    date=(run.completed_at or run.created_at or "")[:10],
                    conclusion=lead_conclusion(run.final_report),
                )
            )
    return coverage


def load_run(run_id: str, store: SwarmStore | None = None) -> SwarmRun | None:
    """按 run id 读取团队 run，失败返回 None。"""
    store = _load_store(store)
    run_file = store.run_dir(run_id) / "run.json"
    if not run_file.exists():
        return None
    try:
        return SwarmRun.model_validate_json(run_file.read_text(encoding="utf-8"))
    except ValueError:
        return None


def load_materials(
    coverage: list[TeamCoverage],
    store: SwarmStore | None = None,
) -> list[TeamMaterial]:
    """加载所有已覆盖团队的完整报告文本（截断保护上下文长度）。"""
    materials: list[TeamMaterial] = []
    for item in coverage:
        if not item.present or not item.run_id:
            continue
        run = load_run(item.run_id, store)
        report = (run.final_report if run else "") or ""
        if len(report) > _MAX_MATERIAL:
            report = report[:_MAX_MATERIAL].rstrip() + "\n…（报告截断）"
        materials.append(
            TeamMaterial(
                team=item.team,
                title=item.title,
                run_id=item.run_id,
                date=item.date or "",
                report=report,
            )
        )
    return materials
