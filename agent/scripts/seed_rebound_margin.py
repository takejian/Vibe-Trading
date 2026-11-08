#!/usr/bin/env python3
"""One-off seed: import the scraped maintenance-margin-ratio attachment
(MDATES / MVALS JS arrays from the astock-monitor page) into MySQL.

Usage:
    python -m scripts.seed_rebound_margin <path-to-担保比例.txt>

Rows are keyed by STATISTICS_DATE and inserted with INSERT IGNORE, so the
script is idempotent: re-running never overwrites existing rows. Only
AVG_GUARANTEE_RATIO is populated; remaining Eastmoney columns stay NULL and
are filled later by the Eastmoney backfill / daily sync.
"""

from __future__ import annotations

import ast
import re
import sys
from datetime import date
from pathlib import Path

# Allow running both as module and as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.super_rebound import db  # noqa: E402

_ARRAY_RE = re.compile(r"=\s*(\[[^\]]*\])")


def _parse_arrays(text: str) -> tuple[list[str], list[float]]:
    arrays = []
    for match in _ARRAY_RE.finditer(text):
        arrays.append(ast.literal_eval(match.group(1)))
    if len(arrays) < 2:
        raise ValueError("expected at least two JS-style arrays (MDATES, MVALS)")
    dates, values = arrays[0], arrays[1]
    if len(dates) != len(values):
        raise ValueError(f"length mismatch: {len(dates)} dates vs {len(values)} values")
    return dates, values


def seed(file_path: str) -> dict[str, int]:
    text = Path(file_path).read_text(encoding="utf-8")
    dates, values = _parse_arrays(text)

    inserted = 0
    skipped = 0
    with db.rebound_connection() as conn:
        db.initialize_schema(conn)
        for d_str, ratio in zip(dates, values):
            trade_date = date.fromisoformat(d_str)
            if db.upsert_margin_ratio_only(conn, trade_date, float(ratio)):
                inserted += 1
            else:
                skipped += 1

    return {"total": len(dates), "inserted": inserted, "skipped": skipped}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    stats = seed(sys.argv[1])
    print(
        f"seed complete: {stats['total']} rows parsed, "
        f"{stats['inserted']} inserted, {stats['skipped']} already existed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
