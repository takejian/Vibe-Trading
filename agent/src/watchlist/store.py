"""File-backed personal watchlist store.

Membership lives in ``<runtime_root>/watchlist/watchlist.json`` (one JSON
document, atomically replaced on every write). Quote snapshots are cached on
the entry for list rendering but the authoritative raw data stays in the
DuckDB warehouse.

Unfollowing a symbol only removes its membership row: analysis history
(swarm runs) and archived DuckDB data are never touched here.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from pydantic import ValidationError

from src.config.paths import get_watchlist_dir
from src.watchlist.models import A_SHARE_SYMBOL_RE, QuoteSnapshot, WatchEntry

_STORE_FILENAME = "watchlist.json"
_STORE_VERSION = 1

logger = logging.getLogger(__name__)


class WatchlistError(ValueError):
    """Base class for watchlist store errors (maps to HTTP 400)."""


class DuplicateWatchError(WatchlistError):
    """Raised when a symbol already on the watchlist is added again."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_symbol(symbol: str) -> str:
    """Validate and normalize an engineering-form A-share symbol."""
    normalized = (symbol or "").strip().upper()
    if not A_SHARE_SYMBOL_RE.match(normalized):
        raise WatchlistError(f"标的代码不合法（仅支持 A 股，如 600519.SH）: {symbol!r}")
    return normalized


class WatchlistStore:
    """JSON-document CRUD for the personal watchlist."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self._dir = base_dir if base_dir is not None else get_watchlist_dir()
        self._path = os.path.join(self._dir, _STORE_FILENAME)

    # ------------------------------------------------------------------
    def _write(self, entries: list[WatchEntry]) -> None:
        os.makedirs(self._dir, exist_ok=True)
        payload = {
            "version": _STORE_VERSION,
            "entries": [entry.model_dump() for entry in entries],
        }
        fd, tmp_name = tempfile.mkstemp(
            prefix=".watchlist-", suffix=".json", dir=self._dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _read_all(self) -> list[WatchEntry]:
        if not os.path.isfile(self._path):
            return []
        try:
            with open(self._path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            # Corrupt document must not break the whole page; surface an
            # empty list rather than half-parsed rows. Log loudly because
            # the next write would otherwise silently replace the file.
            logger.warning("watchlist store unreadable, degrading to empty: %s (%s)", self._path, exc)
            return []
        raw_entries = payload.get("entries", []) if isinstance(payload, dict) else []
        entries: list[WatchEntry] = []
        for row in raw_entries if isinstance(raw_entries, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                entries.append(WatchEntry.model_validate(row))
            except ValidationError:
                # Skip corrupt rows but keep the rest usable.
                logger.warning("skipping unparsable watchlist row in %s", self._path)
                continue
        return entries

    # ------------------------------------------------------------------
    def list_entries(self) -> list[WatchEntry]:
        """All watched symbols, newest add first."""
        entries = self._read_all()
        entries.sort(key=lambda entry: entry.added_at, reverse=True)
        return entries

    def get_entry(self, symbol: str) -> WatchEntry:
        symbol = validate_symbol(symbol)
        for entry in self._read_all():
            if entry.symbol == symbol:
                return entry
        raise FileNotFoundError(f"标的不在关注列表中: {symbol}")

    def contains(self, symbol: str) -> bool:
        try:
            self.get_entry(symbol)
        except (FileNotFoundError, WatchlistError):
            return False
        return True

    def add_entry(
        self,
        symbol: str,
        *,
        name: str = "",
        industry: str | None = None,
    ) -> WatchEntry:
        """Add one symbol; raises :class:`DuplicateWatchError` on repeats."""
        symbol = validate_symbol(symbol)
        entries = self._read_all()
        if any(entry.symbol == symbol for entry in entries):
            raise DuplicateWatchError("该标的已在关注列表中")
        now = _utc_now()
        entry = WatchEntry(
            symbol=symbol,
            name=(name or "").strip(),
            industry=(industry or "").strip() or None,
            added_at=now,
            updated_at=now,
        )
        entries.append(entry)
        self._write(entries)
        return entry

    def remove_entry(self, symbol: str) -> bool:
        """Remove membership only. Returns False when the symbol was absent."""
        symbol = validate_symbol(symbol)
        entries = self._read_all()
        remaining = [entry for entry in entries if entry.symbol != symbol]
        if len(remaining) == len(entries):
            return False
        self._write(remaining)
        return True

    def update_quote(self, symbol: str, quote: QuoteSnapshot) -> WatchEntry:
        """Cache the latest quote snapshot on one entry."""
        symbol = validate_symbol(symbol)
        entries = self._read_all()
        for idx, entry in enumerate(entries):
            if entry.symbol == symbol:
                updated = entry.model_copy(
                    update={
                        "quote": quote,
                        "updated_at": _utc_now(),
                        # Industry from the live quote fills the static field.
                        "industry": quote.industry or entry.industry,
                    }
                )
                entries[idx] = updated
                self._write(entries)
                return updated
        raise FileNotFoundError(f"标的不在关注列表中: {symbol}")

    def apply_quote_snapshots(
        self,
        snapshots: dict[str, QuoteSnapshot],
        stamped_at: str | None = None,
    ) -> list[WatchEntry]:
        """Merge many quote snapshots into the store in ONE read/write.

        Used by the list endpoint: per-row writes would rewrite the whole
        document N times and race with concurrent updates. Symbols absent
        from ``snapshots`` are returned unchanged; unknown snapshot symbols
        are ignored. Returns the full entry list (newest add first).
        """
        if not snapshots:
            return self.list_entries()
        stamp = stamped_at or _utc_now()
        entries = self._read_all()
        changed = False
        for idx, entry in enumerate(entries):
            quote = snapshots.get(entry.symbol)
            if quote is None:
                continue
            quote.quote_updated_at = stamp
            entries[idx] = entry.model_copy(
                update={
                    "quote": quote,
                    "updated_at": stamp,
                    # Industry from the live quote fills the static field.
                    "industry": quote.industry or entry.industry,
                }
            )
            changed = True
        if changed:
            self._write(entries)
        entries.sort(key=lambda entry: entry.added_at, reverse=True)
        return entries

    def update_meta(
        self,
        symbol: str,
        *,
        name: str | None = None,
        industry: str | None = None,
    ) -> WatchEntry:
        """Update static display metadata (name/industry) on one entry."""
        symbol = validate_symbol(symbol)
        entries = self._read_all()
        for idx, entry in enumerate(entries):
            if entry.symbol != symbol:
                continue
            updated = entry.model_copy(
                update={
                    "name": (name or entry.name or "").strip(),
                    "industry": (industry or entry.industry or None),
                    "updated_at": _utc_now(),
                }
            )
            entries[idx] = updated
            self._write(entries)
            return updated
        raise FileNotFoundError(f"标的不在关注列表中: {symbol}")
