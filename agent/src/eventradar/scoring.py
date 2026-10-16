"""Source tiers, verification state machine and paradigm scoring.

Pure functions over plain dicts so the whole gate pipeline is unit-testable
without network or an LLM. The defaults mirror the PRD rules:

* a single source can never reach ``confirmed``;
* confirmation needs >= N independent sources, at least one T1/T2, and a
  confidence above the configured threshold;
* ``new_paradigm`` requires four explicit sub-scores and a total threshold.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Event taxonomy
# ---------------------------------------------------------------------------

EVENT_TYPES: tuple[str, ...] = (
    "geopolitical",       # 地缘冲突
    "monetary_fiscal",    # 货币财政政策
    "trade",              # 贸易关税
    "public_health",      # 疫情公共卫生
    "climate_disaster",   # 气候灾害
    "technology",         # 技术突破
    "regulation",         # 产业监管
    "politics",           # 大选政治
    "financial_credit",   # 金融信用事件
    "commodity_supply",   # 大宗商品供给冲击
)

#: Chinese/English keyword matrix, used both by the no-LLM fallback
#: extractor and as a safety net for unclassified LLM output.
TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "geopolitical": ("战争", "冲突", "军事", "袭击", "导弹", "制裁", "入侵", "地缘",
                     "war", "conflict", "military", "strike", "missile", "invasion",
                     "sanction", "geopolitical"),
    "monetary_fiscal": ("央行", "降息", "加息", "降准", "货币政策", "财政", "国债",
                        "利率", "fed", "rate cut", "rate hike", "central bank",
                        "monetary", "fiscal", "treasury"),
    "trade": ("关税", "贸易", "出口管制", "脱钩", "tariff", "trade war", "export control",
              "import duty", "trade barrier"),
    "public_health": ("疫情", "病毒", "感染", "封锁", "世卫", "大流行", "pandemic",
                      "virus", "outbreak", "lockdown", "who ", "epidemic", "cases"),
    "climate_disaster": ("厄尔尼诺", "拉尼娜", "台风", "洪水", "干旱", "地震", "极端天气",
                         "el nino", "el niño", "la nina", "typhoon", "flood", "drought",
                         "earthquake", "hurricane", "wildfire"),
    "technology": ("突破", "发布", "芯片", "人工智能", "ai", "大模型", "量子", "机器人",
                   "breakthrough", "unveil", "chip", "semiconductor", "artificial intelligence",
                   "large model", "quantum", "robot", "launch"),
    "regulation": ("监管", "反垄断", "处罚", "禁令", "调查", "新规", "regulate", "antitrust",
                   "ban", "probe", "crackdown", "fine", "compliance"),
    "politics": ("大选", "选举", "总统", "国会", "政府停摆", "election", "president vote",
                 "parliament", "government shutdown", "campaign"),
    "financial_credit": ("违约", "爆雷", "破产", "债务危机", "银行", "挤兑", "信用",
                         "default", "bankruptcy", "debt crisis", "bank run", "credit event",
                         "contagion"),
    "commodity_supply": ("减产", "停产", "供给", "原油", "天然气", "粮食", "opec", "断供",
                         "supply cut", "output cut", "shutdown", "crude", "natural gas",
                         "grain", "supply disruption"),
}

NOVELTY_CLASSES = ("known_continuation", "known_escalation", "new_paradigm")

# ---------------------------------------------------------------------------
# Source credibility tiers
# ---------------------------------------------------------------------------

# T1 primary sources, T2 wires/authoritative media, T3 general finance media,
# T4 aggregators/self-media. Matched as lowercase substrings of host/name.
_SOURCE_PATTERNS: dict[int, tuple[str, ...]] = {
    1: ("gov.cn", "mof.gov", "pbc.gov", "csrc.gov", "mofcom.gov", "miit.gov",
        "whitehouse.gov", "treasury.gov", "federalreserve.gov", "sec.gov", "fdic.gov",
        "who.int", "wto.org", "imf.org", "worldbank.org", "nasa.gov", "noaa.gov",
        "ec.europa.eu", "ecb.europa.eu", "bankofengland", "boj.or.jp", "mof.go.jp",
        "hkex.hk", "sse.com.cn", "szse.cn", "cngold", "xinhuanet.com/politics",
        "reuters.com/world", "cpc.people"),
    2: ("xinhuanet.com", "news.cn", "people.com.cn", "cctv.com", "chinanews.com",
        "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "apnews.com", "afp.com",
        "cnbc.com", "economist.com", "nytimes.com", "bbc.com", "caixin.com",
        "yicai.com", "stcn.com", "cnstock.com", "cls.cn",
        "wallstreetcn.com", "wallstcn.com", "awtmt.com", "gov"),
    3: ("eastmoney.com", "sina.com", "finance.sina", "10jqka.com.cn", "163.com",
        "sohu.com", "qq.com", "ifeng.com", "21jingji.com", "thepaper.cn",
        "marketwatch.com", "barrons.com", "investing.com", "yahoo.com", "forbes.com",
        "businessinsider.com", "ftchinese.com"),
}
DEFAULT_TIER = 4

#: Hosts that merely republish the same wire copy do not count as independent.
_REPOST_MARKERS = ("转载", "转自", "来源：", "via reuters", "via bloomberg",
                   "source: reuters", "source: bloomberg")


def source_tier(source_name: str | None, url: str | None) -> int:
    blob = f"{source_name or ''} {url or ''}".lower()
    for tier in (1, 2, 3):
        if any(pattern in blob for pattern in _SOURCE_PATTERNS[tier]):
            return tier
    return DEFAULT_TIER


def is_repost(snippet: str | None, title: str | None) -> bool:
    blob = f"{title or ''} {snippet or ''}".lower()
    return any(marker in blob for marker in _REPOST_MARKERS)


# ---------------------------------------------------------------------------
# Verification state machine
# ---------------------------------------------------------------------------

STATUS_UNVERIFIED = "unverified"
STATUS_VERIFYING = "verifying"
STATUS_CONFIRMED = "confirmed"
STATUS_DISPUTED = "disputed"
STATUS_RUMOR = "rumor"
STATUS_DISMISSED = "dismissed"

ALL_STATUSES = (
    STATUS_UNVERIFIED, STATUS_VERIFYING, STATUS_CONFIRMED,
    STATUS_DISPUTED, STATUS_RUMOR, STATUS_DISMISSED,
)

#: Statuses from which automatic scans may never move an event without human
#: action or T1/T2 refutation evidence.
HUMAN_LOCKED_STATUSES = (STATUS_CONFIRMED, STATUS_RUMOR, STATUS_DISMISSED)

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_UNVERIFIED: {STATUS_VERIFYING, STATUS_CONFIRMED, STATUS_DISPUTED,
                        STATUS_RUMOR, STATUS_DISMISSED},
    STATUS_VERIFYING: {STATUS_CONFIRMED, STATUS_DISPUTED, STATUS_RUMOR,
                       STATUS_DISMISSED, STATUS_UNVERIFIED},
    STATUS_DISPUTED: {STATUS_CONFIRMED, STATUS_RUMOR, STATUS_DISMISSED,
                      STATUS_VERIFYING},
    STATUS_RUMOR: {STATUS_DISMISSED, STATUS_VERIFYING},
    STATUS_CONFIRMED: {STATUS_DISPUTED, STATUS_RUMOR, STATUS_DISMISSED},
    STATUS_DISMISSED: set(),
}

#: Human review actions mapped to resulting status.
HUMAN_ACTIONS: dict[str, str] = {
    "confirm": STATUS_CONFIRMED,
    "flag_dispute": STATUS_DISPUTED,
    "mark_rumor": STATUS_RUMOR,
    "dismiss": STATUS_DISMISSED,
}


def can_transition(current: str, target: str) -> bool:
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def confidence_score(
    *,
    best_tier: int,
    independent_sources: int,
    fact_consistency: float,
) -> float:
    """Composite confidence: source tier 0.4 + count 0.25 + consistency 0.35."""
    tier_score = {1: 1.0, 2: 0.8, 3: 0.5, 4: 0.25}.get(best_tier, 0.25)
    count_score = min(1.0, independent_sources / 3.0)
    consistency = max(0.0, min(1.0, fact_consistency))
    return round(0.4 * tier_score + 0.25 * count_score + 0.35 * consistency, 3)


def derive_status(
    *,
    best_tier: int,
    independent_sources: int,
    fact_consistency: float,
    confidence: float,
    min_sources: int,
    confirm_threshold: float,
) -> str:
    """Hard gate: no single-source event is ever auto-confirmed."""
    if (
        independent_sources >= max(2, min_sources)
        and best_tier <= 2
        and fact_consistency >= 0.6
        and confidence >= confirm_threshold
    ):
        return STATUS_CONFIRMED
    if independent_sources >= 1:
        return STATUS_VERIFYING
    return STATUS_UNVERIFIED


# ---------------------------------------------------------------------------
# Novelty / paradigm scoring
# ---------------------------------------------------------------------------

PARADIGM_DIMENSIONS = (
    "policy_duration",    # 政策持续性
    "invest_cycle",       # 投资周期长度
    "chain_breadth",      # 产业链波及宽度
    "narrative_heat",     # 叙事热度增速
)

LONG_TERM_THEMES: dict[str, tuple[str, ...]] = {
    "AI 与算力": ("ai", "人工智能", "大模型", "算力", "芯片", "artificial intelligence",
                  "chip", "semiconductor", "gpu", "data center"),
    "能源转型": ("新能源", "光伏", "储能", "电动车", "碳中和", "renewable", "solar",
                 "battery", "ev ", "energy transition", "carbon"),
    "军工安全": ("军工", "国防", "军费", "defense", "military spending", "arms"),
    "供应链重构": ("供应链", "产能转移", "近岸外包", "supply chain", "reshoring",
                   "nearshoring", "manufacturing shift"),
    "人口与消费": ("人口", "老龄化", "生育", "消费", "demographic", "aging",
                   "fertility", "consumption"),
    "国产替代": ("国产替代", "自主可控", "国产化", "domestic substitution",
                 "self-reliance", "localization"),
    "气候与农业": ("厄尔尼诺", "粮食", "农业", "气候", "el nino", "el niño",
                   "agriculture", "grain", "fishing", "drought"),
    "货币体系": ("去美元化", "人民币国际化", "黄金", "美债", "dedollarization",
                 "rmb internationalization", "gold", "sovereign debt"),
}


def map_themes(text: str) -> list[str]:
    blob = (text or "").lower()
    return [theme for theme, keywords in LONG_TERM_THEMES.items()
            if any(keyword in blob for keyword in keywords)]


def validate_paradigm(
    novelty_class: str,
    scores: dict[str, Any] | None,
    *,
    threshold: int,
) -> tuple[str, int | None, dict[str, int] | None]:
    """Enforce the new-paradigm contract structurally.

    Returns the (possibly downgraded) novelty class, total, normalized scores.
    Anything missing a dimension or below threshold becomes
    ``known_escalation`` rather than ``new_paradigm``.
    """
    if novelty_class != "new_paradigm":
        return novelty_class, None, None
    normalized: dict[str, int] = {}
    for dim in PARADIGM_DIMENSIONS:
        try:
            value = int((scores or {}).get(dim))
        except (TypeError, ValueError):
            return "known_escalation", None, None
        if not 1 <= value <= 5:
            return "known_escalation", None, None
        normalized[dim] = value
    total = sum(normalized.values())
    if total < threshold:
        return "known_escalation", total, normalized
    return "new_paradigm", total, normalized


def impact_level_from_type(event_type: str, novelty: str) -> str:
    """Default impact rating; LLM may override via affected-asset detail."""
    if novelty == "new_paradigm":
        return "high"
    high_types = {"geopolitical", "financial_credit", "monetary_fiscal",
                  "commodity_supply", "public_health"}
    if event_type in high_types:
        return "high"
    if event_type in {"trade", "climate_disaster", "regulation", "technology"}:
        return "medium"
    return "low"


def guess_event_type(text: str) -> str:
    """Keyword fallback for event classification (no-LLM path)."""
    blob = (text or "").lower()
    best_type = "politics"
    best_hits = 0
    for event_type, keywords in TYPE_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in blob)
        if hits > best_hits:
            best_hits = hits
            best_type = event_type
    return best_type if best_hits > 0 else "politics"


def extract_entities_heuristic(title: str, event_type: str | None = None) -> list[str]:
    """Very conservative entity guess for the no-LLM path.

    Pulls quoted names, well-known proper-noun keywords, and the matched
    taxonomy keyword (e.g. 厄尔尼诺/OPEC) so the server-side cluster key is
    stable across reworded reposts. Chinese NER is intentionally avoided
    (no jieba dependency).
    """
    entities: list[str] = []
    for match in re.findall(r"[《\"“']([^》\"”']{2,20})[》\"”']", title or ""):
        entities.append(match)
    known = ("美联储", "央行", "欧盟", "美国", "中国", "俄罗斯", "乌克兰", "以色列",
             "伊朗", "日本", "OPEC", "WHO", "世卫组织", "英伟达", "台积电", "特朗普")
    for name in known:
        if name in (title or "") and name not in entities:
            entities.append(name)
    # The taxonomy keyword that fired classification is the strongest
    # no-dictionary anchor for clustering (厄尔尼诺, 关税, OPEC ...).
    for type_key, keywords in TYPE_KEYWORDS.items():
        if event_type is not None and type_key != event_type:
            continue
        for keyword in keywords:
            if len(keyword) >= 3 and keyword.lower() in (title or "").lower() \
                    and keyword not in entities:
                entities.append(keyword)
                break
    return entities[:5]
