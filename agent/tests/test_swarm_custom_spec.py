"""Tests for web-orchestrated single-use swarm customizations.

Covers ``src.swarm.custom_spec.build_run_from_custom_spec``: graph
validation (cycles/orphans/dangling/self-loop), node field validation,
the preset tool-catalog trust boundary, upstream-placeholder injection,
question suffixing, and the customized-run snapshot fields.

No LLM, network, or filesystem runs are involved — only run construction.
"""

from __future__ import annotations

import pytest

from src.swarm.custom_spec import build_run_from_custom_spec
from src.swarm.task_store import topological_layers

PRESET = "investment_committee"


class _FallbackDict(dict):
    def __missing__(self, key: str) -> str:  # mirrors worker.py rendering
        return f"(determine {key})"


def _node(node_id: str, **overrides) -> dict:
    base = {
        "id": node_id,
        "role": node_id,
        "duty": f"Duty of {node_id}",
        "tools": ["load_skill", "get_market_data"],
        "timeout_seconds": 300,
        "source_task_id": {
            "bull_advocate": "task-bull",
            "bear_advocate": "task-bear",
            "risk_officer": "task-risk",
            "portfolio_manager": "task-decision",
        }.get(node_id),
        "is_new": False,
    }
    base.update(overrides)
    return base


def _edge(up: str, down: str) -> dict:
    return {"upstream": up, "downstream": down}


def _ic_spec(**overrides) -> dict:
    spec = {
        "target": "600519.SH",
        "question": "当前市场环境下做多还是做空？",
        "nodes": [
            _node("bull_advocate"),
            _node("bear_advocate"),
            _node("risk_officer"),
            _node(
                "portfolio_manager",
                duty="You chair the committee.\n\n{upstream_context}",
                tools=["backtest", "load_skill"],
                timeout_seconds=1800,
            ),
        ],
        "edges": [
            _edge("bull_advocate", "risk_officer"),
            _edge("bear_advocate", "risk_officer"),
            _edge("risk_officer", "portfolio_manager"),
        ],
    }
    spec.update(overrides)
    return spec


def _agent(run, agent_id: str):
    return next(a for a in run.agents if a.id == agent_id)


def _task_for(run, agent_id: str):
    agent_task = {t.agent_id: t for t in run.tasks}
    return agent_task[agent_id]


def test_happy_path_builds_layered_customized_run():
    run = build_run_from_custom_spec(PRESET, _ic_spec())

    assert run.customized is True
    assert run.research_target == "600519.SH"
    assert run.research_question == "当前市场环境下做多还是做空？"
    assert run.preset_name == PRESET
    assert run.user_vars["target"] == "600519.SH"
    assert run.user_vars["question"] == run.research_question

    assert len(run.agents) == 4
    assert len(run.tasks) == 4
    assert {a.id for a in run.agents} == {
        "bull_advocate",
        "bear_advocate",
        "risk_officer",
        "portfolio_manager",
    }

    layers = topological_layers(run.tasks)
    assert len(layers) == 3
    # last layer is the final decision task
    assert _task_for(run, "portfolio_manager").id in layers[-1]
    assert set(layers[0]) == {
        _task_for(run, "bull_advocate").id,
        _task_for(run, "bear_advocate").id,
    }

    risk_task = _task_for(run, "risk_officer")
    assert set(risk_task.depends_on) == {
        _task_for(run, "bull_advocate").id,
        _task_for(run, "bear_advocate").id,
    }
    assert len(risk_task.input_from) == 2
    assert set(risk_task.input_from.values()) == set(risk_task.depends_on)
    assert risk_task.status.value == "blocked"

    bull_task = _task_for(run, "bull_advocate")
    assert bull_task.depends_on == []
    assert bull_task.status.value == "pending"
    assert bull_task.input_from == {}


def test_original_node_preserves_skills_iterations_and_prompt():
    run = build_run_from_custom_spec(PRESET, _ic_spec())
    pm = _agent(run, "portfolio_manager")
    assert pm.skills == ["strategy-generate", "asset-allocation"]
    assert pm.max_iterations == 50
    assert pm.timeout_seconds == 1800
    pm_task = _task_for(run, "portfolio_manager")
    assert "make the final investment decision" in pm_task.prompt_template
    assert pm_task.prompt_template.endswith(
        "Research question: 当前市场环境下做多还是做空？"
    )


def test_upstream_placeholder_appended_only_when_needed():
    run = build_run_from_custom_spec(PRESET, _ic_spec())

    # duty without placeholder but with incoming edges → appended once
    risk_prompt = _agent(run, "risk_officer").system_prompt
    assert risk_prompt.endswith("{upstream_context}")
    assert risk_prompt.count("{upstream_context}") == 1

    # duty already carried the placeholder → not duplicated
    pm_prompt = _agent(run, "portfolio_manager").system_prompt
    assert pm_prompt.count("{upstream_context}") == 1

    # start node with no incoming edges → no placeholder
    bull_prompt = _agent(run, "bull_advocate").system_prompt
    assert "{upstream_context}" not in bull_prompt


def test_question_with_braces_renders_safely():
    spec = _ic_spec(question="evaluate {target} and {weird} {")
    run = build_run_from_custom_spec(PRESET, spec)
    template = _task_for(run, "bull_advocate").prompt_template
    # Must render the same way the worker renders templates, without raising.
    rendered = template.format_map(_FallbackDict(run.user_vars))
    assert "evaluate {target} and {weird} {" in rendered


def test_tools_outside_preset_catalog_are_stripped():
    spec = _ic_spec(
        nodes=[
            _node("bull_advocate", tools=["get_market_data", "rm_rf_everything", 123]),
            _node("bear_advocate"),
            _node("risk_officer"),
            _node("portfolio_manager"),
        ]
    )
    run = build_run_from_custom_spec(PRESET, spec)
    bull = _agent(run, "bull_advocate")
    assert "rm_rf_everything" not in bull.tools
    assert 123 not in bull.tools
    assert "get_market_data" in bull.tools


def test_new_node_gets_defaults_and_empty_skills():
    spec = _ic_spec(
        nodes=[
            _node("bull_advocate"),
            _node("bear_advocate"),
            _node("risk_officer"),
            _node("portfolio_manager"),
            _node(
                "macro_observer",
                role="宏观观察员",
                duty="观察宏观环境",
                tools=["get_market_data"],
                timeout_seconds=120,
                source_task_id=None,
                is_new=True,
            ),
        ],
        edges=[
            _edge("macro_observer", "portfolio_manager"),
            _edge("bull_advocate", "risk_officer"),
            _edge("bear_advocate", "risk_officer"),
            _edge("risk_officer", "portfolio_manager"),
        ],
    )
    run = build_run_from_custom_spec(PRESET, spec)
    observer = _agent(run, "macro_observer")
    assert observer.skills == []
    assert observer.max_iterations == 25
    assert observer.model_name is None
    assert "{upstream_context}" not in observer.system_prompt
    pm_task = _task_for(run, "portfolio_manager")
    assert _task_for(run, "macro_observer").id in pm_task.depends_on


@pytest.mark.parametrize(
    "mutate",
    [
        # cycle
        lambda s: s["edges"].append(_edge("risk_officer", "bull_advocate")),
        # dangling upstream / downstream
        lambda s: s["edges"].append(_edge("ghost", "risk_officer")),
        lambda s: s["edges"].append(_edge("bull_advocate", "ghost")),
        # self loop
        lambda s: s["edges"].append(_edge("bull_advocate", "bull_advocate")),
        # orphan
        lambda s: s["nodes"].append(
            _node("lonely_wolf", source_task_id=None, is_new=True)
        ),
        # blank duty / role
        lambda s: s["nodes"][0].update(duty="   "),
        lambda s: s["nodes"][0].update(role=""),
        # invalid timeout values
        lambda s: s["nodes"][0].update(timeout_seconds=0),
        lambda s: s["nodes"][0].update(timeout_seconds=-5),
        lambda s: s["nodes"][0].update(timeout_seconds=1801),
        lambda s: s["nodes"][0].update(timeout_seconds="300"),
        lambda s: s["nodes"][0].update(timeout_seconds=True),
        # invalid / duplicate node ids
        lambda s: s["nodes"].append(
            _node("../escape", source_task_id=None, is_new=True)
        ),
        lambda s: s["nodes"].append(_node("bull_advocate")),
        # missing target / question
        lambda s: s.update(target=""),
        lambda s: s.update(question="  "),
    ],
)
def test_invalid_specs_raise(mutate):
    spec = _ic_spec()
    mutate(spec)
    with pytest.raises(ValueError):
        build_run_from_custom_spec(PRESET, spec)


def test_single_node_graph_is_valid():
    spec = {
        "target": "AAPL",
        "question": "值得买入吗",
        "nodes": [_node("portfolio_manager")],
        "edges": [],
    }
    run = build_run_from_custom_spec(PRESET, spec)
    assert len(run.tasks) == 1
    assert run.tasks[0].status.value == "pending"
    assert "{upstream_context}" not in run.agents[0].system_prompt


def test_empty_nodes_rejected():
    with pytest.raises(ValueError):
        build_run_from_custom_spec(
            PRESET, {"target": "AAPL", "question": "q", "nodes": [], "edges": []}
        )


def test_duplicate_edges_are_deduped():
    spec = _ic_spec(
        edges=[
            _edge("bull_advocate", "risk_officer"),
            _edge("bull_advocate", "risk_officer"),
            _edge("bear_advocate", "risk_officer"),
            _edge("risk_officer", "portfolio_manager"),
        ]
    )
    run = build_run_from_custom_spec(PRESET, spec)
    risk_task = _task_for(run, "risk_officer")
    assert len(risk_task.depends_on) == 2
    assert len(risk_task.input_from) == 2


def test_unknown_preset_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        build_run_from_custom_spec("no_such_preset", _ic_spec())
