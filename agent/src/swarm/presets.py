"""Swarm YAML preset loader.

Reads YAML preset files from the bundled ``presets/`` directory next to this
module and parses them into SwarmRun / SwarmAgentSpec / SwarmTask data models.
Keeping the YAMLs inside the ``src.swarm`` package guarantees identical
behavior under editable installs and built wheels.

User-supplied presets are also discovered from ``~/.vibe-trading/swarm/
presets/`` — the same pattern as user skills (``src/agent/skills.py``):
the user directory is searched first, so a user preset can both add to and
override the bundled roster by name, and nothing needs to be copied into
site-packages (where it would be wiped by the next ``pip install -U``).
Preset names are validated to a single path segment before any filesystem
lookup, so a name can never escape either presets directory.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter

import yaml

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.task_store import topological_layers, validate_dag

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
#: User-created presets; searched before the bundled directory so user files
#: can add to and override the roster by name (mirrors USER_SKILLS_DIR in
#: ``src/agent/skills.py``). Survives package upgrades.
USER_PRESETS_DIR = Path.home() / ".vibe-trading" / "swarm" / "presets"
_INTERNAL_TEMPLATE_VARS = {"upstream_context"}

#: Preset category identifiers, modeled on the standard research taxonomy of
#: buy-side funds and sell-side houses: analysis style first (technical /
#: fundamental / quant / sentiment), then strategy style (macro & strategy /
#: event-driven / asset allocation), then asset class desks (fixed income &
#: derivatives / alternatives) and the independent risk function.
PRESET_CATEGORY_ORDER: tuple[str, ...] = (
    "technical",
    "fundamental",
    "macro",
    "quant",
    "sentiment",
    "event_driven",
    "allocation",
    "fixed_income_derivatives",
    "alternatives",
    "risk",
    "other",
)

#: Canonical (English) metadata per category. The web UI renders localized
#: labels via i18n keys (``swarmStudio.category.<id>``); these strings serve
#: CLI/MCP consumers and as fallback labels.
PRESET_CATEGORY_META: dict[str, dict[str, str]] = {
    "technical": {
        "title": "Technical Analysis",
        "description": "Price-action, indicators, patterns and wave-based market timing teams.",
    },
    "fundamental": {
        "title": "Fundamental & Equity Research",
        "description": "Financial statements, valuation, earnings and bottom-up stock research.",
    },
    "macro": {
        "title": "Macro Economy & Strategy",
        "description": "Central banks, economic cycle, geopolitics and top-down strategy teams.",
    },
    "quant": {
        "title": "Quant Research & Arbitrage",
        "description": "Factor research, machine learning, statistical arbitrage and pairs trading.",
    },
    "sentiment": {
        "title": "Sentiment & Alternative Data",
        "description": "News, social media, flows and alternative-data signal teams.",
    },
    "event_driven": {
        "title": "Event-Driven",
        "description": "Corporate and market event deep-dive teams (event-driven hedge fund style).",
    },
    "allocation": {
        "title": "Asset Allocation & Portfolio Management",
        "description": "Multi-asset allocation, ETF/FOF portfolio construction and investment committees.",
    },
    "fixed_income_derivatives": {
        "title": "Fixed Income & Derivatives",
        "description": "Rates, credit, convertible bonds and options/derivatives strategy desks.",
    },
    "alternatives": {
        "title": "Alternative Assets",
        "description": "Digital assets (crypto) and commodity research/trading teams.",
    },
    "risk": {
        "title": "Risk Management",
        "description": "Independent drawdown, tail-risk and mandate risk oversight committees.",
    },
    "other": {
        "title": "Other",
        "description": "Presets without a standard category mapping.",
    },
}

#: Bundled preset name -> category id. Every bundled YAML is classified once
#: here; a YAML may still declare its own ``category`` key to override this
#: mapping (only known category ids are honored).
PRESET_CATEGORIES: dict[str, str] = {
    # Technical analysis
    "technical_analysis_panel": "technical",
    # Fundamental / equity research
    "fundamental_research_team": "fundamental",
    "equity_research_team": "fundamental",
    "value_investing_committee": "fundamental",
    "earnings_research_desk": "fundamental",
    "global_equities_desk": "fundamental",
    # Macro economy & strategy
    "macro_strategy_forum": "macro",
    "macro_rates_fx_desk": "macro",
    "geopolitical_war_room": "macro",
    "sector_rotation_team": "macro",
    # Quant research & arbitrage
    "quant_strategy_desk": "quant",
    "factor_research_committee": "quant",
    "ml_quant_lab": "quant",
    "statistical_arbitrage_desk": "quant",
    "pairs_research_lab": "quant",
    # Sentiment & alternative data
    "sentiment_intelligence_team": "sentiment",
    "social_alpha_team": "sentiment",
    # Event-driven
    "event_driven_task_force": "event_driven",
    # Asset allocation & portfolio management
    "global_allocation_committee": "allocation",
    "etf_allocation_desk": "allocation",
    "fund_selection_panel": "allocation",
    "portfolio_review_board": "allocation",
    "investment_committee": "allocation",
    # Fixed income & derivatives
    "credit_research_team": "fixed_income_derivatives",
    "convertible_bond_team": "fixed_income_derivatives",
    "derivatives_strategy_desk": "fixed_income_derivatives",
    # Alternative assets (digital assets & commodities)
    "crypto_trading_desk": "alternatives",
    "crypto_research_lab": "alternatives",
    "commodity_research_team": "alternatives",
    # Risk management
    "risk_committee": "risk",
}


def preset_category(name: str, data: dict | None = None) -> str:
    """Return the category id for a preset.

    Resolution order:
        1. A ``category`` key declared in the preset YAML — but only when it
           names a known category id, so free-text YAML values cannot create
           phantom groups the UI cannot label.
        2. The bundled :data:`PRESET_CATEGORIES` mapping.
        3. ``"other"`` (covers user presets that declare nothing).

    Args:
        name: Preset name (file stem / YAML ``name``).
        data: Parsed preset YAML, if already loaded.
    """
    if data:
        declared = data.get("category")
        if isinstance(declared, str) and declared.strip() in PRESET_CATEGORY_META:
            return declared.strip()
    return PRESET_CATEGORIES.get(name, "other")


def _redact_home(path: Path) -> str:
    """Render ``path`` with the home prefix collapsed to ``~`` so user-facing
    errors never leak the absolute home directory (CWE-209)."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _validate_preset_name(name: str) -> str:
    """Reject names that are empty or could escape a presets directory.

    Preset names map directly to ``<dir>/<name>.yaml``; a name carrying a
    path separator or ``..`` would resolve outside the directory. The bundled
    path had the same latent exposure — validating here covers both.

    Returns:
        The stripped name.

    Raises:
        ValueError: Empty name, path separators, or parent references.
    """
    cleaned = (name or "").strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"invalid preset name: {name!r}")
    return cleaned


def _preset_search_dirs() -> tuple[Path, ...]:
    """Directories searched for presets, highest priority first."""
    return (USER_PRESETS_DIR, PRESETS_DIR)


def resolve_preset_path(name: str) -> Path | None:
    """Return the YAML path for *name* (user dir first), or ``None``."""
    cleaned = _validate_preset_name(name)
    for directory in _preset_search_dirs():
        path = directory / f"{cleaned}.yaml"
        if path.is_file():
            return path
    return None


def load_preset(name: str) -> dict:
    """Load a YAML preset by name (user directory first, then bundled).

    Args:
        name: Preset name (without .yaml extension).

    Returns:
        Parsed YAML dict.

    Raises:
        ValueError: If the name is empty or contains path separators.
        FileNotFoundError: If the preset file does not exist in either the
            user directory (``~/.vibe-trading/swarm/presets/``) or the
            bundled package directory.
    """
    path = resolve_preset_path(name)
    if path is None:
        available = sorted({
            p.stem
            for directory in _preset_search_dirs()
            if directory.exists()
            for p in directory.glob("*.yaml")
        })
        raise FileNotFoundError(
            f"Preset {name!r} not found in {_redact_home(USER_PRESETS_DIR)} or "
            f"the bundled presets. Available: {available}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def list_presets() -> list[dict]:
    """Return summary info for all available presets, sorted by name.

    User presets (``~/.vibe-trading/swarm/presets/``) are listed alongside the
    bundled roster; when both directories carry the same file stem, the user
    preset wins — the same override rule as user skills.

    Returns:
        List of dicts with keys: name, title, description, category,
        agent_count, variables, source (``"user"`` or ``"bundled"``).
    """
    by_stem: dict[str, dict] = {}
    for directory, source in ((PRESETS_DIR, "bundled"), (USER_PRESETS_DIR, "user")):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            preset_name = data.get("name", path.stem)
            # Later iteration (user) intentionally replaces bundled stems.
            by_stem[path.stem] = {
                "name": preset_name,
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "category": preset_category(preset_name, data),
                "agent_count": len(data.get("agents", [])),
                "variables": data.get("variables", []),
                "source": source,
            }

    return sorted(by_stem.values(), key=lambda entry: entry["name"])


def _declared_variable_names(raw_variables: list) -> set[str]:
    """Extract variable names from the YAML variables section."""
    names: set[str] = set()
    for item in raw_variables:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = str(item)
        if name:
            names.add(str(name))
    return names


def _template_variables(template: str) -> set[str]:
    """Return Python format fields referenced by a prompt template."""
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template or ""):
        if not field_name:
            continue
        root = field_name.split(".", 1)[0].split("[", 1)[0]
        if root and root not in _INTERNAL_TEMPLATE_VARS:
            variables.add(root)
    return variables


def inspect_preset(name: str) -> dict:
    """Validate a swarm preset and return a dry-run execution plan.

    This does not start workers or call an LLM. It catches common YAML/DAG
    mistakes early and exposes the topological task layers used by the runtime.
    """
    data = load_preset(name)
    run = build_run_from_preset(name, {})

    errors: list[str] = []
    warnings: list[str] = []

    agent_ids = [agent.id for agent in run.agents]
    task_ids = [task.id for task in run.tasks]
    agent_id_set = set(agent_ids)
    task_id_set = set(task_ids)

    for duplicate in sorted(item for item, count in Counter(agent_ids).items() if count > 1):
        errors.append(f"Duplicate agent id: {duplicate}")
    for duplicate in sorted(item for item, count in Counter(task_ids).items() if count > 1):
        errors.append(f"Duplicate task id: {duplicate}")

    for task in run.tasks:
        if task.agent_id not in agent_id_set:
            errors.append(f"Task '{task.id}' references unknown agent '{task.agent_id}'")
        for _, upstream_task_id in task.input_from.items():
            if upstream_task_id not in task_id_set:
                errors.append(
                    f"Task '{task.id}' input_from references unknown task '{upstream_task_id}'"
                )

    layers: list[list[str]] = []
    try:
        validate_dag(run.tasks)
        layers = topological_layers(run.tasks)
    except ValueError as exc:
        errors.append(str(exc))

    dependents: dict[str, list[str]] = defaultdict(list)
    for task in run.tasks:
        for dep in task.depends_on:
            dependents[dep].append(task.id)

    def is_upstream(candidate: str, task_id: str) -> bool:
        """Return whether candidate can reach task_id through dependency edges."""
        seen: set[str] = set()
        stack = [candidate]
        while stack:
            current = stack.pop()
            if current == task_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(dependents.get(current, []))
        return False

    for task in run.tasks:
        for key, upstream_task_id in task.input_from.items():
            if upstream_task_id in task_id_set and not is_upstream(upstream_task_id, task.id):
                warnings.append(
                    f"Task '{task.id}' input_from '{key}' references '{upstream_task_id}', "
                    "which is not upstream in the DAG"
                )

    declared_variables = _declared_variable_names(data.get("variables", []))
    used_variables: set[str] = set()
    for task in data.get("tasks", []):
        try:
            used_variables.update(_template_variables(task.get("prompt_template", "")))
        except ValueError as exc:
            errors.append(f"Task '{task.get('id', '?')}' has invalid prompt template: {exc}")

    missing_declarations = sorted(used_variables - declared_variables)
    unused_declarations = sorted(declared_variables - used_variables)
    if missing_declarations:
        warnings.append(
            "Prompt templates use undeclared variables: " + ", ".join(missing_declarations)
        )
    if unused_declarations:
        warnings.append(
            "Declared variables are not used by task prompt templates: "
            + ", ".join(unused_declarations)
        )

    task_agent = {task.id: task.agent_id for task in run.tasks}
    return {
        "name": data.get("name", name),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "category": preset_category(data.get("name", name), data),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "variables": sorted(declared_variables),
        "used_variables": sorted(used_variables),
        "agents": [
            {"id": agent.id, "role": agent.role, "tools": agent.tools, "skills": agent.skills}
            for agent in run.agents
        ],
        "tasks": [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "depends_on": task.depends_on,
                "input_from": task.input_from,
            }
            for task in run.tasks
        ],
        "layers": [
            [{"task_id": task_id, "agent_id": task_agent.get(task_id, "")} for task_id in layer]
            for layer in layers
        ],
    }


def get_preset_detail(name: str) -> dict:
    """Return the full editor payload for one preset (web orchestration).

    Unlike :func:`list_presets` (summaries) and :func:`inspect_preset`
    (validation dry-run, intentionally sparse), this exposes everything the
    web canvas needs to render an editable graph: each agent's duty, tools,
    skills and timeout; each task's prompt template and dependency edges;
    the preset-wide tool catalog (the trust boundary for checkbox choices);
    and the topological execution layers (canvas layout).

    Raises:
        FileNotFoundError: Preset does not exist.
    """
    data = load_preset(name)
    run = build_run_from_preset(name, {})
    layers = topological_layers(run.tasks)

    catalog = sorted({tool for agent in run.agents for tool in agent.tools})
    return {
        "name": data.get("name", name),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "category": preset_category(data.get("name", name), data),
        "variables": data.get("variables", []),
        "agents": [
            {
                "id": agent.id,
                "role": agent.role,
                "system_prompt": agent.system_prompt,
                "tools": list(agent.tools),
                "skills": list(agent.skills),
                "max_iterations": agent.max_iterations,
                "timeout_seconds": agent.timeout_seconds,
                "model_name": agent.model_name,
            }
            for agent in run.agents
        ],
        "tasks": [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "prompt_template": task.prompt_template,
                "depends_on": list(task.depends_on),
                "input_from": dict(task.input_from),
            }
            for task in run.tasks
        ],
        "tool_catalog": catalog,
        "skill_catalog": sorted({skill for agent in run.agents for skill in agent.skills}),
        "layers": [list(layer) for layer in layers],
    }


def build_run_from_preset(preset_name: str, user_vars: dict[str, str]) -> SwarmRun:
    """Create a SwarmRun from a preset with user variables applied.

    Steps:
        1. Load preset YAML
        2. Create SwarmAgentSpec list from agents section
        3. Create SwarmTask list from tasks section
        4. Generate run_id: f"swarm-{datetime}-{uuid[:8]}"
        5. Return SwarmRun with all fields populated

    Args:
        preset_name: Name of the preset to load.
        user_vars: User-provided variables for prompt template rendering.

    Returns:
        Fully constructed SwarmRun instance (status=pending).

    Raises:
        FileNotFoundError: If preset does not exist.
        ValueError: If preset YAML is malformed.
    """
    data = load_preset(preset_name)

    # Parse agents
    agents: list[SwarmAgentSpec] = []
    for agent_data in data.get("agents", []):
        agents.append(SwarmAgentSpec(
            id=agent_data["id"],
            role=agent_data.get("role", ""),
            system_prompt=agent_data.get("system_prompt", ""),
            tools=agent_data.get("tools", []),
            skills=agent_data.get("skills", []),
            max_iterations=agent_data.get("max_iterations", 25),
            timeout_seconds=agent_data.get("timeout_seconds", 300),
            model_name=agent_data.get("model_name"),
            max_retries=agent_data.get("max_retries", 2),
        ))

    # Parse tasks, initialize blocked_by from depends_on
    tasks: list[SwarmTask] = []
    for task_data in data.get("tasks", []):
        depends_on = task_data.get("depends_on", [])
        status = TaskStatus.blocked if depends_on else TaskStatus.pending
        tasks.append(SwarmTask(
            id=task_data["id"],
            agent_id=task_data["agent_id"],
            prompt_template=task_data.get("prompt_template", ""),
            depends_on=depends_on,
            blocked_by=list(depends_on),
            input_from=task_data.get("input_from", {}),
            status=status,
        ))

    # Generate run ID
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    run_id = f"swarm-{ts}-{short_uuid}"

    return SwarmRun(
        id=run_id,
        preset_name=preset_name,
        status=RunStatus.pending,
        user_vars=user_vars,
        agents=agents,
        tasks=tasks,
        created_at=now.isoformat(),
    )
