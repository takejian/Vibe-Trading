"""Read-only catalog of assembled skills for the Skill Square / canvas.

Combines :class:`src.agent.skills.SkillsLoader` (bundled + user-installed
skill packages) with the global :class:`SkillApprovalStore`. Also hosts the
finance-relevance lexicon shared by package import/sync validation.
"""

from __future__ import annotations

from src.agent.skills import SkillsLoader
from src.swarm.skill_approvals import SkillApprovalStore

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
) -> list[dict]:
    """Return all assembled skills with approval state.

    Each item: ``{name, description, category, source, approved}`` where
    source is ``"bundled"`` or ``"user"``.
    """
    loader = loader or SkillsLoader()
    approvals = approvals or SkillApprovalStore()
    approved = approvals.approved_names()
    user_dir = loader._user_skills_dir
    items: list[dict] = []
    for skill in loader.skills:
        source = "bundled"
        try:
            if skill.dir_path is not None and user_dir is not None:
                skill.dir_path.resolve().relative_to(user_dir.resolve())
                source = "user"
        except (ValueError, OSError):
            source = "bundled"
        items.append(
            {
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "source": source,
                "approved": skill.name in approved,
            }
        )
    items.sort(key=lambda item: (item["source"], item["category"], item["name"]))
    return items


def list_approved_skill_names(
    loader: SkillsLoader | None = None,
    approvals: SkillApprovalStore | None = None,
) -> list[str]:
    """Names of assembled skills that are also approved (the 'add' catalog)."""
    return [
        item["name"]
        for item in list_assembled_skills(loader=loader, approvals=approvals)
        if item["approved"]
    ]


def assembled_skill_names(loader: SkillsLoader | None = None) -> set[str]:
    """All currently assembled skill names (regardless of approval)."""
    loader = loader or SkillsLoader()
    return {skill.name for skill in loader.skills}
