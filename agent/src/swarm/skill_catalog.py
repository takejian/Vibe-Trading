"""Read-only catalog of assembled skills for the Skill Square / canvas.

Combines :class:`src.agent.skills.SkillsLoader` (bundled + user-installed
skill packages) with the global :class:`SkillApprovalStore`. Also hosts the
finance-relevance lexicon shared by package import/sync validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.agent.skills import SkillsLoader
from src.swarm.skill_approvals import SkillApprovalStore

if TYPE_CHECKING:
    from src.swarm.custom_skills import CustomSkillStore

#: Keywords (English + Chinese) used as the heuristic finance-relevance gate
#: for imported/synced packages. Matched against name, description, category
#: and body text case-insensitively.
FINANCE_KEYWORDS: tuple[str, ...] = (
    "finance", "financial", "stock", "stocks", "equity", "equities", "market",
    "trading", "trade", "invest", "investment", "portfolio", "security",
    "securities", "bond", "bonds", "futures", "option", "options", "derivative",
    "derivatives", "forex", "fx", "currency", "currencies", "crypto",
    "bitcoin", "ethereum", "token", "commodity", "commodities", "gold",
    "oil", "macro", "economic", "economy", "inflation", "interest rate",
    "yield", "dividend", "earnings", "valuation", "fundamental", "technical",
    "quant", "quantitative", "factor", "backtest", "alpha", "beta", "sharpe",
    "volatility", "liquidity", "hedge", "arbitrage", "spread", "bull",
    "bear", "long position", "short position", "a-share", "ashare",
    "hang seng", "kospi", "nifty", "tick", "ohlcv", "kline", "candlestick",
    "ichimoku", "elliott", "chanlun", "moving average", "rsi", "macd",
    "bollinger", "finance data", "ticker", "exchange", "nasdaq", "nyse",
    "s&p", "index future", "金融", "股票", "股市", "证券", "基金", "债券",
    "期货", "期权", "衍生品", "外汇", "货币", "加密", "比特币", "商品",
    "黄金", "原油", "宏观", "经济", "通胀", "利率", "收益", "股息",
    "财报", "估值", "基本面", "技术面", "量化", "因子", "回测", "波动",
    "流动性", "对冲", "套利", "价差", "做多", "做空", "多头", "空头",
    "A股", "港股", "美股", "行情", "指数", "交易所", "缠论", "波浪",
    "蜡烛", "均线", "K线",
)


def is_finance_related(
    name: str,
    description: str = "",
    category: str = "",
    body: str = "",
    metadata: dict | None = None,
) -> bool:
    """Heuristic gate: a package is finance-related when its metadata/body
    names a finance keyword or its frontmatter explicitly sets ``finance: true``.
    """
    if isinstance(metadata, dict):
        flag = metadata.get("finance")
        if flag is True or (isinstance(flag, str) and flag.strip().lower() == "true"):
            return True
    haystack = " ".join((name or "", description or "", category or "", body or "")).lower()
    return any(keyword.lower() in haystack for keyword in FINANCE_KEYWORDS)


def list_assembled_skills(
    loader: SkillsLoader | None = None,
    approvals: SkillApprovalStore | None = None,
    custom_store: "CustomSkillStore | None" = None,
) -> list[dict]:
    """Return all assembled skills with approval state.

    Each item: ``{name, description, category, source, kind, ref,
    approved, derived_from}``.

    * assembled packages (bundled directories or operator-installed user
      packages) use ``kind`` ``"bundled"``/``"user"``, ref
      ``"assembled:<name>"`` and take approval from the global registry;
    * materialized personal skills (``custom-<id>`` directories backed by
      a :class:`CustomSkillStore` record) use ``kind="custom"``, ref =
      record id and take approval from their record.
    """
    from src.swarm.custom_skills import (
        ASSEMBLED_TEMPLATE_PREFIX,
        CustomSkillStore,
    )

    loader = loader or SkillsLoader()
    approvals = approvals or SkillApprovalStore()
    custom_store = custom_store or CustomSkillStore()
    approved = approvals.approved_names()
    custom_by_id = {skill.id: skill for skill in custom_store.list_skills()}
    user_dir = Path(loader._user_skills_dir) if loader._user_skills_dir else None
    items: list[dict] = []
    for skill in loader.skills:
        source = "bundled"
        custom_record = None
        try:
            if skill.dir_path is not None and user_dir is not None:
                resolved_dir = skill.dir_path.resolve()
                resolved_dir.relative_to(user_dir.resolve())
                source = "user"
                dir_name = resolved_dir.name
                if dir_name.startswith("custom-"):
                    custom_record = custom_by_id.get(
                        dir_name[len("custom-"):]
                    )
        except (ValueError, OSError):
            source = "bundled"

        if custom_record is not None:
            items.append(
                {
                    "name": custom_record.name,
                    "description": custom_record.purpose,
                    "category": "custom",
                    "source": "user",
                    "kind": "custom",
                    "ref": custom_record.id,
                    "approved": custom_record.approved,
                    "derived_from": custom_record.derived_from,
                }
            )
        else:
            items.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "category": skill.category,
                    "source": source,
                    "kind": source,
                    "ref": f"{ASSEMBLED_TEMPLATE_PREFIX}{skill.name}",
                    "approved": skill.name in approved,
                    "derived_from": None,
                }
            )
    items.sort(key=lambda item: (item["source"], item["category"], item["name"]))
    return items


def list_approved_skill_names(
    loader: SkillsLoader | None = None,
    approvals: SkillApprovalStore | None = None,
    custom_store: "CustomSkillStore | None" = None,
) -> list[str]:
    """Names of assembled skills that are also approved (the 'add' catalog).

    Combines the global package-approval registry with manually approved
    personal custom skills.
    """
    return [
        item["name"]
        for item in list_assembled_skills(
            loader=loader, approvals=approvals, custom_store=custom_store
        )
        if item["approved"]
    ]


def assembled_skill_names(loader: SkillsLoader | None = None) -> set[str]:
    """All currently assembled skill names (regardless of approval)."""
    loader = loader or SkillsLoader()
    return {skill.name for skill in loader.skills}


def resolve_skill(
    ref: str,
    loader: SkillsLoader | None = None,
    approvals: SkillApprovalStore | None = None,
    custom_store: "CustomSkillStore | None" = None,
) -> dict:
    """Return the uniform full profile behind any skill-square reference.

    Assembled references look like ``"assembled:<name>"``; custom
    references are the custom skill id. Raises :class:`ValueError` on
    malformed/unknown references and :class:`FileNotFoundError` when a
    custom record was deleted.
    """
    from src.swarm.custom_skills import (
        ASSEMBLED_TEMPLATE_PREFIX,
        CustomSkillStore,
        is_custom_skill_id,
    )

    ref = (ref or "").strip()
    if not ref:
        raise ValueError("技能引用不能为空")
    loader = loader or SkillsLoader()
    approvals = approvals or SkillApprovalStore()

    if ref.startswith(ASSEMBLED_TEMPLATE_PREFIX):
        name = ref[len(ASSEMBLED_TEMPLATE_PREFIX):].strip()
        skill = next((item for item in loader.skills if item.name == name), None)
        if skill is None:
            raise ValueError(f"技能不存在或未装配: {name!r}")
        return {
            "kind": "assembled",
            "ref": ref,
            "name": skill.name,
            "purpose": skill.description,
            "methodology": skill.body,
            "inputs": "",
            "outputs": "",
            "category": skill.category,
            "approved": approvals.is_approved(skill.name),
            "derived_from": None,
        }

    if not is_custom_skill_id(ref):
        raise ValueError(f"技能引用不合法: {ref!r}")
    custom_store = custom_store or CustomSkillStore()
    record = custom_store.get_skill(ref)  # may raise FileNotFoundError
    return {
        "kind": "custom",
        "ref": record.id,
        "name": record.name,
        "purpose": record.purpose,
        "methodology": record.methodology,
        "inputs": record.inputs,
        "outputs": record.outputs,
        "category": "custom",
        "approved": record.approved,
        "derived_from": record.derived_from,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def is_custom_skill_name(
    skill_name: str, custom_store: "CustomSkillStore | None" = None
) -> bool:
    """Whether an assembled skill name belongs to a personal custom skill."""
    from src.swarm.custom_skills import CustomSkillStore

    custom_store = custom_store or CustomSkillStore()
    return custom_store.get_by_name(skill_name) is not None
