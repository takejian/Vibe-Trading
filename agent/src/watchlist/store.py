"""File-backed personal watchlist store.

Membership lives in ``<runtime_root>/watchlist/watchlist.json`` (one JSON
document, atomically replaced on every write). Quote snapshots are cached on
the entry for list rendering but the authoritative raw data stays in the
DuckDB warehouse.

Store format (version 2)::

    {
      "version": 2,
      "groups": [
        {"id": "default", "name": "自选", "system": true},
        {"id": "canceled", "name": "取消", "system": true},
        {"id": "midterm", "name": "中长期", "system": false}
      ],
      "entries": [
        {
          "symbol": "600519.SH",
          "name": "贵州茅台",
          "group_id": "midterm",
          "added_at": "...",
          "updated_at": "...",
          "quote": {...}
        }
      ]
    }

Unfollowing a symbol moves it into the ``canceled`` group rather than removing
it. Only a hard "delete from canceled" actually drops the membership row.
Analysis history (swarm runs) and archived DuckDB data are never touched here.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from src.config.paths import get_watchlist_dir
from src.watchlist.models import (
    A_SHARE_SYMBOL_RE,
    CANCELED_GROUP_ID,
    DEFAULT_GROUP_ID,
    SYSTEM_GROUP_IDS,
    SYSTEM_GROUP_NAMES,
    QuoteSnapshot,
    WatchEntry,
    WatchGroup,
)

_STORE_FILENAME = "watchlist.json"
_STORE_VERSION = 2

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class WatchlistError(ValueError):
    """Base class for watchlist store errors (maps to HTTP 400)."""


class DuplicateWatchError(WatchlistError):
    """Raised when a symbol already on the watchlist is added again."""


class DuplicateGroupError(WatchlistError):
    """Raised when a group name already exists."""


class SystemGroupError(WatchlistError):
    """Raised when trying to rename or delete a system-reserved group."""


class GroupNotFoundError(WatchlistError):
    """Raised when a target group id does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_group_id() -> str:
    return f"g_{uuid.uuid4().hex[:12]}"


def _build_default_groups() -> list[WatchGroup]:
    """Always-available system groups; the store ensures these exist."""
    return [
        WatchGroup(id=DEFAULT_GROUP_ID, name=SYSTEM_GROUP_NAMES[DEFAULT_GROUP_ID], system=True),
        WatchGroup(id=CANCELED_GROUP_ID, name=SYSTEM_GROUP_NAMES[CANCELED_GROUP_ID], system=True),
    ]


def validate_symbol(symbol: str) -> str:
    """Validate and normalize an engineering-form A-share symbol."""
    normalized = (symbol or "").strip().upper()
    if not A_SHARE_SYMBOL_RE.match(normalized):
        raise WatchlistError(f"标的代码不合法（仅支持 A 股，如 600519.SH）: {symbol!r}")
    return normalized


def _normalize_group_name(name: str) -> str:
    stripped = (name or "").strip()
    if not stripped:
        raise WatchlistError("分组名称不能为空")
    if len(stripped) > 30:
        raise WatchlistError("分组名称不能超过 30 个字符")
    return stripped


class WatchlistStore:
    """JSON-document CRUD for the personal watchlist, now with groups."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self._dir = base_dir if base_dir is not None else get_watchlist_dir()
        self._path = os.path.join(self._dir, _STORE_FILENAME)

    # ------------------------------------------------------------------
    # Low-level persistence
    # ------------------------------------------------------------------
    def _write(
        self,
        groups: list[WatchGroup],
        entries: list[WatchEntry],
    ) -> None:
        os.makedirs(self._dir, exist_ok=True)
        payload = {
            "version": _STORE_VERSION,
            "groups": [g.model_dump() for g in groups],
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

    def _read_all(self) -> tuple[list[WatchGroup], list[WatchEntry]]:
        """Read and auto-migrate the document to the current version."""
        default_groups = _build_default_groups()

        if not os.path.isfile(self._path):
            return default_groups, []

        try:
            with open(self._path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "watchlist store unreadable, degrading to empty: %s (%s)",
                self._path, exc,
            )
            return default_groups, []

        if not isinstance(payload, dict):
            return default_groups, []

        raw_groups = payload.get("groups") if isinstance(payload.get("groups"), list) else None
        raw_entries = payload.get("entries") if isinstance(payload.get("entries"), list) else None

        # ---- groups --------------------------------------------------
        if raw_groups is None:
            # v1 or corrupt — start with system groups only.
            groups: list[WatchGroup] = list(default_groups)
        else:
            groups = []
            for row in raw_groups:
                if not isinstance(row, dict):
                    continue
                try:
                    groups.append(WatchGroup.model_validate(row))
                except ValidationError:
                    logger.warning("skipping unparsable group row in %s", self._path)
            # Ensure the two system groups exist — backfill if an older v2
            # document somehow lacked them.
            present_ids = {g.id for g in groups}
            for sg in default_groups:
                if sg.id not in present_ids:
                    groups.append(sg)

        # ---- entries -------------------------------------------------
        entries: list[WatchEntry] = []
        valid_group_ids = {g.id for g in groups}
        for row in raw_entries or []:
            if not isinstance(row, dict):
                continue
            try:
                entry = WatchEntry.model_validate(row)
            except ValidationError:
                logger.warning("skipping unparsable watchlist row in %s", self._path)
                continue
            # v1 documents have no group_id — default to "自选".
            if entry.group_id not in valid_group_ids:
                entry.group_id = DEFAULT_GROUP_ID
            entries.append(entry)

        return groups, entries

    # ------------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------------
    def list_groups(self) -> list[WatchGroup]:
        groups, _ = self._read_all()
        # System groups first, then user-defined in insertion order.
        system = [g for g in groups if g.system]
        custom = [g for g in groups if not g.system]
        return system + custom

    def create_group(self, name: str) -> WatchGroup:
        """Add a custom group. Raises DuplicateGroupError on name conflict."""
        clean_name = _normalize_group_name(name)
        groups, entries = self._read_all()
        if any(g.name == clean_name for g in groups):
            raise DuplicateGroupError("分组名称已存在")
        group = WatchGroup(id=_new_group_id(), name=clean_name, system=False)
        groups.append(group)
        self._write(groups, entries)
        return group

    def rename_group(self, group_id: str, name: str) -> WatchGroup:
        """Rename a custom group. System groups are immutable."""
        clean_name = _normalize_group_name(name)
        groups, entries = self._read_all()
        target = next((g for g in groups if g.id == group_id), None)
        if target is None:
            raise GroupNotFoundError(f"分组不存在: {group_id}")
        if target.system:
            raise SystemGroupError("系统预置分组不可重命名")
        if any(g.name == clean_name and g.id != group_id for g in groups):
            raise DuplicateGroupError("分组名称已存在")
        target.name = clean_name
        self._write(groups, entries)
        return target

    def delete_group(self, group_id: str) -> int:
        """Delete a custom group; contained entries move to 'canceled'.

        Returns the number of entries that were relocated.
        Raises SystemGroupError for system groups.
        """
        groups, entries = self._read_all()
        target = next((g for g in groups if g.id == group_id), None)
        if target is None:
            raise GroupNotFoundError(f"分组不存在: {group_id}")
        if target.system:
            raise SystemGroupError("系统预置分组不可删除")

        relocated = 0
        canceled_exists = any(g.id == CANCELED_GROUP_ID for g in groups)
        for entry in entries:
            if entry.group_id == group_id:
                entry.group_id = CANCELED_GROUP_ID if canceled_exists else DEFAULT_GROUP_ID
                relocated += 1
        groups = [g for g in groups if g.id != group_id]
        self._write(groups, entries)
        return relocated

    # ------------------------------------------------------------------
    # Entry membership
    # ------------------------------------------------------------------
    def list_entries(
        self,
        group_id: str | None = None,
        *,
        exclude_group_ids: set[str] | None = None,
    ) -> list[WatchEntry]:
        """Return watched symbols, newest add first.

        - ``group_id``: only entries whose group matches (default: all entries).
        - ``exclude_group_ids``: entries whose group is one of these are filtered out.
        """
        _groups, entries = self._read_all()
        if group_id is not None:
            entries = [e for e in entries if e.group_id == group_id]
        if exclude_group_ids:
            entries = [e for e in entries if e.group_id not in exclude_group_ids]
        entries.sort(key=lambda entry: entry.added_at, reverse=True)
        return entries

    def get_entry(self, symbol: str) -> WatchEntry:
        symbol = validate_symbol(symbol)
        _groups, entries = self._read_all()
        for entry in entries:
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
        group_id: str = DEFAULT_GROUP_ID,
    ) -> WatchEntry:
        """Add one symbol to the watchlist.

        Raises DuplicateWatchError if the symbol already exists in any group.
        """
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        if not any(g.id == group_id for g in groups):
            raise GroupNotFoundError(f"目标分组不存在: {group_id}")
        if any(entry.symbol == symbol for entry in entries):
            raise DuplicateWatchError("该标的已在关注列表中")
        now = _utc_now()
        entry = WatchEntry(
            symbol=symbol,
            name=(name or "").strip(),
            industry=(industry or "").strip() or None,
            group_id=group_id,
            added_at=now,
            updated_at=now,
        )
        entries.append(entry)
        self._write(groups, entries)
        return entry

    def cancel_entry(self, symbol: str) -> WatchEntry:
        """Move an active entry into the 'canceled' group.

        This is the user-visible "取消关注" operation — the row is not
        deleted, just relocated. Returns the relocated entry.
        """
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        idx = next((i for i, e in enumerate(entries) if e.symbol == symbol), None)
        if idx is None:
            raise FileNotFoundError(f"标的不在关注列表中: {symbol}")
        if entries[idx].group_id == CANCELED_GROUP_ID:
            raise WatchlistError("该标的已在取消分组中")
        canceled_group = next(
            (g for g in groups if g.id == CANCELED_GROUP_ID), None
        )
        if canceled_group is None:
            raise GroupNotFoundError("取消分组不存在")
        moved = entries[idx].model_copy(
            update={"group_id": CANCELED_GROUP_ID, "updated_at": _utc_now()}
        )
        entries[idx] = moved
        self._write(groups, entries)
        return moved

    def remove_entry(self, symbol: str) -> bool:
        """Permanently delete membership (hard delete, e.g. from canceled group).

        This replaces the old "remove" — only callable after cancel_entry,
        or when the caller explicitly wants the row gone forever.
        Returns False when the symbol was absent.
        """
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        remaining = [e for e in entries if e.symbol != symbol]
        if len(remaining) == len(entries):
            return False
        self._write(groups, remaining)
        return True

    def restore_entry(self, symbol: str) -> WatchEntry:
        """Move a canceled entry back into the 'default' group (重新关注)."""
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        idx = next((i for i, e in enumerate(entries) if e.symbol == symbol), None)
        if idx is None:
            raise FileNotFoundError(f"标的不在关注列表中: {symbol}")
        if entries[idx].group_id != CANCELED_GROUP_ID:
            raise WatchlistError("该标的不在取消分组中")
        default_group = next(
            (g for g in groups if g.id == DEFAULT_GROUP_ID), None
        )
        if default_group is None:
            raise GroupNotFoundError("自选分组不存在")
        moved = entries[idx].model_copy(
            update={"group_id": DEFAULT_GROUP_ID, "updated_at": _utc_now()}
        )
        entries[idx] = moved
        self._write(groups, entries)
        return moved

    def move_entry(self, symbol: str, target_group_id: str) -> WatchEntry:
        """Relocate an entry between groups.

        Raises GroupNotFoundError if the target group doesn't exist,
        WatchlistError if the entry is in 'canceled' (cannot be moved out of
        that group — users must 重新关注 first), or if it's already in the
        target group.
        """
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        if target_group_id == CANCELED_GROUP_ID:
            # Use cancel_entry for that explicit semantics.
            raise WatchlistError("请使用'取消关注'操作将标的移入取消分组")
        if not any(g.id == target_group_id for g in groups):
            raise GroupNotFoundError(f"目标分组不存在: {target_group_id}")
        idx = next((i for i, e in enumerate(entries) if e.symbol == symbol), None)
        if idx is None:
            raise FileNotFoundError(f"标的不在关注列表中: {symbol}")
        entry = entries[idx]
        if entry.group_id == CANCELED_GROUP_ID:
            raise WatchlistError("取消分组中的标的不可移动到其他分组")
        if entry.group_id == target_group_id:
            raise WatchlistError("标的已在目标分组中")
        moved = entry.model_copy(
            update={"group_id": target_group_id, "updated_at": _utc_now()}
        )
        entries[idx] = moved
        self._write(groups, entries)
        return moved

    # ------------------------------------------------------------------
    # Quote / meta mutations (unchanged from v1)
    # ------------------------------------------------------------------
    def update_quote(self, symbol: str, quote: QuoteSnapshot) -> WatchEntry:
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
        for idx, entry in enumerate(entries):
            if entry.symbol == symbol:
                updated = entry.model_copy(
                    update={
                        "quote": quote,
                        "updated_at": _utc_now(),
                        "industry": quote.industry or entry.industry,
                    }
                )
                entries[idx] = updated
                self._write(groups, entries)
                return updated
        raise FileNotFoundError(f"标的不在关注列表中: {symbol}")

    def apply_quote_snapshots(
        self,
        snapshots: dict[str, QuoteSnapshot],
        stamped_at: str | None = None,
    ) -> list[WatchEntry]:
        if not snapshots:
            return self.list_entries()
        stamp = stamped_at or _utc_now()
        groups, entries = self._read_all()
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
                    "industry": quote.industry or entry.industry,
                }
            )
            changed = True
        if changed:
            self._write(groups, entries)
        entries.sort(key=lambda entry: entry.added_at, reverse=True)
        return entries

    def update_meta(
        self,
        symbol: str,
        *,
        name: str | None = None,
        industry: str | None = None,
    ) -> WatchEntry:
        symbol = validate_symbol(symbol)
        groups, entries = self._read_all()
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
            self._write(groups, entries)
            return updated
        raise FileNotFoundError(f"标的不在关注列表中: {symbol}")
