"""Read-only catalog of assembled skills for the Skill Square / canvas.

Combines :class:`src.agent.skills.SkillsLoader` (bundled + user-installed
skill packages) with the global :class:`SkillApprovalStore`. Also hosts the
finance-relevance lexicon shared by package import/sync validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.agent.skills import SkillsLoader
from src.swarm.presets import list_presets, load_preset
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


# ---------------------------------------------------------------------------
# Financial research taxonomy (same desk language as agent/preset categories)
# ---------------------------------------------------------------------------

#: Category order for skill display; mirrors PRESET_CATEGORY_ORDER in
#: ``src/swarm/presets.py`` with one extra bucket, ``data_toolkit``, for
#: market-data adapters and general research tooling that is not itself an
#: analysis style.
SKILL_CATEGORY_ORDER: tuple[str, ...] = (
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
    "data_toolkit",
    "other",
)

#: Bundled skill name -> financial research category id. Every built-in
#: skill is classified once here; skills absent from the map fall back to
#: ``"other"``.
SKILL_CATEGORIES: dict[str, str] = {
    # Technical analysis
    "technical-basic": "technical",
    "candlestick": "technical",
    "chanlun": "technical",
    "elliott-wave": "technical",
    "harmonic": "technical",
    "ichimoku": "technical",
    "smc": "technical",
    "minute-analysis": "technical",
    "volatility": "technical",
    # Fundamental & equity research
    "fundamental-filter": "fundamental",
    "financial-statement": "fundamental",
    "valuation-model": "fundamental",
    "deep-company-series": "fundamental",
    "dividend-analysis": "fundamental",
    "management-deep-dive": "fundamental",
    "private-company-research": "fundamental",
    "earnings-forecast": "fundamental",
    "earnings-revision": "fundamental",
    "bottleneck-hunter": "fundamental",
    "investor-lenses": "fundamental",
    "thesis-tracker": "fundamental",
    "edgar-sec-filings": "fundamental",
    # Macro economy & strategy
    "macro-analysis": "macro",
    "global-macro": "macro",
    "geopolitical-risk": "macro",
    "sector-rotation": "macro",
    "behavioral-finance": "macro",
    "cross-market-strategy": "macro",
    # Quant research & arbitrage
    "factor-research": "quant",
    "quant-statistics": "quant",
    "multi-factor": "quant",
    "ml-strategy": "quant",
    "pair-trading": "quant",
    "alpha-zoo": "quant",
    "correlation-analysis": "quant",
    "correlation-regime": "quant",
    "adr-hshare": "quant",
    "seasonal": "quant",
    "market-microstructure": "quant",
    "execution-model": "quant",
    # Sentiment & alternative data
    "sentiment-analysis": "sentiment",
    "social-media-intelligence": "sentiment",
    "hk-connect-flow": "sentiment",
    "us-etf-flow": "sentiment",
    # Event-driven
    "event-driven": "event_driven",
    "corporate-events": "event_driven",
    # Asset allocation & portfolio management
    "asset-allocation": "allocation",
    "etf-analysis": "allocation",
    "fund-analysis": "allocation",
    "research-goal": "allocation",
    # Fixed income & derivatives
    "credit-analysis": "fixed_income_derivatives",
    "convertible-bond": "fixed_income_derivatives",
    "options-strategy": "fixed_income_derivatives",
    "options-payoff": "fixed_income_derivatives",
    "options-advanced": "fixed_income_derivatives",
    "hedging-strategy": "fixed_income_derivatives",
    # Alternative assets (digital assets & commodities)
    "commodity-analysis": "alternatives",
    "ccxt": "alternatives",
    "okx-market": "alternatives",
    "crypto-derivatives": "alternatives",
    "perp-funding-basis": "alternatives",
    "defi-yield": "alternatives",
    "onchain-analysis": "alternatives",
    "stablecoin-flow": "alternatives",
    "liquidation-heatmap": "alternatives",
    "token-unlock-treasury": "alternatives",
    # Risk management
    "risk-analysis": "risk",
    "ashare-pre-st-filter": "risk",
    "performance-attribution": "risk",
    "shadow-account": "risk",
    # Data sources & general toolkit
    "akshare": "data_toolkit",
    "eastmoney": "data_toolkit",
    "mootdx": "data_toolkit",
    "qveris": "data_toolkit",
    "sec-edgar": "data_toolkit",
    "tushare": "data_toolkit",
    "yfinance": "data_toolkit",
    "data-routing": "data_toolkit",
    "backtest-diagnose": "data_toolkit",
    "doc-reader": "data_toolkit",
    "pine-script": "data_toolkit",
    "regulatory-knowledge": "data_toolkit",
    "report-generate": "data_toolkit",
    "trade-journal": "data_toolkit",
    "vnpy-export": "data_toolkit",
    "web-reader": "data_toolkit",
    "research-discipline": "data_toolkit",
    "strategy-dev-manager": "data_toolkit",
    "strategy-discovery": "data_toolkit",
    "strategy-generate": "data_toolkit",
}


def skill_finance_category(name: str) -> str:
    """Return the financial research category id for a skill name.

    Unknown / user-authored skills fall back to ``"other"``.
    """
    return SKILL_CATEGORIES.get(name, "other")


def build_skill_usage_index() -> dict[str, list[dict]]:
    """Map every skill name to the roles (agents) that reference it.

    Both built-in preset agents (``skills:`` lists inside each preset YAML)
    and user custom roles are scanned. Each reference is
    ``{ref, name, source}`` where ``ref`` is the same role reference used by
    the Role Square (``"preset:agent"`` or custom role id), ``name`` is the
    human-readable role name and ``source`` is the containing preset/custom
    title. A skill used by no role simply maps to an empty list.
    """
    usage: dict[str, list[dict]] = {}

    def _record(skill_name: str, ref: str, name: str, source: str) -> None:
        references = usage.setdefault(skill_name, [])
        if not any(item["ref"] == ref for item in references):
            references.append({"ref": ref, "name": name, "source": source})

    for summary in list_presets():
        preset_name = summary["name"]
        try:
            data = load_preset(preset_name)
        except Exception:
            continue
        preset_title = str(data.get("title", "") or summary.get("title", ""))
        for agent in data.get("agents", []):
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("id", ""))
            role_name = str(agent.get("role", "") or agent_id)
            ref = f"{preset_name}:{agent_id}"
            for skill_name in agent.get("skills", []):
                if isinstance(skill_name, str) and skill_name.strip():
                    _record(skill_name.strip(), ref, role_name, preset_title)

    # User custom roles.
    from src.swarm.roles import RoleStore

    for role in RoleStore().list_roles():
        for skill_name in getattr(role, "skills", []) or []:
            _record(
                str(skill_name),
                role.id,
                role.name,
                "自建角色",
            )
    return usage


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

    Each item: ``{name, description, category, finance_category, source,
    kind, ref, approved, derived_from, used_by_count}``.

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
    # Build once: which roles reference each skill.
    usage_index = build_skill_usage_index()
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
                    "finance_category": skill_finance_category(custom_record.name),
                    "source": "user",
                    "kind": "custom",
                    "ref": custom_record.id,
                    "approved": custom_record.approved,
                    "derived_from": custom_record.derived_from,
                    "used_by_count": len(usage_index.get(custom_record.name, [])),
                }
            )
        else:
            items.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "category": skill.category,
                    "finance_category": skill_finance_category(skill.name),
                    "source": source,
                    "kind": source,
                    "ref": f"{ASSEMBLED_TEMPLATE_PREFIX}{skill.name}",
                    "approved": skill.name in approved,
                    "derived_from": None,
                    "used_by_count": len(usage_index.get(skill.name, [])),
                }
            )
    items.sort(
        key=lambda item: (
            SKILL_CATEGORY_ORDER.index(item["finance_category"])
            if item["finance_category"] in SKILL_CATEGORY_ORDER
            else len(SKILL_CATEGORY_ORDER),
            item["name"],
        )
    )
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
    usage_index = build_skill_usage_index()

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
            "finance_category": skill_finance_category(skill.name),
            "approved": approvals.is_approved(skill.name),
            "derived_from": None,
            "used_by": usage_index.get(skill.name, []),
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
        "finance_category": skill_finance_category(record.name),
        "approved": record.approved,
        "derived_from": record.derived_from,
        "used_by": usage_index.get(record.name, []),
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
