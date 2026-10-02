"""Tests for watchlist analysis orchestration (fake runtime/store, tmp DB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from src.watchlist import analysis as svc
from src.watchlist import db as watch_db
from src.watchlist.models import QuoteSnapshot  # noqa: F401  (ensures models import)
from src.watchlist.store import WatchlistStore

CHANLUN_REF = "technical_analysis_panel:chanlun_analyst"
CLASSIC_TA_REF = "technical_analysis_panel:classic_ta_analyst"
FETCH_REF = "equity_research_team:stock_picker"

ENTRIES = [
    {"ref": CHANLUN_REF, "name": "Chanlun (Chan Theory) Analyst",
     "purpose": "Chan theory", "approved": True},
    {"ref": CLASSIC_TA_REF, "name": "Classic Technical Analyst",
     "purpose": "MACD", "approved": True},
    {"ref": FETCH_REF, "name": "Stock Analyst",
     "purpose": "equity research", "approved": True},
    {"ref": "macro_rates_fx_desk:macro_analyst", "name": "Macro Analyst",
     "purpose": "rates", "approved": True},
]


@dataclass
class FakeRun:
    id: str
    trial_role: str | None = None
    research_target: str = ""
    research_question: str = ""
    status: str = "pending"
    kind: str = "role_run"
    final_report: str = ""
    created_at: str = "2026-09-01T10:00:00+00:00"
    completed_at: str | None = None
    tasks: list = field(default_factory=list)


class FakeStore:
    def __init__(self) -> None:
        self.runs: list[FakeRun] = []
        self.seq = 0

    def list_runs(self, limit: int = 50):
        return list(self.runs)

    def reconcile_run(self, run, *, write: bool = True):
        return run


class FakeRuntime:
    def __init__(self) -> None:
        self._store = FakeStore()
        self.start_calls: list[dict] = []

    def start_run(self, preset_name, user_vars, role_run=None, **kwargs):
        self.start_calls.append(role_run)
        self.seq = getattr(self, "seq", 0) + 1
        run = FakeRun(
            id=f"run-{self.seq}",
            trial_role=role_run["role_ref"],
            research_target=role_run["target"],
            research_question=role_run["question"],
            status="pending",
        )
        self._store.runs.append(run)
        return run


@pytest.fixture()
def watch_store(tmp_path: Path) -> WatchlistStore:
    store = WatchlistStore(base_dir=tmp_path / "watchlist")
    store.add_entry("600519.SH", name="贵州茅台", industry="白酒")
    return store


# ----------------------------------------------------------------------
# TR-5.1 default questions
# ----------------------------------------------------------------------
def test_symbol_matching_uses_word_boundaries() -> None:
    """N6: an embedded digit must not cross-match another symbol."""
    assert svc._symbol_matches(
        FakeRun("r1", research_target="贵州茅台（600519.SH）"), "600519.SH"
    )
    # Digits glued onto the engineering symbol must NOT match.
    assert not svc._symbol_matches(
        FakeRun("r2", research_target="1600519.SH5 误写"), "600519.SH"
    )


def test_default_question_templates_and_brief() -> None:
    q = svc.default_question("technical", "600519.SH", "贵州茅台")
    assert "贵州茅台" in q and "600519.SH" in q and "技术面" in q

    qb = svc.default_question(
        "fundamental", "600519.SH", "贵州茅台", "重点看自由现金流"
    )
    assert qb.startswith("标的：贵州茅台（600519.SH）")
    assert "重点看自由现金流" in qb
    # Category template must NOT swallow the user's own request.
    assert "行业格局与竞争优势" not in qb

    qg = svc.default_question("general", "000001.SZ")
    assert "000001.SZ" in qg and "综合分析" in qg


# ----------------------------------------------------------------------
# TR-5.2 / TR-5.3 start_analysis
# ----------------------------------------------------------------------
def test_start_analysis_success(watch_store: WatchlistStore) -> None:
    runtime = FakeRuntime()
    run = svc.start_analysis(
        symbol="600519.SH",
        category="technical",
        role_ref=CHANLUN_REF,
        entries=ENTRIES,
        runtime=runtime,
        watch_store=watch_store,
    )
    assert run.id == "run-1"
    payload = runtime.start_calls[0]
    assert payload["role_ref"] == CHANLUN_REF
    assert payload["target"] == "贵州茅台（600519.SH）"
    assert "600519.SH" in payload["question"]


def test_start_analysis_validation_errors(
    watch_store: WatchlistStore,
) -> None:
    runtime = FakeRuntime()
    with pytest.raises(ValueError):  # unknown/unapproved role
        svc.start_analysis(
            symbol="600519.SH", category="technical", role_ref="nope:role",
            entries=ENTRIES, runtime=runtime, watch_store=watch_store,
        )
    with pytest.raises(ValueError):  # category mismatch
        svc.start_analysis(
            symbol="600519.SH", category="fundamental", role_ref=CHANLUN_REF,
            entries=ENTRIES, runtime=runtime, watch_store=watch_store,
        )
    with pytest.raises(FileNotFoundError):  # not watched
        svc.start_analysis(
            symbol="000001.SZ", category="technical", role_ref=CHANLUN_REF,
            entries=ENTRIES, runtime=runtime, watch_store=watch_store,
        )
    assert runtime.start_calls == []


def test_start_analysis_rejects_concurrent_run(
    watch_store: WatchlistStore,
) -> None:
    runtime = FakeRuntime()
    first = svc.start_analysis(
        symbol="600519.SH", category="technical", role_ref=CHANLUN_REF,
        entries=ENTRIES, runtime=runtime, watch_store=watch_store,
    )
    assert first.status == "pending"
    with pytest.raises(svc.AnalysisInProgress):
        svc.start_analysis(
            symbol="600519.SH", category="technical", role_ref=CHANLUN_REF,
            entries=ENTRIES, runtime=runtime, watch_store=watch_store,
        )
    # The rejected request must not create another run.
    assert len(runtime._store.runs) == 1

    # A different role on the same symbol is allowed.
    other = svc.start_analysis(
        symbol="600519.SH", category="technical", role_ref=CLASSIC_TA_REF,
        entries=ENTRIES, runtime=runtime, watch_store=watch_store,
    )
    assert other.id == "run-2"


# ----------------------------------------------------------------------
# Objective fetch
# ----------------------------------------------------------------------
def test_start_objective_fetch(watch_store: WatchlistStore) -> None:
    runtime = FakeRuntime()
    run = svc.start_objective_fetch(
        symbol="600519.SH", note="抓取近三年分红率", entries=ENTRIES,
        runtime=runtime, watch_store=watch_store,
    )
    payload = runtime.start_calls[0]
    assert payload["role_ref"] == FETCH_REF
    assert payload["target"] == "600519.SH"
    assert "分红率" in payload["question"]
    assert run.id == "run-1"

    with pytest.raises(ValueError):
        svc.start_objective_fetch(
            symbol="600519.SH", note="  ", entries=ENTRIES,
            runtime=runtime, watch_store=watch_store,
        )
    with pytest.raises(svc.AnalysisInProgress):
        svc.start_objective_fetch(
            symbol="600519.SH", note="再抓一次", entries=ENTRIES,
            runtime=runtime, watch_store=watch_store,
        )


def test_start_objective_fetch_missing_role(watch_store: WatchlistStore) -> None:
    runtime = FakeRuntime()
    with pytest.raises(svc.AnalysisServiceError):
        svc.start_objective_fetch(
            symbol="600519.SH", note="x", entries=ENTRIES[:2],
            runtime=runtime, watch_store=watch_store,
        )


# ----------------------------------------------------------------------
# TR-5.4 history
# ----------------------------------------------------------------------
def _seed_history(store: FakeStore) -> None:
    store.runs = [
        FakeRun("a1", CHANLUN_REF, "贵州茅台（600519.SH）", "q1",
                status="completed", completed_at="2026-09-10T11:00:00+00:00",
                created_at="2026-09-10T10:00:00+00:00",
                final_report="缠论结论"),
        FakeRun("a2", CLASSIC_TA_REF, "600519.SH", "q2",
                status="completed", completed_at="2026-09-09T11:00:00+00:00",
                created_at="2026-09-09T10:00:00+00:00",
                final_report="均线结论"),
        FakeRun("a3", CHANLUN_REF, "平安银行（000001.SZ）", "q3",
                status="completed", created_at="2026-09-08T10:00:00+00:00"),
        FakeRun("t1", None, "team run", status="completed", kind="team",
                created_at="2026-09-07T10:00:00+00:00"),
    ]


def test_list_analyses_filters_symbol_category_role_date() -> None:
    runtime = FakeRuntime()
    _seed_history(runtime._store)

    all_runs = svc.list_analyses(
        symbol="600519.SH", entries=ENTRIES, runtime=runtime, limit=50
    )
    assert [r["id"] for r in all_runs] == ["a1", "a2"]  # desc, symbol only
    assert all(r["category"] == "technical" for r in all_runs)
    assert all_runs[0]["is_chanlun"] is True
    assert all_runs[0]["qualified"] is True

    only_chanlun = svc.list_analyses(
        symbol="600519.SH", entries=ENTRIES, runtime=runtime,
        role_ref=CHANLUN_REF,
    )
    assert [r["id"] for r in only_chanlun] == ["a1"]

    dated = svc.list_analyses(
        symbol="600519.SH", entries=ENTRIES, runtime=runtime,
        date_from=date(2026, 9, 10), date_to=date(2026, 9, 10),
    )
    assert [r["id"] for r in dated] == ["a1"]


# ----------------------------------------------------------------------
# TR-5.6 persistence
# ----------------------------------------------------------------------
_STRUCTURED_REPORT = "\n".join(
    [
        "**1. Structure read 结构读取**", "s1",
        "**2. Active pivots 活跃支点**", "s2",
        "**3. Divergence 背驰**", "s3",
        "**4. Buy/sell points 买卖点**", "s4",
        "**5. Multi-level plan 多级别计划**", "s5",
        "**6. Elliott corroboration 艾略特验证**", "s6",
        "**7. Chanlun score 缠论打分**",
        "Score: +3", "Confidence: 78%",
    ]
)


@pytest.fixture()
def db_conn(tmp_path: Path):
    connection = watch_db.watchlist_connection(tmp_path / "m.duckdb")
    watch_db.initialize_schema(connection)
    yield connection
    connection.close()


def test_persist_chanlun_and_objective_idempotent(db_conn) -> None:
    chanlun_run = FakeRun(
        "c1", CHANLUN_REF, "贵州茅台（600519.SH）", "q",
        status="completed", final_report=_STRUCTURED_REPORT,
        created_at="2026-09-10T10:00:00+00:00",
        completed_at="2026-09-10T11:00:00+00:00",
    )
    fetch_run = FakeRun(
        "f1", FETCH_REF, "600519.SH", "抓取分红",
        status="completed", final_report="客观数据正文",
        created_at="2026-09-11T10:00:00+00:00",
        completed_at="2026-09-11T11:00:00+00:00",
    )
    counts = svc.persist_run_artifacts(
        [chanlun_run, fetch_run], entries=ENTRIES, connection=db_conn
    )
    assert counts == {"chanlun": 1, "objective": 1, "unstructured": 0}

    rows = watch_db.list_chanlun_records("600519.SH", db_conn)
    assert len(rows) == 1
    assert rows[0]["structured"] is True
    assert rows[0]["score"] == 3
    assert rows[0]["confidence"] == 0.78
    assert rows[0]["dim1_structure_read"] == "s1"

    objectives = watch_db.list_objective_records("600519.SH", db_conn)
    assert len(objectives) == 1
    assert objectives[0]["payload"] == "客观数据正文"
    assert objectives[0]["run_id"] == "f1"

    # Second pass archives nothing new.
    counts_again = svc.persist_run_artifacts(
        [chanlun_run, fetch_run], entries=ENTRIES, connection=db_conn
    )
    assert counts_again == {"chanlun": 0, "objective": 0, "unstructured": 0}
    assert len(watch_db.list_chanlun_records("600519.SH", db_conn)) == 1


def test_persist_unstructured_report_raw_row(db_conn) -> None:
    bad_run = FakeRun(
        "c2", CHANLUN_REF, "600519.SH", "q",
        status="completed", final_report="抱歉，数据缺失无法给出七段结论。",
        created_at="2026-09-12T10:00:00+00:00",
        completed_at="2026-09-12T11:00:00+00:00",
    )
    counts = svc.persist_run_artifacts(
        [bad_run], entries=ENTRIES, connection=db_conn
    )
    assert counts["unstructured"] == 1 and counts["chanlun"] == 0
    rows = watch_db.list_chanlun_records("600519.SH", db_conn)
    assert rows[0]["structured"] is False
    assert rows[0]["score"] is None
    assert rows[0]["raw_report"] == "抱歉，数据缺失无法给出七段结论。"


def test_persist_ignores_unfinished_and_other_roles(db_conn) -> None:
    running = FakeRun(
        "c3", CHANLUN_REF, "600519.SH", "q", status="running",
        final_report="partial", created_at="2026-09-12T10:00:00+00:00",
    )
    other = FakeRun(
        "m1", "macro_rates_fx_desk:macro_analyst", "600519.SH", "q",
        status="completed", final_report="macro note",
        created_at="2026-09-12T10:00:00+00:00",
        completed_at="2026-09-12T11:00:00+00:00",
    )
    counts = svc.persist_run_artifacts(
        [running, other], entries=ENTRIES, connection=db_conn
    )
    assert counts == {"chanlun": 0, "objective": 0, "unstructured": 0}
    assert watch_db.list_chanlun_records("600519.SH", db_conn) == []
    assert watch_db.list_objective_records("600519.SH", db_conn) == []
