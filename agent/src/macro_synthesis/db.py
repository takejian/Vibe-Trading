"""宏观量化汇总的 DuckDB 持久化。

与本地行情仓库共用 ``market.duckdb``，便于后续 claim 复盘与实际宏观/行情
数据同库 JOIN。连接短开短用，写操作在单连接事务内完成。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

import duckdb

from src.config.paths import get_market_db_path

from .models import (
    ASSET_KEYS,
    CYCLE_KEYS,
    DimensionSignal,
    SynthesisClaim,
    SynthesisReport,
    SynthesisReview,
    TeamCoverage,
)

_DDL = """
CREATE SEQUENCE IF NOT EXISTS seq_macro_syn_report START 1;
CREATE SEQUENCE IF NOT EXISTS seq_macro_syn_claim START 1;
CREATE SEQUENCE IF NOT EXISTS seq_macro_syn_review START 1;

CREATE TABLE IF NOT EXISTS macro_synthesis_report (
    id BIGINT NOT NULL DEFAULT nextval('seq_macro_syn_report') PRIMARY KEY,
    economy VARCHAR NOT NULL,
    period_type VARCHAR NOT NULL,
    period VARCHAR NOT NULL,
    mcs DOUBLE NOT NULL,
    mcs_delta DOUBLE,
    cycle_probs VARCHAR NOT NULL,
    allocation VARCHAR NOT NULL,
    summary VARCHAR NOT NULL,
    action_advice VARCHAR NOT NULL,
    risk_triggers VARCHAR NOT NULL,
    coverage VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    claim_count INTEGER NOT NULL DEFAULT 0,
    create_time TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (economy, period_type, period)
);

CREATE TABLE IF NOT EXISTS macro_synthesis_dimension (
    report_id BIGINT NOT NULL,
    dimension VARCHAR NOT NULL,
    signal INTEGER NOT NULL,
    confidence DOUBLE NOT NULL,
    trend VARCHAR NOT NULL,
    weight DOUBLE NOT NULL,
    source_run_ids VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    PRIMARY KEY (report_id, dimension)
);

CREATE TABLE IF NOT EXISTS macro_synthesis_claim (
    id BIGINT NOT NULL DEFAULT nextval('seq_macro_syn_claim') PRIMARY KEY,
    report_id BIGINT NOT NULL,
    dimension VARCHAR NOT NULL,
    text VARCHAR NOT NULL,
    metric VARCHAR NOT NULL,
    direction VARCHAR NOT NULL,
    predicted_value VARCHAR NOT NULL,
    probability DOUBLE NOT NULL,
    window_start VARCHAR NOT NULL,
    window_end VARCHAR NOT NULL,
    verify_source VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    actual_value VARCHAR,
    verified_at VARCHAR,
    ai_comment VARCHAR
);

CREATE TABLE IF NOT EXISTS macro_synthesis_review (
    id BIGINT NOT NULL DEFAULT nextval('seq_macro_syn_review') PRIMARY KEY,
    report_id BIGINT NOT NULL,
    review_type VARCHAR NOT NULL,
    hit_rate DOUBLE,
    brier_score DOUBLE,
    counts VARCHAR,
    comment VARCHAR NOT NULL,
    attribution VARCHAR,
    lessons VARCHAR,
    reviewer VARCHAR,
    create_time TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


class SynthesisDBError(RuntimeError):
    """DuckDB 持久化失败，向服务层透出。"""


def synthesis_connection(
    db_path: str | os.PathLike[str] | None = None,
) -> duckdb.DuckDBPyConnection:
    """打开读写连接，自动创建父目录。"""
    path = str(db_path) if db_path is not None else str(get_market_db_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return duckdb.connect(path)


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """幂等建表（可反复执行）。"""
    for statement in _DDL.strip().split(";"):
        ddl = statement.strip()
        if ddl:
            conn.execute(ddl)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iso(value: object) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


class MacroSynthesisRepository:
    """宏观汇总报告仓储。"""

    def __init__(
        self,
        conn: Optional[duckdb.DuckDBPyConnection] = None,
        db_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._owns_conn = conn is None
        self._conn = conn or synthesis_connection(db_path)
        initialize_schema(self._conn)

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    def __enter__(self) -> "MacroSynthesisRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- 读 ---------------------------------------------------------------

    def _hydrate(
        self,
        row: tuple,
        dimensions: list[DimensionSignal],
        claims: list[SynthesisClaim],
        reviews: list[SynthesisReview],
    ) -> SynthesisReport:
        coverage_payload = json.loads(row[11])
        teams = [TeamCoverage(**item) for item in coverage_payload.get("teams", [])]
        return SynthesisReport(
            id=row[0],
            economy=row[1],
            period_type=row[2],
            period=row[3],
            period_label="",
            mcs=row[4],
            mcs_delta=row[5],
            cycle_probs=json.loads(row[6]),
            allocation=json.loads(row[7]),
            summary=row[8],
            action_advice=row[9],
            risk_triggers=json.loads(row[10]),
            teams=teams,
            dimensions=dimensions,
            claims=claims,
            reviews=reviews,
            status=row[12],
            create_time=_iso(row[14]),
        )

    def _load_dimensions(self, report_id: int) -> list[DimensionSignal]:
        rows = self._conn.execute(
            "SELECT dimension, signal, confidence, trend, weight, source_run_ids, rationale "
            "FROM macro_synthesis_dimension WHERE report_id = ? ORDER BY dimension",
            [report_id],
        ).fetchall()
        return [
            DimensionSignal(
                dimension=r[0],
                signal=r[1],
                confidence=r[2],
                trend=r[3],
                weight=r[4],
                source_run_ids=json.loads(r[5]),
                rationale=r[6],
            )
            for r in rows
        ]

    def _load_claims(self, report_id: int) -> list[SynthesisClaim]:
        rows = self._conn.execute(
            "SELECT id, report_id, dimension, text, metric, direction, predicted_value, "
            "probability, window_start, window_end, verify_source, status, actual_value, "
            "verified_at, ai_comment FROM macro_synthesis_claim WHERE report_id = ? ORDER BY id",
            [report_id],
        ).fetchall()
        return [
            SynthesisClaim(
                id=r[0],
                report_id=r[1],
                dimension=r[2],
                text=r[3],
                metric=r[4],
                direction=r[5],
                predicted_value=r[6],
                probability=r[7],
                window_start=r[8],
                window_end=r[9],
                verify_source=r[10],
                status=r[11],
                actual_value=r[12],
                verified_at=r[13],
                ai_comment=r[14],
            )
            for r in rows
        ]

    def _load_reviews(self, report_id: int) -> list[SynthesisReview]:
        rows = self._conn.execute(
            "SELECT id, report_id, review_type, hit_rate, brier_score, counts, comment, "
            "attribution, lessons, reviewer, create_time "
            "FROM macro_synthesis_review WHERE report_id = ? ORDER BY id",
            [report_id],
        ).fetchall()
        return [
            SynthesisReview(
                id=r[0],
                report_id=r[1],
                review_type=r[2],
                hit_rate=r[3],
                brier_score=r[4],
                counts=json.loads(r[5]) if r[5] else None,
                comment=r[6],
                attribution=r[7],
                lessons=r[8],
                reviewer=r[9],
                create_time=_iso(r[10]),
            )
            for r in rows
        ]

    def _row_to_report(self, row: tuple) -> SynthesisReport:
        report = self._hydrate(
            row,
            self._load_dimensions(row[0]),
            self._load_claims(row[0]),
            self._load_reviews(row[0]),
        )
        from dataclasses import replace as _replace
        from .periods import period_label

        return _replace(
            report, period_label=period_label(report.period_type, report.period)
        )

    def get_report(
        self, economy: str, period_type: str, period: str
    ) -> Optional[SynthesisReport]:
        rows = self._conn.execute(
            "SELECT * FROM macro_synthesis_report "
            "WHERE economy = ? AND period_type = ? AND period = ?",
            [economy, period_type, period],
        ).fetchall()
        return self._row_to_report(rows[0]) if rows else None

    def get_report_by_id(self, report_id: int) -> Optional[SynthesisReport]:
        rows = self._conn.execute(
            "SELECT * FROM macro_synthesis_report WHERE id = ?", [report_id]
        ).fetchall()
        return self._row_to_report(rows[0]) if rows else None

    def list_reports(self, economy: str, limit: int = 50) -> list[SynthesisReport]:
        rows = self._conn.execute(
            "SELECT * FROM macro_synthesis_report WHERE economy = ? "
            "ORDER BY create_time DESC LIMIT ?",
            [economy, limit],
        ).fetchall()
        return [self._row_to_report(row) for row in rows]

    def previous_report(self, economy: str, before_id: int) -> Optional[SynthesisReport]:
        """取早于指定报告的最近一期（用于 MCS 环比）。"""
        rows = self._conn.execute(
            "SELECT * FROM macro_synthesis_report WHERE economy = ? AND id < ? "
            "ORDER BY create_time DESC LIMIT 1",
            [economy, before_id],
        ).fetchall()
        return self._row_to_report(rows[0]) if rows else None

    # -- 写 ---------------------------------------------------------------

    def insert_report(self, report: SynthesisReport) -> SynthesisReport:
        """事务性写入报告、维度信号与命题，回填自增 id。"""
        coverage_payload = {
            "all_covered": report.all_covered,
            "teams": [team.to_dict() for team in report.teams],
        }
        conn = self._conn
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT INTO macro_synthesis_report "
                "(economy, period_type, period, mcs, mcs_delta, cycle_probs, allocation, "
                "summary, action_advice, risk_triggers, coverage, status, claim_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    report.economy,
                    report.period_type,
                    report.period,
                    report.mcs,
                    report.mcs_delta,
                    _dumps({key: report.cycle_probs[key] for key in CYCLE_KEYS}),
                    _dumps({key: report.allocation[key] for key in ASSET_KEYS}),
                    report.summary,
                    report.action_advice,
                    _dumps(list(report.risk_triggers)),
                    _dumps(coverage_payload),
                    report.status,
                    report.claim_count,
                ],
            )
            report_id = int(conn.execute(
                "SELECT currval('seq_macro_syn_report')"
            ).fetchone()[0])

            for dim in report.dimensions:
                conn.execute(
                    "INSERT INTO macro_synthesis_dimension "
                    "(report_id, dimension, signal, confidence, trend, weight, "
                    "source_run_ids, rationale) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        report_id,
                        dim.dimension,
                        dim.signal,
                        dim.confidence,
                        dim.trend,
                        dim.weight,
                        _dumps(list(dim.source_run_ids)),
                        dim.rationale,
                    ],
                )

            for claim in report.claims:
                conn.execute(
                    "INSERT INTO macro_synthesis_claim "
                    "(report_id, dimension, text, metric, direction, predicted_value, "
                    "probability, window_start, window_end, verify_source, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        report_id,
                        claim.dimension,
                        claim.text,
                        claim.metric,
                        claim.direction,
                        claim.predicted_value,
                        claim.probability,
                        claim.window_start,
                        claim.window_end,
                        claim.verify_source,
                        claim.status,
                    ],
                )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise SynthesisDBError(f"汇总报告写入失败：{exc}") from exc

        stored = self.get_report_by_id(report_id)
        return stored if stored is not None else report

    # -- Claims 判定 / Review 写入 ----------------------------------------

    def update_claim_verification(
        self,
        claim_id: int,
        status: str,
        actual_value: Optional[float],
        observed_date: Optional[str],
    ) -> None:
        """更新一条命题的判定结果。"""
        self._conn.execute(
            "UPDATE macro_synthesis_claim "
            "SET status = ?, actual_value = ?, verified_at = COALESCE(?, verified_at) "
            "WHERE id = ?",
            [
                status,
                None if actual_value is None else str(actual_value),
                observed_date,
                claim_id,
            ],
        )

    def insert_review(self, review: SynthesisReview) -> SynthesisReview:
        """写入一条复盘点评并回填 id。"""
        conn = self._conn
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT INTO macro_synthesis_review "
                "(report_id, review_type, hit_rate, brier_score, counts, comment, "
                "attribution, lessons, reviewer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    review.report_id,
                    review.review_type,
                    review.hit_rate,
                    review.brier_score,
                    _dumps(review.counts) if review.counts else None,
                    review.comment,
                    review.attribution,
                    review.lessons,
                    review.reviewer,
                ],
            )
            review_id = int(
                conn.execute("SELECT currval('seq_macro_syn_review')").fetchone()[0]
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise SynthesisDBError(f"复盘点评写入失败：{exc}") from exc
        from dataclasses import replace as _replace

        return _replace(review, id=review_id)

