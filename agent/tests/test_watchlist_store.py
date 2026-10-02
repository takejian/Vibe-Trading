"""Unit tests for the personal watchlist JSON store and path helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.paths import get_market_db_path, get_watchlist_dir
from src.watchlist.models import QuoteSnapshot
from src.watchlist.store import (
    DuplicateWatchError,
    WatchlistStore,
    validate_symbol,
)


def _make_store(tmp_path: Path) -> WatchlistStore:
    return WatchlistStore(base_dir=tmp_path / "watchlist")


def test_add_list_remove_and_persistence(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.list_entries() == []

    entry = store.add_entry("600519.SH", name="贵州茅台", industry="白酒")
    assert entry.symbol == "600519.SH"
    assert store.contains("600519.sh")  # normalized to upper case

    again = WatchlistStore(base_dir=tmp_path / "watchlist")
    rows = again.list_entries()
    assert len(rows) == 1 and rows[0].name == "贵州茅台"

    assert store.remove_entry("600519.SH") is True
    assert store.list_entries() == []
    # Removing an absent symbol is an idempotent no-op.
    assert store.remove_entry("600519.SH") is False


def test_duplicate_add_rejected_without_doubling(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add_entry("000001.SZ", name="平安银行")
    with pytest.raises(DuplicateWatchError):
        store.add_entry("000001.sz")
    assert len(store.list_entries()) == 1


def test_invalid_symbol_rejected(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    for bad in ("", "60051", "AAPL.US", "600519.XX", "ABCDEF.SH"):
        with pytest.raises(ValueError):
            validate_symbol(bad)
        with pytest.raises(ValueError):
            store.add_entry(bad)
    with pytest.raises(FileNotFoundError):
        store.get_entry("600519.SH")


def test_update_quote_and_meta(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add_entry("300750.SZ", name="宁德时代")
    updated = store.update_quote(
        "300750.SZ",
        QuoteSnapshot(
            price=189.5,
            total_market_cap=8.3e11,
            pe=22.1,
            pb=4.2,
            industry="电池",
            quote_updated_at="2026-09-30T10:00:00+00:00",
        ),
    )
    assert updated.quote.price == 189.5
    assert updated.industry == "电池"

    meta = store.update_meta("300750.SZ", name="宁德时代股份")
    assert meta.name == "宁德时代股份"

    with pytest.raises(FileNotFoundError):
        store.update_quote("600519.SH", QuoteSnapshot(price=1.0))


def test_apply_quote_snapshots_single_write(tmp_path: Path, monkeypatch) -> None:
    """N2: list refresh merges all snapshots in ONE document write."""
    store = _make_store(tmp_path)
    store.add_entry("600519.SH", name="贵州茅台")
    store.add_entry("300750.SZ", name="宁德时代")

    writes = []
    original = store._write
    def counting(entries):
        writes.append(len(entries))
        return original(entries)
    monkeypatch.setattr(store, "_write", counting)

    result = store.apply_quote_snapshots(
        {
            "600519.SH": QuoteSnapshot(price=1258.62, industry="白酒Ⅱ"),
            "300750.SZ": QuoteSnapshot(price=189.5, industry="电池"),
        },
        stamped_at="2026-10-01T06:00:00+00:00",
    )
    assert writes == [2]  # exactly one write of the whole two-row document
    by_symbol = {e.symbol: e for e in result}
    assert by_symbol["600519.SH"].quote.price == 1258.62
    assert by_symbol["300750.SZ"].industry == "电池"


def test_update_meta_only_touches_the_matching_entry(tmp_path: Path) -> None:
    """Regression: meta refresh must never overwrite another row (B1)."""
    store = _make_store(tmp_path)
    store.add_entry("600519.SH", name="贵州茅台", industry="白酒")
    store.add_entry("300750.SZ", name="宁德时代", industry="电池")

    updated = store.update_meta("300750.SZ", name="宁德时代新", industry="动力电池")
    assert updated.symbol == "300750.SZ"
    assert updated.name == "宁德时代新"

    by_symbol = {e.symbol: e for e in store.list_entries()}
    assert by_symbol["600519.SH"].name == "贵州茅台"
    assert by_symbol["600519.SH"].industry == "白酒"
    assert by_symbol["300750.SZ"].industry == "动力电池"

    with pytest.raises(FileNotFoundError):
        store.update_meta("000001.SZ", name="不存在")


def test_corrupt_document_degrades_to_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store_dir = tmp_path / "watchlist"
    store_dir.mkdir(parents=True)
    (store_dir / "watchlist.json").write_text("{not json", encoding="utf-8")
    assert store.list_entries() == []


def test_write_is_atomic_single_document(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.add_entry("600519.SH", name="贵州茅台")
    store.add_entry("000001.SZ", name="平安银行")
    data = json.loads(
        (tmp_path / "watchlist" / "watchlist.json").read_text(encoding="utf-8")
    )
    assert data["version"] == 1
    assert {row["symbol"] for row in data["entries"]} == {
        "600519.SH",
        "000001.SZ",
    }
    # No temp files left behind after a successful write.
    leftovers = [
        p.name
        for p in (tmp_path / "watchlist").iterdir()
        if p.name.startswith(".watchlist-")
    ]
    assert leftovers == []


def test_path_helpers_honor_runtime_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom_root = tmp_path / "custom-home"
    monkeypatch.setenv("VIBE_TRADING_HOME", str(custom_root))
    assert get_watchlist_dir() == custom_root / "watchlist"
    assert get_market_db_path() == custom_root / "data" / "market.duckdb"
