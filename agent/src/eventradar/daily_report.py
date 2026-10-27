"""Investment-news-collector daily report (SkillHub v2.7.2 适配版).

零 Token 财经科技资讯日报：复用事件雷达的双源采集（财联社深度 + 华尔街见闻），
经领域过滤 → 标题优先事件评分 → 话题聚类 → 正文规则摘要，生成 6 板块
Markdown 日报并存入 ``radar_daily_report`` 表。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

FETCH_TIMEOUT = 8
FETCH_DELAY = 0.3
MAX_SUMMARY_LEN = 500
MAX_FINAL = 20

# ---- 噪音正则 ----

LEAD_PREFIX_RE = re.compile(
    r"^(?:财联社|《科创板日报》|科创板日报)(?:\d{1,2}月)?\d{1,2}日讯"
    r"(?:\s*[（(](?:编辑|记者)[^）)]*[）)])?\s*[,，]?\s*"
)
TAIL_SIGN_RE = re.compile(
    r"\s*[（(][^（）()\n]*?(?:编辑|记者)\s+[\u4e00-\u9fa5]{2,6}\s*[）)]\s*$"
)
HEAD_SIGN_RE = re.compile(
    r"^\s*[（(][^（）()\n]{0,40}?(?:编辑|记者)\s+[\u4e00-\u9fa5]{2,6}\s*[）)]\s*"
)
LINE_DROP_RE = re.compile(
    r"^\s*(?:"
    r"作者\s*[|｜丨/]\s*\S{1,12}"
    r"|本文来源[:：]\s*\S{1,24}"
    r"|责任编辑[:：]\s*\S{1,12}"
    r"|来源[:：]\s*\S{1,24}"
    r")\s*$"
)
SOURCE_TAG_RE = re.compile(
    r"\s*[（(](?:"
    r"彭博|彭博社|路透|路透社|第一财经|一财|界面新闻|界面|每日经济新闻|每经|"
    r"证券时报|证券日报|上海证券报|上证报|中国证券报|中证报|中证金牛座|"
    r"21世纪经济报道|21财经|券商中国|经济观察报|经济参考报|"
    r"澎湃新闻|澎湃|新华财经|新华社|财联社|科创板日报|"
    r"新浪科技|央视新闻|央视财经|央广网|科技日报|新京报|贝壳财经|"
    r"参考消息|IPO早知道|36氪|硬AI|腾讯混元|CNBC|CNBC中文网"
    r")[）)]\s*$"
)
SOURCE_TAG_GENERIC_RE = re.compile(
    r"\s*[（(][\u4e00-\u9fa5A-Za-z0-9]{1,9}"
    r"(?:网|报|社|财经|科技|日报|晚报|时报|周刊|新闻|观察|氪)"
    r"[）)]\s*$"
)
DISCLAIMER_RE = re.compile(r"[\s；;]{0,4}风险提示及免责条款[\s\S]*$")
DISCLAIMER_INLINE_RE = re.compile(
    r"[\s；;]{0,4}市场有风险，投资需谨慎。[\s\S]{0,400}?据此投资，责任自负。?\s*$"
)

COLUMN_POST_KW = (
    "精选", "今夜看点", "研选", "早餐", "早报", "晚报", "复盘", "直播间", "快讯", "一览",
)
COLUMN_POST_FILTER_KW = (
    "今夜看点", "早报", "早餐FM", "公告精选", "盘后公告集锦", "速读公告", "机构调研",
)


def is_column_post(title: str) -> bool:
    return any(k in (title or "") for k in COLUMN_POST_KW)


def is_low_value_column_post(title: str) -> bool:
    return any(k in (title or "") for k in COLUMN_POST_FILTER_KW)


def strip_noise_affixes(text: str) -> str:
    if not text:
        return text
    out = DISCLAIMER_RE.sub("", text)
    out = DISCLAIMER_INLINE_RE.sub("", out)
    out = "\n".join(line for line in out.split("\n") if not LINE_DROP_RE.match(line))
    out = HEAD_SIGN_RE.sub("", out.lstrip())
    out = "\n".join(
        LEAD_PREFIX_RE.sub("", _l).lstrip("，,。、；; ") for _l in out.split("\n")
    )
    out = TAIL_SIGN_RE.sub("", out.rstrip()).strip()
    out = SOURCE_TAG_RE.sub("", out.rstrip()).strip()
    out = SOURCE_TAG_GENERIC_RE.sub("", out.rstrip()).strip()
    return out


# ---- 领域过滤 ----

CORE_TECH_KEYWORDS = [
    "ai", "人工智能", "大模型", "gpt", "claude", "llm", "chatgpt",
    "智能体", "ai agent", "copilot", "aigc", "生成式", "anthropic", "deepseek",
    "机器人", "具身智能", "人形机器人", "机械臂",
    "脑机接口", "可穿戴",
    "芯片", "半导体", "gpu", "cpu", "npu", "算力",
    "台积电", "tsmc", "中芯国际", "smic", "英伟达", "nvidia",
    "新能源", "电动车", "电动汽车", "动力电池", "固态电池", "储能", "光储",
    "光伏", "宁德时代", "catl",
    "特斯拉", "tesla", "蔚来", "nio", "小鹏", "xpeng", "比亚迪", "byd",
    "自动驾驶", "无人驾驶", "智驾",
    "锂电池", "负极", "正极", "电解液",
    "光模块", "cpo", "光通信", "中际旭创",
    "低空经济", "evtol", "飞行汽车",
    "spacex", "星舰", "商业航天", "卫星", "火箭",
    "核聚变", "聚变", "人造太阳",
    "存储", "内存", "闪存", "hbm", "dram", "nand",
    "科创板",
    "华为", "huawei", "阿里", "alibaba", "字节", "bytedance", "腾讯", "tencent",
    "百度", "baidu", "openai", "meta", "google", "谷歌", "微软", "microsoft",
    "苹果", "apple", "amazon", "亚马逊", "小米",
    "智谱", "zhipu", "月之暗面", "moonshot", "kimi", "千问", "通义", "文心",
    "量子计算", "量子通信",
]

# ---- 雷达模式宏观关键词（突发雷达 tab 允许通过领域过滤）----
# 与 CORE_TECH_KEYWORDS 合并作为雷达模式的白名单，确保宏观/政策/地缘
# 新闻能进入雷达评分器（日报模式仍只保留科技关键词命中）。
MACRO_KEYWORDS = [
    # 货币政策
    "央行", "降准", "降息", "加息", "货币政策", "利率", "lpr", "mlf", "逆回购",
    "流动性", "存款准备金", "再贷款", "再贴现", "公开市场", "美联储", "fed",
    "欧央行", "日央行", "英央行", "缩表", "扩表", "qe", "taper",
    # 财政
    "财政", "赤字", "国债", "地方债", "专项债", "特别国债", "转移支付",
    # 通胀/经济数据
    "cpi", "ppi", "pce", "通胀", "通缩", "gdp", "经济增长", "衰退", "萧条",
    "失业率", "非农", "制造业pmi", "pmi",
    # 汇率/国际收支
    "汇率", "人民币", "贬值", "升值", "外汇", "外储", "贸易逆差", "贸易顺差",
    "经常账户", "资本外流",
    # 地缘政治
    "地缘", "制裁", "脱钩", "禁运", "封锁", "战争", "冲突", "关税", "贸易战",
    "出口管制", "实体清单", "芯片法案", "反制裁", "中立", "结盟",
    # 系统性风险
    "系统性", "危机", "崩盘", "爆雷", "违约", "挤兑", "黑天鹅", "灰犀牛",
    "流动性危机", "债务危机", "金融危机", "银行危机",
    # 能源/大宗商品
    "原油", "石油", "天然气", "煤炭", "opec", "油价", "大宗商品", "铁矿石",
    "铜价", "黄金", "贵金属",
    # 房地产/制度变革
    "房地产", "楼市", "房价", "地产", "限购", "限贷", "棚改", "城中村",
    "土地出让", "房产税",
    # 债市
    "债市", "债券", "收益率", "信用债", "利率债", "地方政府债",
    # 监管/制度
    "监管", "新规", "试点", "立法", "修法", "反垄断", "数据安全", "数据主权",
    "平台治理", "金融监管", "证监会", "银保监会", "金融委",
    # 公共卫生
    "疫情", "公共卫生", "大流行", "传染病", "致死率",
]

EXCLUDE_PATTERNS = [
    r"\|速读公告", r"\|盘后公告集锦",
    r"退市风险警示.*触发", r"会计处理调整.*触发", r"可能被实施退市风险警示",
    r"世界杯|足球|球队|出线|小组赛|淘汰赛|半决赛|决赛",
    r"梅西|C罗|姆巴佩|内马尔|FIFA",
    r"五一.*出游|假期.*预订",
    r"红海航道|美伊.*和平|美伊.*封锁|美伊.*谈判|美伊会谈|霍尔木兹",
    r"伊朗.*美国|伊朗.*核|伊朗.*制裁|伊朗代表|伊朗宣布",
    r"城市更新行动",
    r"NBA|火箭队|篮球|湖人|勇士队|季后赛|球员|球队",
    r"茅台|五粮液|白酒|金徽酒",
    r"永辉超市|开立医疗|网达软件",
    r"造谣|谣言|行政拘留|行拘|刑事拘留|警方通报|不实信息|治安管理处罚|寻衅滋事",
    r"分手|绯闻|恋情|求婚|恋情曝光",
]

# 仅日报模式排除的宏观/政策类模式；雷达模式需要保留这些新闻用于宏观评分。
EXCLUDE_PATTERNS_DAILY = [
    r"黄金.*大涨|金价.*上涨",
    r"房价.*信号|二手房复苏",
    r"GDP.*增长|国民经济",
    r"央行.*降准|央行.*降息|货币政策|美联储.*加息|美联储.*降息",
    r"贸易逆差", r"GDP.*(终值|初值|年化|增速|数据|环比)",
    r"PCE|CPI.*(预期|数据|同比|环比)|PPI",
    r"加息预期|降息预期|加息概率|降息概率",
    r"楼市新政|房地产.*(新政|调控)|房屋销售|二手房.*(成交|价格)",
    r"摊余.*债基|信用债.*(抢筹|利差|发行)|债市.*(增量资金|震荡)",
    r"燃油|原油.*价格|石油.*出口|油价",
]


def _kw_matches(kw: str, content: str) -> bool:
    k = kw.lower()
    c = content.lower()
    if k.isascii() and len(k) <= 4:
        return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", c) is not None
    return k in c


def filter_by_relevance(news_list: list[dict[str, Any]], *, mode: str = "daily") -> list[dict[str, Any]]:
    """领域过滤。

    mode="daily"  → 仅保留科技关键词命中，同时排除宏观/政策类新闻
    mode="radar"  → 保留科技 + 宏观关键词命中，不排除宏观/政策新闻
    """
    # 日报模式排除宏观类模式；雷达模式不排除（保留给宏观评分器）。
    exclude_patterns = (
        EXCLUDE_PATTERNS + EXCLUDE_PATTERNS_DAILY if mode == "daily" else EXCLUDE_PATTERNS
    )
    # 雷达模式允许宏观关键词通过白名单。
    allow_keywords = (
        CORE_TECH_KEYWORDS + MACRO_KEYWORDS if mode == "radar" else CORE_TECH_KEYWORDS
    )
    result: list[dict[str, Any]] = []
    for news in news_list:
        title = news.get("title", "")
        summary = news.get("summary", "")
        content = f"{title} {summary}".lower()
        excluded = False
        for pattern in exclude_patterns:
            try:
                if re.search(pattern, title, re.IGNORECASE):
                    excluded = True
                    break
            except re.error:
                continue
        if excluded:
            continue
        if is_low_value_column_post(title):
            continue
        if any(_kw_matches(kw, content) for kw in allow_keywords):
            result.append(news)
    logger.info("日报领域过滤[%s]: %d条 -> %d条", mode, len(news_list), len(result))
    return result


# ---- 事件类型 + 评分 ----

EVENT_TYPES: dict[str, dict[str, Any]] = {
    "tier_a_ipo": {"keywords": ["ipo", "上市", "港股上市", "科创板上市", "纳斯达克", "纽交所"],
                    "label": "IPO/上市", "weight": 25, "icon": "🔴"},
    "tier_a_mega_deal": {"keywords": ["并购", "收购", "重组", "私有化", "要约"],
                          "label": "并购重组", "weight": 24, "icon": "🔴"},
    "tier_b_risk": {"keywords": ["泡沫", "暴跌", "崩盘", "爆仓", "违约", "退市风险",
                                  "踩踏", "爆雷", "债务危机", "破产", "清算", "大规模召回",
                                  "反垄断", "出口管制", "制裁", "实体清单", "调查", "罚款",
                                  "断供", "封锁", "关税壁垒", "强制退市", "暂停上市"],
                     "label": "风险预警", "weight": 22, "icon": "⚠️"},
    "tier_b_finance": {"keywords": ["融资", "募资", "估值", "亿美元", "融资轮", "种子轮",
                                     "天使轮", "a轮", "b轮", "c轮", "基石", "超额认购"],
                        "label": "融资估值", "weight": 20, "icon": "🟠"},
    "tier_b_policy": {"keywords": ["产业政策", "监管", "新规", "试点", "放宽", "收紧", "补贴",
                                    "减税", "退税", "扶持", "鼓励", "指导意见", "规划", "碳中和"],
                       "label": "政策监管", "weight": 18, "icon": "📋"},
    "tier_c_milestone": {"keywords": ["首发", "量产", "交付", "中标", "落地", "获批", "认证"],
                          "label": "业务里程碑", "weight": 14, "icon": "🟡"},
    "tier_c_collab": {"keywords": ["合作", "签约", "战略", "入股", "增持", "投资", "设立基金"],
                       "label": "合作战略", "weight": 12, "icon": "🟡"},
    "tier_c_launch": {"keywords": ["发布", "推出", "上线", "开源", "揭幕"],
                       "label": "产品发布", "weight": 11, "icon": "🟢"},
    "tier_d_financials": {"keywords": ["财报", "净利", "净利润", "营收", "营业收入", "收入",
                                         "业绩预告", "盈利", "亏损"],
                            "label": "财报业绩", "weight": 9, "icon": "📊"},
    "tier_d_market": {"keywords": ["股价", "市值", "涨停", "跌停", "大涨", "大跌", "回购",
                                     "分红", "派息", "股息"],
                        "label": "市场表现", "weight": 8, "icon": "📊"},
}

TIER1_COMPANIES = [
    "英伟达", "nvidia", "博通", "broadcom", "台积电", "tsmc", "openai", "anthropic",
    "deepseek", "华为", "三星", "samsung", "sk海力士", "sk hynix", "美光", "micron",
    "闪迪", "sandisk", "spacex",
]
TIER2_COMPANIES = [
    "特斯拉", "tesla", "宁德时代", "比亚迪", "腾讯", "阿里", "阿里巴巴", "字节",
    "百度", "智谱", "月之暗面", "kimi", "千问", "通义", "meta", "google", "谷歌",
    "微软", "microsoft", "苹果", "apple", "亚马逊", "amazon", "中芯国际", "中际旭创",
    "marvell", "amd", "强脑科技", "本源量子", "博睿康",
]


def _classify_event(content: str, title: str) -> tuple[Optional[dict], int]:
    title_lower = title.lower()
    content_lower = content.lower()
    for info in EVENT_TYPES.values():
        for kw in info["keywords"]:
            kw_l = kw.lower()
            if kw_l in title_lower:
                return info, info["weight"]
            if kw_l in content_lower:
                return info, max(1, info["weight"] // 3)
    return None, 0


def _parse_news_time(news: dict[str, Any]) -> Optional[datetime]:
    from src.eventradar.dedup import parse_published
    return parse_published(news.get("published_at") or news.get("published"))


def _time_decay_factor(pub_dt: Optional[datetime]) -> float:
    if not pub_dt:
        return 0.90
    try:
        age_hours = (datetime.now() - pub_dt).total_seconds() / 3600
        if age_hours < 0:
            return 1.00
        if age_hours < 6:
            return 1.00
        if age_hours < 12:
            return 0.95
        if age_hours < 24:
            return 0.85
        return max(0.70, 1.0 - age_hours / 120)
    except Exception:
        return 0.90


def _extract_magnitude(content: str) -> float:
    text = content.lower()
    if re.search(r"\d{3,}\s*亿", text) or re.search(r"\d{2,}\s*亿美元", text):
        return 1.30
    if re.search(r"\d{2,}\s*亿", text) or re.search(r"\d+\s*亿美元", text):
        return 1.15
    if re.search(r"\d+(?:\.\d+)?\s*%", text):
        return 1.10
    if re.search(r"\d{2,}", text):
        return 1.05
    return 1.00


def score_and_classify(news_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for news in news_list:
        title = news["title"]
        summary = news.get("summary", "")
        content = f"{title} {summary}".lower()
        score = 10
        event_info, event_score = _classify_event(content, title)
        score += event_score
        if event_info:
            weight = event_info["weight"]
            if not any(kw.lower() in title.lower() for kw in event_info["keywords"]):
                weight = min(weight, 21)
            if weight >= 22:
                signal_type = "strong_signal"
            elif weight >= 10:
                signal_type = "watch"
            else:
                signal_type = "data_ref"
            event_label = event_info["label"]
            signal_hits = [f"{event_info['icon']} {event_label}"]
        else:
            signal_type = "data_ref"
            event_label = ""
            signal_hits = []
        company_bonus = 0
        for company in TIER1_COMPANIES:
            if company.lower() in content:
                company_bonus = 8
                signal_hits.append(f"★{company}")
                break
        if company_bonus == 0:
            for company in TIER2_COMPANIES:
                if company.lower() in content:
                    company_bonus = 5
                    signal_hits.append(f"☆{company}")
                    break
        score += company_bonus
        for kw in ["首创", "突破", "全球第一", "sota", "首个", "刷新纪录", "世界首例", "行业首创"]:
            if kw in title:
                score += 8
                signal_hits.append(f"💡{kw}")
                break
        mag_factor = _extract_magnitude(content)
        decay_factor = _time_decay_factor(_parse_news_time(news))
        final_score = round(score * mag_factor * decay_factor, 1)
        news["score"] = final_score
        news["signal_type"] = signal_type
        news["signal_hits"] = signal_hits
        news["event_type"] = event_label or "-"
        news["mag_factor"] = round(mag_factor, 2)
        news["decay_factor"] = round(decay_factor, 2)
        if final_score >= 42:
            news["value_tier"] = "🔴"
        elif final_score >= 32:
            news["value_tier"] = "🟠"
        elif final_score >= 22:
            news["value_tier"] = "🟡"
        else:
            news["value_tier"] = "⚪"
    news_list.sort(key=lambda x: x["score"], reverse=True)
    return news_list[:MAX_FINAL]


# ---- 雷达评分（突发雷达 tab 使用，宏观/范式导向，权重见 SKILL.md）----

RADAR_EVENT_TYPES: dict[str, dict[str, Any]] = {
    "tech_paradigm": {"keywords": ["突破性", "商用化", "量产", "国产替代", "卡脖子",
                                   "范式", "重构", "颠覆性", "sota", "全球第一",
                                   "行业首创", "世界首例"],
                       "label": "技术范式突破", "weight": 30, "icon": "🔴", "require_title_for_strong": True},
    "monetary_turning": {"keywords": ["拐点", "周期转向", "加息周期", "降息周期", "缩表", "扩表",
                                      "央行", "货币政策", "降准", "降息", "加息", "利率",
                                      "流动性", "存款准备金", "逆回购", "mlf", "lpr", "公开市场",
                                      "美联储", "fed", "欧央行", "日央行", "英央行",
                                      "财政", "赤字", "国债", "地方债", "专项债",
                                      "债市", "债券", "收益率", "信用债", "利率债"],
                          "label": "货币政策拐点", "weight": 25, "icon": "🔴"},
    "systemic_risk": {"keywords": ["系统性", "违约", "挤兑", "流动性危机", "黑天鹅", "崩盘", "爆雷",
                                   "危机", "破产", "清算", "退市", "债务危机", "金融危机",
                                   "银行危机", "灰犀牛"],
                       "label": "系统性风险", "weight": 25, "icon": "🔴", "require_title_for_strong": True},
    "institution_change": {"keywords": ["制度性", "历史性", "首次", "里程碑", "监管", "数据主权",
                                         "反垄断", "平台治理", "出口管制", "制裁", "脱钩", "禁运",
                                         "封锁", "战争", "冲突升级", "新规", "试点", "立法",
                                         "修法", "改革", "政策", "数据安全", "金融监管",
                                         "证监会", "银保监会", "金融委"],
                            "label": "范式/制度变革", "weight": 20, "icon": "🟠"},
    "geopolitical": {"keywords": ["地缘", "制裁", "脱钩", "禁运", "封锁", "战争", "冲突升级",
                                  "关税", "贸易战", "实体清单", "芯片法案", "反制裁"],
                      "label": "地缘政治冲击", "weight": 20, "icon": "🟠"},
    "public_health": {"keywords": ["致死率高", "传染", "疫情危机", "公共卫生危机", "大流行"],
                       "label": "公共卫生危机", "weight": 20, "icon": "🟠"},
    "industry_reshape": {"keywords": ["产业链", "重塑", "供应链", "重构", "转移", "能源",
                                      "原油", "石油", "天然气", "煤炭", "opec", "油价",
                                      "大宗商品", "铁矿石", "铜价", "黄金", "贵金属",
                                      "房地产", "楼市", "房价", "地产"],
                          "label": "产业链重塑", "weight": 15, "icon": "🟡"},
    "diffusion": {"keywords": ["用户破亿", "指数增长", "历史最快", "颠覆", "普及"],
                   "label": "扩散类", "weight": 15, "icon": "🟡"},
}


def _classify_event_radar(content: str, title: str) -> tuple[Optional[dict], int, bool]:
    """Return (event_info, score, title_hit). Title hit = full weight, body = 1/3."""
    title_lower = title.lower()
    content_lower = content.lower()
    for info in RADAR_EVENT_TYPES.values():
        for kw in info["keywords"]:
            kw_l = kw.lower()
            if kw_l in title_lower:
                return info, info["weight"], True
            if kw_l in content_lower:
                return info, max(1, info["weight"] // 3), False
    return None, 0, False


def _extract_duration_factor(content: str) -> float:
    """影响时长因子：>5 年 ×1.30；1–5 年 ×1.15；<1 年 ×1.00"""
    if re.search(r"[5-9]\s*年|十年|长期|永久", content):
        return 1.30
    if re.search(r"[1-4]\s*年", content):
        return 1.15
    return 1.00


def _extract_breadth_factor(content: str) -> float:
    """广度因子：跨资产 ×1.30；跨行业 ≥3 ×1.15；单行业/单公司 ×1.00"""
    if re.search(r"跨资产|多资产|股债商|全球市场", content):
        return 1.30
    industries = re.findall(
        r"(半导体|芯片|人工智能|ai|新能源|汽车|医药|生物|金融|地产|消费|能源|军工|"
        r"云计算|软件|互联网|制造|化工|农业)", content.lower())
    if len(set(industries)) >= 3:
        return 1.15
    return 1.00


def score_and_classify_radar(news_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Radar-tab scoring: macro/paradigm oriented (weights per SKILL.md)."""
    for news in news_list:
        title = news["title"]
        summary = news.get("summary", "")
        content = f"{title} {summary}".lower()
        score = 10
        event_info, event_score, title_hit = _classify_event_radar(content, title)
        score += event_score
        if event_info:
            weight = event_info["weight"]
            # 强烈信号必须标题命中（技术范式突破/风险类等标注 require_title_for_strong 的类型）
            require_title = event_info.get("require_title_for_strong", False)
            if require_title and not title_hit:
                weight = min(weight, 21)
            if weight >= 22:
                signal_type = "strong_signal"
            elif weight >= 10:
                signal_type = "watch"
            else:
                signal_type = "data_ref"
            event_label = event_info["label"]
            signal_hits = [f"{event_info['icon']} {event_label}"]
        else:
            signal_type = "data_ref"
            event_label = ""
            signal_hits = []
        # 公司加分（与日报共用分档）
        company_bonus = 0
        for company in TIER1_COMPANIES:
            if company.lower() in content:
                company_bonus = 8
                signal_hits.append(f"★{company}")
                break
        if company_bonus == 0:
            for company in TIER2_COMPANIES:
                if company.lower() in content:
                    company_bonus = 5
                    signal_hits.append(f"☆{company}")
                    break
        score += company_bonus
        # 创新/突破加分
        for kw in ["首创", "突破", "全球第一", "sota", "首个", "刷新纪录", "世界首例", "行业首创"]:
            if kw in title:
                score += 8
                signal_hits.append(f"💡{kw}")
                break
        mag_factor = _extract_magnitude(content)
        duration_factor = _extract_duration_factor(content)
        breadth_factor = _extract_breadth_factor(content)
        decay_factor = _time_decay_factor(_parse_news_time(news))
        final_score = round(score * mag_factor * duration_factor * breadth_factor * decay_factor, 1)
        news["score"] = final_score
        news["signal_type"] = signal_type
        news["signal_hits"] = signal_hits
        news["event_type"] = event_label or "-"
        news["mag_factor"] = round(mag_factor, 2)
        news["duration_factor"] = round(duration_factor, 2)
        news["breadth_factor"] = round(breadth_factor, 2)
        news["decay_factor"] = round(decay_factor, 2)
        if final_score >= 42:
            news["value_tier"] = "🔴"
        elif final_score >= 32:
            news["value_tier"] = "🟠"
        elif final_score >= 22:
            news["value_tier"] = "🟡"
        else:
            news["value_tier"] = "⚪"
    news_list.sort(key=lambda x: x["score"], reverse=True)
    return news_list[:MAX_FINAL]


# ---- 话题聚类去重 ----

def _extract_topic_keywords(title: str) -> set[str]:
    stop_words = {
        "的", "了", "在", "是", "和", "与", "将", "已", "也", "要",
        "能", "会", "被", "把", "让", "对", "从", "到", "又", "更",
        "最", "为", "上", "下", "中", "里", "后", "前", "出", "有",
        "重磅", "突发", "独家", "最新", "今日", "迎来", "临近",
    }
    words: set[str] = set()
    clean = re.sub(r'[""「」\'\'《》\[\]【】]', ' ', title)
    for seg in re.split(r'\s+', clean):
        seg = seg.strip()
        if not seg:
            continue
        for w in re.findall(r'[a-zA-Z0-9]+', seg):
            w = w.lower()
            if len(w) >= 2 and w not in stop_words:
                words.add(w)
        for cn in re.findall(r'[\u4e00-\u9fff]+', seg):
            for i in range(len(cn) - 1):
                gram = cn[i:i + 2]
                if gram not in stop_words:
                    words.add(gram)
    return words


def topic_dedup(news_list: list[dict[str, Any]], threshold: float = 0.12) -> list[dict[str, Any]]:
    if len(news_list) <= 1:
        return news_list
    keyword_sets = [_extract_topic_keywords(n["title"]) for n in news_list]
    n = len(news_list)
    group = list(range(n))

    def find(x: int) -> int:
        while group[x] != x:
            group[x] = group[group[x]]
            x = group[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            group[rb] = ra

    for i in range(n):
        prefix_i = re.findall(r'[\u4e00-\u9fff]{4}', news_list[i]["title"])
        if not prefix_i:
            continue
        pi = prefix_i[0]
        for j in range(i + 1, n):
            prefix_j = re.findall(r'[\u4e00-\u9fff]{4}', news_list[j]["title"])
            if prefix_j and prefix_j[0] == pi:
                union(i, j)
    for i in range(n):
        if not keyword_sets[i]:
            continue
        for j in range(i + 1, n):
            if not keyword_sets[j] or find(i) == find(j):
                continue
            inter = len(keyword_sets[i] & keyword_sets[j])
            smaller = min(len(keyword_sets[i]), len(keyword_sets[j]))
            sim = inter / smaller if smaller > 0 else 0
            if sim >= threshold:
                union(i, j)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    result = []
    for indices in groups.values():
        best = max(indices, key=lambda idx: news_list[idx].get("score", 0))
        result.append(news_list[best])
    logger.info("日报话题去重: %d条 -> %d条", n, len(result))
    return result


# ---- 正文抓取 + 规则摘要 ----

def fetch_article_content(url: str) -> Optional[str]:
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (vibe-trading event radar)"}
        if "wallstreetcn.com" in url:
            m = re.search(r"/(articles|lives|charts)/(\d+)", url)
            if m:
                kind, aid = m.group(1), m.group(2)
                api = f"https://api-one.wallstcn.com/apiv1/content/{kind}/{aid}?extract=0"
                r = requests.get(api, headers={**headers, "Referer": "https://wallstreetcn.com/"},
                                 timeout=FETCH_TIMEOUT)
                if r.status_code == 200:
                    j = r.json()
                    if j.get("code") == 20000:
                        content = (j.get("data") or {}).get("content", "")
                        if content:
                            soup = BeautifulSoup(content, "html.parser")
                            for tag in soup.select("script, style, iframe"):
                                tag.decompose()
                            text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
                            return text if len(text) >= 50 else None
            return None
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        detail = soup.select_one("div.detail-content")
        if not detail:
            for sel in ["article", ".article-content", ".news-content",
                        "[class*=detail-content]", "[class*=article-body]"]:
                detail = soup.select_one(sel)
                if detail and len(detail.get_text(strip=True)) > 200:
                    break
        if not detail:
            return None
        for tag in detail.select("script, style, iframe, .ad, .share, .related"):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n", detail.get_text(separator="\n", strip=True))
        return text if len(text) >= 50 else None
    except Exception:
        return None


def _merge_unclosed_quotes(sentences: list[str], max_len: int = 200) -> list[str]:
    merged: list[str] = []
    for s in sentences:
        if merged and merged[-1].count("“") != merged[-1].count("”") and len(merged[-1]) < max_len:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return merged


def _truncate_at_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    p = max(cut.rfind(c) for c in "。！？")
    if p > limit * 0.5:
        return cut[:p + 1]
    p = max(cut.rfind(c) for c in "；，,")
    if p > limit * 0.5:
        return cut[:p] + "。"
    return cut


def generate_rule_summary(full_text: str, title: str) -> str:
    if not full_text:
        return ""
    image_caption_re = re.compile(
        r"（[^）]{0,30}?来源[:：]\s*(?:TradingView|Wind|同花顺|东方财富)[^）]{0,10}）"
    )
    raw_lines = []
    for line in full_text.split("\n"):
        s = LEAD_PREFIX_RE.sub("", line).strip()
        s = s.lstrip("，,。、；; ")
        s = s.replace("▍", "")
        s = image_caption_re.sub("", s).strip()
        if s:
            raw_lines.append(s)
    noise_contains = {
        "面对每天上千份", "请看财联社公司新闻部", "栏目，我们派驻全国",
        "公告里一堆专业术语", "重大事项公告动辄几十页几百页", "重点是啥？",
    }
    byline_startswith = ("编辑 ", "财联社记者", "科创板日报记者", "蓝鲸科技记者", "小鲸注：")
    date_line_re = re.compile(
        r"^财联社\d{4}年\d{1,2}月\d{1,2}日讯(\s*（[编辑记者]\s*\S+?)?\s*）?$"
    )

    def is_noise(line: str) -> bool:
        if date_line_re.match(line):
            return True
        if any(pat in line for pat in noise_contains):
            return True
        if line.startswith(byline_startswith):
            return True
        if LINE_DROP_RE.match(line):
            return True
        return False

    clean_lines = [line for line in raw_lines if not is_noise(line)]
    clean_text = "\n".join(clean_lines)
    clean_text = TAIL_SIGN_RE.sub("", clean_text.rstrip()).strip()
    if len(clean_text) < 30:
        return ""
    sentences = re.split(r"(?<=[。！？；])", clean_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 10]
    sentences = _merge_unclosed_quotes(sentences)
    candidates: list[str] = []
    seen: set[str] = set()
    for sent in sentences:
        key = sent[:50]
        if key in seen:
            continue
        seen.add(key)
        candidates.append(sent)
    parts: list[str] = []
    total = 0
    for sent in candidates:
        if total + len(sent) > MAX_SUMMARY_LEN:
            break
        parts.append(sent)
        total += len(sent)
    result = "".join(parts)
    result = _truncate_at_boundary(result, MAX_SUMMARY_LEN)
    if result and result[-1] in "；，":
        result = result[:-1] + "。"
    return result.strip()


def enrich_summaries(news_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    success = 0
    for news in news_list:
        url = news.get("url") or news.get("link", "")
        if not url:
            continue
        full_text = fetch_article_content(url)
        if full_text:
            summary = generate_rule_summary(full_text, news["title"])
            if summary and len(summary) >= 30:
                news["summary"] = summary
                news["has_full_summary"] = True
                success += 1
        time.sleep(FETCH_DELAY)
    for n in news_list:
        s = n.get("summary", "")
        if s:
            n["summary"] = strip_noise_affixes(s)
    logger.info("日报正文摘要增强: %d/%d 篇成功", success, len(news_list))
    return news_list


# ---- 6 板块 Markdown 日报生成 ----

SIGNAL_ICONS = {"strong_signal": "🔥", "watch": "👀", "data_ref": "📊"}
SIGNAL_LABELS = {"strong_signal": "强烈信号", "watch": "跟踪观察", "data_ref": "数据参考"}
VALUE_ORDER = {"🔴": 0, "🟠": 1, "🟡": 2, "⚪": 3}


def select_top5(news_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank by value tier then score; deprioritize column/editorial posts."""
    ranked = sorted(news_list, key=lambda x: (VALUE_ORDER.get(x["value_tier"], 99), -x["score"]))
    top5 = ([n for n in ranked if not is_column_post(n["title"])]
            + [n for n in ranked if is_column_post(n["title"])])[:5]
    return top5


def generate_report(news_list: list[dict[str, Any]]) -> str:
    today = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
    now = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    total = len(news_list)
    value_counts: dict[str, int] = {}
    signal_counts = {"strong_signal": 0, "watch": 0, "data_ref": 0}
    for n in news_list:
        vt = n["value_tier"]
        value_counts[vt] = value_counts.get(vt, 0) + 1
        signal_counts[n["signal_type"]] = signal_counts.get(n["signal_type"], 0) + 1

    lines: list[str] = []
    lines.append("# 💰 财经科技资讯日报")
    lines.append("")
    lines.append(f"**日期**: {today}  ")
    lines.append(f"**生成时间**: {now}  ")
    lines.append(f"**新闻数量**: {total} 条")
    lines.append("")

    # 板块 1: 今日概览
    lines.append("## 📊 今日概览")
    lines.append("")
    value_str = " | ".join(
        f"**{k}** {value_counts.get(k, 0)}条"
        for k in ["🔴", "🟠", "🟡", "⚪"] if value_counts.get(k, 0) > 0
    )
    lines.append(f"**价值分布**: {value_str}")
    lines.append("")
    signal_str = " | ".join(
        f"{SIGNAL_ICONS[k]} {SIGNAL_LABELS[k]} {v}条"
        for k, v in signal_counts.items() if v > 0
    )
    lines.append(f"**投资信号**: {signal_str}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 板块 2: Top 5
    top5 = select_top5(news_list)
    if top5:
        lines.append("## 🎯 今日高价值事件 Top 5")
        lines.append("")
        lines.append("| # | 事件 | 信号 |")
        lines.append("|---|------|------|")
        for i, n in enumerate(top5, 1):
            icon = SIGNAL_ICONS[n["signal_type"]]
            short_title = n["title"][:55] + "…" if len(n["title"]) > 55 else n["title"]
            short_title = short_title.replace("|", "｜")
            lines.append(f"| {i} | **{short_title}** | "
                         f"{n['value_tier']} {icon} {SIGNAL_LABELS[n['signal_type']]} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 板块 3: 投资信号雷达
    signal_news = [n for n in news_list if n["signal_type"] != "data_ref"]
    if signal_news:
        lines.append("## 💰 投资信号雷达")
        lines.append("")
        lines.append("> 识别潜在投资参考方向")
        lines.append("")
        lines.append("| 信号 | 标题 | 价值 | 来源 |")
        lines.append("|------|------|------|------|")
        for n in signal_news:
            icon = SIGNAL_ICONS[n["signal_type"]]
            label = SIGNAL_LABELS[n["signal_type"]]
            short_title = n["title"][:55] + "…" if len(n["title"]) > 55 else n["title"]
            short_title = short_title.replace("|", "｜")
            source = n.get("source_name") or n.get("source", "")
            lines.append(f"| {icon} {label} | {short_title} | {n['value_tier']} | {source} |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 板块 4: Our Take
    type_groups: dict[str, list[dict]] = {}
    for n in news_list:
        if n["signal_type"] == "strong_signal":
            event = n.get("event_type", "其他")
            if event and event != "-":
                type_groups.setdefault(event, []).append(n)
    if type_groups:
        lines.append("## 💡 Our Take")
        lines.append("")
        for event, items in type_groups.items():
            titles = "、".join(f"「{n['title'][:25]}」" for n in items[:3])
            lines.append(f"- **{event}**（{len(items)} 条）：{titles}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 板块 5: Thesis Tracker
    thesis_items = [n for n in news_list if n["signal_type"] == "strong_signal"
                    and n.get("event_type") in ("IPO/上市", "并购重组", "融资估值")]
    if thesis_items:
        lines.append("## 📌 Thesis Tracker")
        lines.append("")
        for n in thesis_items:
            lines.append(f"- **{n['title']}** — {n.get('event_type', '')} "
                         f"（{n['value_tier']} {n['score']}分）")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 板块 6: 完整资讯列表
    lines.append("## 📋 完整资讯列表")
    lines.append("")
    for i, n in enumerate(news_list, 1):
        icon = SIGNAL_ICONS[n["signal_type"]]
        label = SIGNAL_LABELS[n["signal_type"]]
        source = n.get("source_name") or n.get("source", "")
        lines.append(f"**{i}. {n['title']}**  {n['value_tier']} | {icon} {label} | 来源: {source}")
        summary = (n.get("summary") or "").strip()
        if summary:
            for sl in summary.split("\n"):
                if sl.strip():
                    lines.append(f"> {sl.strip()}")
        url = n.get("url") or n.get("link", "")
        if url:
            lines.append(f"🔗 [{url}]({url})")
        lines.append("")
    return "\n".join(lines)


# ---- 管线入口 ----

def build_daily_report(scope: str = "all", *, mode: str = "daily") -> dict[str, Any]:
    """Build the daily report.

    mode="daily"  → finance/company scoring (10 event types, for the 日报 tab)
    mode="radar"  → macro/paradigm scoring (8 event types, for the 突发雷达 tab)
    """
    from src.eventradar import sources
    collected = sources.collect(scope)
    candidates = collected["candidates"]
    logger.info("日报采集[%s]: %d 条候选", mode, len(candidates))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for news in candidates:
        h = hashlib.md5(news["title"].encode("utf-8")).hexdigest()[:12]
        if h not in seen:
            seen.add(h)
            deduped.append(news)
    logger.info("日报 MD5 去重: %d -> %d", len(candidates), len(deduped))

    filtered = filter_by_relevance(deduped, mode=mode)
    if not filtered:
        now = datetime.now(SHANGHAI_TZ)
        return {
            "markdown": f"# 💰 财经科技资讯日报\n\n**日期**: {now.strftime('%Y-%m-%d')}\n\n"
                        f"今日无符合条件的科技财经资讯。",
            "news_count": 0,
            "generated_at": now,
            "top5": [],
        }

    scorer = score_and_classify_radar if mode == "radar" else score_and_classify
    scored = scorer(filtered)
    deduped_topics = topic_dedup(scored)
    enriched = enrich_summaries(deduped_topics)
    markdown = generate_report(enriched)
    top5 = select_top5(enriched)
    return {
        "markdown": markdown,
        "news_count": len(enriched),
        "generated_at": datetime.now(SHANGHAI_TZ),
        "top5": top5,
    }
