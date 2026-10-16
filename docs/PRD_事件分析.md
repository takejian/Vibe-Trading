# PRD：事件分析（Event Analysis）

| 项 | 内容 |
| --- | --- |
| 版本 | v1.2（草案）；v1.0 MVP 与 v1.1（专业双源 / 每日 04:00 扫描 / Top5）已实现 |
| 日期 | 2026-10-15 |
| 范围 | 前端 Web UI + FastAPI 后端 + 本地 DuckDB；全球宏观与中国市场突发事件，跨资产影响分析 |
| 关联模块 | Swarm 多智能体编排（presets/runtime/SSE）、技能体系（skills/skill_catalog，含内置 investment-news-collector / wallstreetcn-news）、定时任务（lifespan asyncio 调度）、行情与量化（market_data、quantlib.eventstudy）、网页深读（read_url）、关注列表（watchlist）、模拟持仓（paper）、报告中心（reports） |

---

## 1. Executive Summary

### 1.1 Problem Statement

重大投资机会往往由**突发事件与范式级新事物**驱动（新冠疫情、AI 产业浪潮、俄乌战争、超强厄尔尼诺），这类机会的共同特征是：发生时新闻混杂、真假难辨，多数人在"是否真实、是否是新事物、影响多大、如何应对"四个问题上反应迟缓，等形成共识时机会已经错过。当前系统的能力缺口：

1. **没有突发新闻雷达**：v1.1 前系统只有按需查询的通用财经头条工具，无持续采集、多源聚合、去重聚类与真实性核验，同一事件被各媒体换词重写后会被反复当作"新闻"；v1.0 初版曾用搜索引擎广撒网，噪声大，v1.1 已收敛为两条专业财经电讯。
2. **没有事件实体与判重机制**：事件无指纹、无生命周期、无证据合并，智能体/skill 无法回答"这件事之前是不是已经报过"。
3. **现有 Event-Driven Task Force 只覆盖个股公司事件**（并购、减持、诉讼，见 `agent/src/swarm/presets/event_driven_task_force.yaml`），不处理宏观/地缘/范式级事件；其影响分析对象是单个公司估值，而用户需要的是跨资产、跨行业赛道的传导分析与历史机会复盘。

### 1.2 Proposed Solution

在菜单栏新增独立的**事件分析**（Event Analysis，路由 `/event`），页内三个模块：

1. **突发雷达（Breaking Radar，已实现 v1.0/v1.1）**：每日 04:00 从两条专业财经电讯——`investment-news-collector`（财联社深度·头条/环球）与 `wallstreetcn-news`（华尔街见闻 7x24 快讯/全球深读）——各取编辑部排序**头部 5 条**（共约 20 条）入管，经"去重聚类 → 结构化抽取 → 真实性核验 → 新颖度/范式判定"门控管道，默认只展示当日**最重要 5 条**，带**核验状态、信源数、影响等级、新颖度标签**。真实性通过信源分级 + 独立信源交叉确认 + LLM 一致性判断综合打分；新颖度判定把事件分为"已知延续 / 已知升级 / **全新范式**"，全新范式事件（新事物，重大机会候选）置顶。判重与识别由 `breaking-news-radar` skill + 扫描员智能体配合 `event_lookup` 工具完成。**雷达是工作台而非档案**：非 Top5 事件在下一轮扫描直接覆盖、不跟踪真假；Top5 经用户丢弃也直接物理删除。
2. **事件档案（Event Archive，v1.2 新增）**：用户从雷达每日 Top5 中**保留**下来的事件进入此 Tab 长期沉淀（丢弃的不保存）。档案记录事件首次入榜日期与信源、统计其近 30 天登上每日 Top5 的**日次数榜单**，支持状态/范式标签与日期区间筛选；待核验事件由系统在**每日 05:00、每周一 05:00、每月 1 日 05:00**自动跟踪复查真假并填写日/周/月复核结论，也支持手动立即复查；档案事件下挂载历次 Task Force 报告并可再次发起，已证实事件可一键发起当下 live 影响分析。
3. **Event-Driven Task Force（宏观增强版，已实现 v1.0；v1.2 补操作能力）**：swarm 预设 `macro_event_task_force`（事件情报官 → 影响分析师 → 历史类比师 → 机会策略师链式编排），支持 `live`（当下事件展望）与 `retrospective`（历史事件复盘）。Task Force Tab 只允许从**近 7 天内已证实**的雷达事件发起（更早的事件到事件档案内发起）；报告列表除标题外展示生成时间、预期结果与指导建议，并支持取消运行、删除、勾选对比（多篇并排，不做 AI 对比）、失败重试；报告在数月/数年后可做事后复盘，评价当时分析的准确性。

### 1.3 Success Criteria

1. 手动触发一次扫描后，**3 分钟内**事件流可见结果；同一事件被 3 个不同信源换词报道时，事件流中**只出现 1 个事件**、其证据链含 3 条来源（固定样本集判重准确率 ≥ 95%，误合并率 ≤ 5%）。
2. 真实性状态机判定可复现：单源消息默认"未证实"，禁止自动升为"已证实"；固定样本集中谣言/反转新闻 100% 不进入"已证实"（宁可留在复核队列，不允许假确认）。
3. 标注为"全新范式"的事件必须同时给出四要素评分（政策持续性/投资周期/产业链宽度/叙事热度）与长期赛道映射，缺一项不得打该标签（结构化校验，非提示词自觉）。
4. 任一雷达事件可一键发起 macro Task Force run，run 上下文自动包含事件摘要与全部证据链接；run 过程经现有 SSE 流式可见，结束后报告在事件详情与 `/reports` 两处可查。
5. MVP 交付时可现场演示四份报告产出：**厄尔尼诺 live 报告** + **新冠 / AI / 俄乌三份 retrospective 复盘报告**，复盘报告中的资产走势数据必须来自 `get_market_data` 实取、事件研究数值必须来自 `quantlib.eventstudy`，禁止臆造数字（沿用现有 preset 的 BMP p 值/样本量披露规则）。
6. 全部采集走既有免费数据源与免费官方接口（财联社/华尔街见闻），不新增付费依赖、不新增对外监听面。
7.（v1.2）每轮扫描入管候选恒为四个通道各头部 5 条、总数 ≤ 20；图表/行情/百科等非文章条目零入库；每日 Top5 之外的事件为临时数据，下一轮扫描即覆盖，不产生跟踪记录。
8.（v1.2）每日 Top5 可逐条"保留/丢弃"：丢弃的事件物理删除且不留痕，保留的事件出现在事件档案 Tab，可查首次入榜日期、信源与近 30 天入榜日次数。
9.（v1.2）档案中待核验事件的日/周/月复核记录由 05:00 三个锚点自动产生，字段在 Web 可见；手动复查结果覆盖月复核；到达终态（已证实/谣言/丢弃）后自动复查停止。
10.（v1.2）任一报告可在 UI 完成取消、删除、重试与多选并排对比；报告支持事后评价（评级 + 文字 + 时间），评价与报告一同长期保留。

---

## 2. User Experience & Functionality

### 2.1 User Personas

- **主要用户：个人宏观/主题投资者（本地单用户）**。关注全球与中国的突发事件、政策与产业趋势，希望第一时间知道"发生了什么、是不是真的、是不是新东西、影响哪些资产、历史上类似机会怎么走的"，并把分析沉淀为可回看的报告。

### 2.2 菜单与入口变更

- **新增**：主导航项"事件分析"，路由 `/event`，图标建议 Radar / Newspaper（在 `frontend/src/components/layout/Layout.tsx:22-37` 的 NAV 数组中注册，建议置于"宏观分析"之后）。
- **不改动**任何现有菜单与路由；现有 `event_driven_task_force.yaml`（个股公司事件）保持原名原义不动，新预设以 `macro_event_task_force` 命名并存。

### 2.3 User Stories 与验收标准

#### Story 1：手动扫描突发新闻

> 作为用户，我希望点一下"立即扫描"，系统就从多个新闻源找出近期突发的、真实的重大新闻并自动结构化输出，而不用我自己刷各个财经网站。

**验收标准：**

- 雷达页顶部提供"立即扫描"按钮与扫描范围选择（中国 / 全球 / 全部，默认全部）；点击后显示扫描进度（采集源数、候选条数、各管道阶段计数），完成后轮询刷新事件流。
- 采集覆盖 10 类宏观事件矩阵：地缘冲突 / 货币财政政策 / 贸易关税 / 疫情公共卫生 / 气候灾害 / 技术突破 / 产业监管 / 大选政治 / 金融信用事件 / 大宗商品供给冲击。
- **数据源（v1.1 起为专业双源，已弃用东财头条 + DDG 检索式矩阵）**：① `investment-news-collector`（SkillHub 社区 skill 内置）——财联社深度「头条/环球」直连 cls.cn（沿用 RSSHub 的 SHA1→MD5 签名，无需本地 RSSHub）；② `wallstreetcn-news`——华尔街见闻 7x24 全球快讯（lives）+ 全球深读（information-flow），走 `api-one.wallstcn.com` 官方 JSON。范围 china/global/all 分别对应财联社 / 见闻 / 双源；单源失败隔离标注，不阻断整轮扫描。
- **入管量（v1.2 收敛）**：四个通道（财联社头条 / 财联社环球 / 见闻快讯 / 见闻深读）各自只取编辑部排序**头部 5 条**，单轮入管候选 **≤ 20 条**；通道不足 5 条按实际条数。保留原评分/聚类算法不变，仅在采集末端做 head-5 截断；非文章条目（见闻 `/charts/` 图表页、行情页、百科、法条、荐股广告等）由垃圾过滤器剔除，零入库。
- 每条输出为结构化事件卡：标题、事件类型、实体（国家/机构/公司/商品）、区域、首发时间、一句话摘要、影响方向（利好/利空/不确定）、涉及资产与行业、信源数、核验状态、新颖度标签、影响等级。
- 扫描批次有记录（开始/结束时间、各源状态、候选/入库/去重/进复核计数），可在页面查看最近批次。

#### Story 2：事件判重与证据合并（智能体/skill 可判重）

> 作为用户，我不希望同一件事被不同媒体重复刷屏；后续报道应该合并到原事件上，让我看到的是"一件事的完整证据链"。

**验收标准：**

- 管道一级判重：标题/正文 SimHash 指纹，海明距离 ≤ 阈值视为近似重复（纯 Python 实现，不引入新依赖）。
- 管道二级聚类：`主实体 × 事件类型 × 时间窗（默认 72 小时，可配置）` 相同的候选归并到同一事件；新候选作为证据行写入 `radar_evidence`，更新事件的 `last_update_at` 与信源数，不生成新事件。
- 智能体级判重：新增 `event_lookup` 工具（按实体关键词/指纹/时间窗检索 `radar_event`），扫描员智能体在结构化输出前**必须先调用**该工具做判重（skill prompt 强制步骤），命中已有事件则输出"合并"动作与 `event_id`，未命中才输出"新建"。
- 事件详情页展示证据链列表（信源名称、层级、标题、链接、发布时间、采集时间），按信源层级与时间排序；同 URL 证据防重（URL 唯一）。
- 时间窗过期后再次出现的同类事件允许新建，但两事件通过"相关事件"关联展示（同实体同类型）。
- **合并口径保持宽松（v1.2 明确不收紧）**：无 LLM 的启发式路径下允许主题相近事件合并（宁可相关信息聚在一张卡，也不漏报）；配 LLM 后由抽取阶段的 merge/new 判定与事实一致性提升精度。不新增"实体严格一致才合并"之类的硬限制。

#### Story 3：真实性核验与人工复核队列

> 作为用户，我希望系统明确告诉我一条突发新闻是"已证实"还是"未证实/有争议/谣言"，拿不准的进复核队列等我看，而不是把谣言当真事推给我。

**验收标准：**

- 信源分四级内置（可在配置中调整层级表）：T1 一手源（央行/政府/监管/交易所/公司公告、WHO 等官方机构）、T2 通讯社与权威媒体（新华社/路透/彭博/华尔街日报等）、T3 一般财经媒体、T4 聚合号/自媒体。
- 核验状态机：`未证实 → 核验中 → 已证实 / 有争议 / 谣言`。单源（无论层级）最高只能到"核验中"；升"已证实"需同时满足：≥ 2 个相互独立信源（非同集团转载）、其中至少 1 个 T1/T2、跨源关键事实一致性 LLM 判定通过、综合置信度 ≥ 配置阈值（默认 0.70）。
- 信源间关键事实冲突（伤亡数字、政策口径、官宣否认等）→ "有争议"；T1/T2 源明确辟谣或关键事实被证伪 → "谣言"。后两类不进正常事件流首屏，只在复核队列/筛选器中可见。
- 事件流提供状态筛选；"未证实/核验中"卡片有醒目标识且不可一键发起 Task Force（按钮置灰，提示先完成核验），"有争议/谣言"可查看但不提供分析入口。
- 复核队列页支持人工动作：`confirm`（升级已证实）、`flag_dispute`、`mark_rumor`、`dismiss`（非事件，丢弃）；人工动作记录操作人与时间，后续自动扫描不得推翻人工终态（人工终态优先级最高，新证据只追加提示）。

#### Story 4：新颖度与"新事物/长期区域"识别

> 作为用户，我希望系统区分"旧闻延续"和真正的新东西，并告诉我这个新东西是否对应长期赛道级机会——这是最值得重点关注的信号。

**验收标准：**

- 每个事件输出新颖度三分类：`已知延续`（同方向重复信息，低优先）、`已知升级`（既有事件扩大/加码/转折，中优先）、`全新范式`（新实体/新政策范式/新技术路线/新冲突形态，高优先）。
- "全新范式"必须附**四要素评分（各 1–5 分）**：政策持续性、投资周期长度、产业链波及宽度、叙事热度增速（同主题报道量的环比变化，可由证据条数时间序列近似）；总分 ≥ 阈值（默认 15/20）才可标"全新范式"，结构化校验强制。
- 范式事件必须映射到**长期赛道库**（内置：AI 与算力、能源转型、军工安全、供应链重构、人口与消费、国产替代、气候农业、货币体系等，可配置扩充），输出受影响赛道及方向。
- 事件流默认按"范式分 × 影响等级 × 新鲜度"排序，全新范式事件卡片带"重大机会候选"标识并置顶；提供按新颖度/类型/区域/状态的筛选。
- 事件详情展示"相似历史事件"（由 `event_lookup` 与 LLM 给出，如 2026 某事件类比 2020 疫情），供快速判断分量。

#### Story 5：一键发起 Event-Driven Task Force —— 当下事件影响报告（live）

> 作为用户，看到"超强厄尔尼诺已经形成"这样的事件，我希望一键让多智能体团队完成深度影响分析并输出报告：未来几个月通过什么链条影响哪些资产、概率多大、关注什么信号。

**验收标准：**

- 已证实事件详情页提供"启动 Task Force"按钮，可选模式（默认 live）、市场（A股/全球，默认全部）、时间跨度（默认 3–6 个月）；提交即调用 swarm runtime 发起 run（preset_name=`macro_event_task_force`，HTTP 入口为 `/swarm/runs`），事件摘要与证据链接自动注入 user_vars，无需复制粘贴。
- 四角色链式执行（详见 3.2），run 过程在页面内通过现有 swarm SSE 流式可见（角色状态、上游产出）；前端复用运行页/运行时菜单的既有事件协议，不新建推送通道。
- live 报告固定章节：①事件确认与定义（事实、时间线、信源可靠性声明）②情景树（基准/恶化/尾部三情景，各赋概率与持续时间假设）③传导链分析（至少两层：直接敞口 → 二阶/三阶传导，如农产品减产→食品通胀→货币政策约束→利率与成长股估值）④跨资产/行业影响矩阵（方向 × 幅度档 <3%/3–10%/>10% × 置信度 × 显化时间窗）⑤A股受益/受损板块与标的线索（含逻辑，不构成投资建议声明）⑥未来 3–6 个月催化日历与可跟踪领先指标 ⑦反方观点与证伪条件（Devil's Advocate）。
- 报告完成后落 `event_report`，事件详情页与 `/reports` 均可查看；支持从报告中的标的一键跳转关注列表（仅跳转，不自动加自选）。

#### Story 6：历史事件复盘报告（retrospective）

> 作为用户，我希望对过去错过的大机会（新冠、AI、俄乌战争）各出一份复盘报告：当时的早期信号是什么、各类资产实际怎么走、哪些机会没抓住、如果重演我该怎么办。

**验收标准：**

- Task Force 页提供"历史复盘"入口，可从内置历史事件清单选择（MVP：新冠疫情 / AI 产业浪潮 / 俄乌战争）或自定义事件名与时间区间；模式 `retrospective` 走同一预设、不同提示词分支。
- retrospective 报告固定章节：①事件分期时间线（酝酿/爆发/扩散/消退各阶段日期）②**关键早期信号复盘**：列出每个阶段"当时公开可知"的信号与日期、为何容易被忽略 ③各阶段跨资产真实表现（指数/行业/商品/汇率，区间涨跌幅，数据由 `get_market_data` 实取并标注数据源与区间）④传导链回顾（实际发生 vs 当时市场共识）⑤**没抓住的机会清单**：代表性受益标的/赛道、启动时点、当时的可观察信号、阶段最大涨幅 ⑥可复用早期信号 checklist（迁移到下一次同类事件的观察清单）⑦"若重演"应对预案（三情景 + 触发指标 + 应对动作）。
- 历史类比与异常收益必须调用 `src.quantlib.eventstudy.event_study` 计算（CAR/CAAR、BMP p 值、样本量、dropped 数均须披露），样本不足 5 个时只列个体 CAR 并声明样本不足；规则与现有 `event_driven_task_force.yaml` 第 4 节的约束逐字对齐，禁止手算/编造。
- MVP 验收：新冠、AI、俄乌三份报告均可端到端生成并归档；每份报告字数与章节完整性有结构化校验（缺章节在报告列表标"不完整"）。

#### Story 7：每日定时扫描（v1.1 已实现）

> 作为用户，我希望不用手动点，系统每天凌晨自动扫描，早上打开页面就能看到当天最重要的少数几条大事。

**验收标准（已实现）：**

- 服务启动时注册轻量 asyncio 定时任务（`eventradar/scheduler.py`，与 paper scheduler 同范式，无新依赖），默认**每日 04:00（Asia/Shanghai）**自动执行一轮 scope=all 扫描，`trigger_type=scheduled`；锚点可由 `VIBE_EVENT_DAILY_SCAN_AT`（HH:MM）调整，`VIBE_EVENT_DAILY_SCAN_ENABLED=false` 可关闭；服务停机错过的锚点不补跑。
- 自动扫描同样走人工终态保护（Story 3）与全部门控规则，无特权通道；扫描进行中遇到锚点则跳过当日。
- 雷达事件流默认**只展示当日最重要的 5 条**（排序：已证实 > 核验中 > 争议 > 未证实 > 谣言，再按全新范式/已知升级、置信度、信源数、时间），提供"查看全部"切换。
- **临时数据语义（v1.2）**：雷达是每日工作台——未进入当日 Top5 的事件（含全部候选事件）不做长期保留，下一轮扫描开始前物理清除；Top5 事件在卡片上提供「保留入档案 / 丢弃」操作：丢弃即物理删除（事件、证据、时间线一并删除，不留痕、不进档案），保留则进入事件档案（见 Story 9）；当日 Top5 中未被显式处理的事件保留到下一轮扫描，仍未入榜且未保留则覆盖。
- 未读计数与 SSE 角标仍留待后续迭代。

#### Story 8：报告与事件的历史回看

> 作为用户，我希望事件和报告都能按时间回看：当时系统怎么报的、后来报告结论是什么。

**验收标准：**

- 事件流支持按时间/类型/区域/状态/新颖度筛选与关键词搜索；事件详情保留状态变更历史（时间线：创建、每次证据追加、每次状态变更及操作人=自动/人工）。
- 报告列表：标题、关联事件、模式（live/retrospective）、run 状态、创建时间、完整性标记；可查看 markdown 正文与对应 swarm run 的完整过程。
- 同一事件允许多次分析（如厄尔尼诺月度更新），报告按版本倒序排列。

#### Story 9：每日 Top5 沉淀进事件档案（v1.2）

> 作为用户，我希望每天雷达筛出的最重要几件事能沉淀成一份长期档案：哪天上榜、来自哪个源、这个月上榜了多少天，而不是第二天就被刷掉。

**验收标准：**

- `/event` 新增第三个 Tab「事件档案」，只保存用户在雷达 Top5 上点「保留入档案」的事件；雷达 Tab 上点「丢弃」的事件直接物理删除，不出现在档案中。
- 每轮 04:00 扫描后，系统把当日 Top5 写入"每日雷达事件"记录（`radar_daily_pick`：日期、位次、事件快照标题、来源通道）；事件连续/多日上榜时，每天一行计数、不重复建事件，通过匹配合并到同一档案事件。
- 档案列表每行展示：标题、**首次入榜日期**、最近入榜日期、**来源（首次/主要信源名与 T 级）**、当前核验状态、新颖度标签、近 30 天入榜日次数、已有报告数。
- 档案顶部提供「近 30 天上榜日次数榜单」：按日次数倒序展示上榜最多的事件（次数、首次/最近日期），点击进入事件详情。
- 筛选：核验状态（已证实/有争议/谣言/核验中）、新颖度（全新范式重大机会/已知升级/已知延续）、事件类型、关键词，**外加日期区间筛选**（按首次入榜或任意上榜日落区间）。

#### Story 10：待核验事件的日 / 周 / 月自动跟踪复核（v1.2）

> 作为用户，我希望进了档案但当时没证实的事，系统每天、每周、每月自动再去查一次真假，把结论填好；我自己也能随时手动刷新。

**验收标准：**

- 跟踪对象**仅限事件档案中处于 verifying/unverified/disputed 的事件**；雷达 Tab 的临时事件一律不跟踪（非 Top5 下轮直接覆盖）。事件一旦到终态（confirmed/rumor/dismissed）自动复查停止。
- 三个定时锚点（Asia/Shanghai，`eventradar/scheduler.py` 内新增跟踪任务）：**每日 05:00 → 写"日复核"；每周一 05:00 → 写"周复核"；每月 1 日 05:00 → 写"月复核"**。复查动作：重新拉取两条专业电讯 + 针对事件实体检索增量证据，按既有核验状态机（独立信源/T 级/一致性/置信度）自动判定真假。
- 每次复查在事件详情与档案行可见三个字段：**日复核 / 周复核 / 月复核**，各含结论（true 证实 / false 证伪 / unverified 仍无定论）、一句话依据、复查时间；复查使状态机达到迁移条件时同步更新 `verify_status` 并在时间线留痕（actor=system-daily/weekly/monthly）。
- 事件详情提供「立即复查」手动按钮：当场执行同样的复查流程，**结果直接写入并覆盖"月复核"字段**（记录 `actor=manual` 与实际执行时间）。
- 复查所需的 LLM/采集失败不覆盖既有结论，只在该字段记 error 与时间，下一锚点重试。

#### Story 11：档案事件下的报告挂载、再发起与 live 分析（v1.2）

> 作为用户，我希望在一个事件下面看到它所有的分析报告、能重新出一份；已经证实的事件可以直接发起当下影响分析。

**验收标准：**

- 事件档案详情页展示该事件下全部 Task Force 报告（标题、模式、生成时间、状态、预期结果摘要），可打开正文；提供「再次发起分析」按钮（默认 live，带入最新证据链），历史报告不被覆盖、按版本倒序。
- 档案中**已证实**事件显示「发起当下影响分析（live）」主按钮；待核验事件该按钮置灰并提示先完成核验。
- 从档案发起 live 不受"近 7 天"限制（该限制只存在于 Task Force Tab，见 Story 12）。

#### Story 12：Task Force Tab 的 7 天窗口与报告列表字段（v1.2）

> 作为用户，我希望在 Task Force 页只快速分析最近一周新证实的大事；报告列表不用点开就能看到生成时间、预期结果和指导建议。

**验收标准：**

- Task Force Tab 的"从雷达事件发起"列表只包含**已证实且最近入榜/更新时间在近 7 天内**的事件；超出 7 天的事件不在此出现，页面提示"请到事件档案对应事件下发起"。
- 报告列表每行展示：**标题、生成时间（完成时间优先，未完成显示开始时间）、模式、状态、预期结果（expected_outcome）、指导建议（guidance 摘要）**；后两者由策略师报告末尾的机器可读块（`预期结果` / `指导建议` 结构化字段）解析落库，解析失败时回退为对应章节首句并在列表标注。
- 自定义历史复盘（新冠/AI/俄乌等）入口保留，不受 7 天窗口限制。

#### Story 13：报告的取消、删除、对比、重试（v1.2）

> 作为用户，我希望像管理下载任务一样管理分析报告：跑错了能取消、不要了能删、几份报告能勾选并排看、失败了能重跑。

**验收标准：**

- 运行中（pending/running）的报告提供「取消」：调用 swarm run 取消，报告置 canceled；已结束的报告不显示取消。
- 任一报告提供「删除」：二次确认后删除报告记录（不影响事件与证据）；删除后列表即时刷新。
- 报告列表支持勾选（checkbox）多篇后「对比查看」：在同页分栏并排展示原文 markdown，**不做任何 AI 归纳/对比生成**，仅提供分栏滚动与章节锚点同步；对比状态在 URL/本地状态中可关闭。
- failed/incomplete 的报告提供「重试」：以相同模式、市场、时间跨度与事件上下文重新发起一个 run，生成新报告版本，旧失败记录保留可查。

#### Story 14：报告的事后复盘与准确性评价（v1.2）

> 作为用户，几个月或几年后我想回来给当时的报告打分：预测对了没有、偏差在哪，形成可迭代的分析资产。

**验收标准：**

- 每份已完成报告提供「事后评价」入口：可填评价时间（默认当天）、准确性评级（如 准确 / 部分准确 / 偏离 / 完全错误）、实际走势与预期的偏差说明、经验教训；评价长期保存在报告上并在列表显示评级。
- 评价为用户人工填写；可附"对照区间"（起止日期）与关联的后续报告，系统不自动判定对错（自动后验留待 v2.0）。
- retrospective 复盘报告同样可被评价（评价其复盘结论对后续投资是否有用），与 live 报告使用同一评价结构。

### 2.4 Non-Goals（本期明确不做）

- 不做新闻/事件驱动的自动下单或模拟仓自动调仓；报告中的标的仅为研究线索。
- 不做秒级/分钟级实时推送；节奏为每日 04:00 扫描 + 05:00 复核（另支持手动触发）。
- 不接入付费数据源（Bloomberg/RavenPack/万得等）；仅用财联社/华尔街见闻免费官方接口与既有网页深读能力。
- 不对雷达 Tab 的临时事件（非每日 Top5、未保留）做真实性跟踪或长期存储；跟踪只发生在事件档案内。
- 报告对比不做 AI 自动归纳，仅提供多篇并排的人工对比视图。
- 不做面向社交媒体（X/微博/股吧）的实时舆情流式采集（现有 sentiment 团队预设与未来 social_alpha 方向另议）。
- 不做多用户、权限体系与事件库云同步；本地单用户，事件库存本地 DuckDB。
- 不改动既有个股公司事件预设 `event_driven_task_force.yaml` 及其使用入口。
- 不新增 LLM 模型；全部智能能力通过现有 LLM 网关与既有模型完成。
- 不做移动端与桌面端专门适配（沿用现有 Web/SPA 渠道）。

---

## 3. AI System Requirements

### 3.1 既有 AI 能力的消费（无新增模型）

- **新闻采集（v1.1 起）**：雷达主通道为内置双源直连——财联社深度（cls.cn v3 depth，RSSHub 同款 SHA1→MD5 签名）与华尔街见闻（api-one lives/information-flow），实现位于 `agent/src/eventradar/sources.py`，零新增运行时依赖；仅在 Task Force 角色需要深读正文时使用 `read_url`（`agent/src/tools/web_reader_tool.py`）。`get_stock_news` / `web_search` 不再作为雷达采集通道（保留给其他既有模块）。
- **LLM 结构化补全**：管道中的事件抽取、跨源一致性判定、新颖度/范式评分复用现有 LLM 客户端的单次结构化输出能力（与 macro/sentiment 分析同一网关），强制 JSON schema 输出与 schema 校验重试；不新接模型供应商。具体客户端入口实现时与 macro 模块对齐，禁止在 config 层之外读环境变量（受 `tools/ci_env_var_gate.py` 约束）。
- **行情与事件研究**：`get_market_data` 取历史 K 线；`src.quantlib.eventstudy.event_study` 做 CAR/CAAR 与 BMP/Patell 检验。
- **Swarm 编排**：复用 `/swarm/runs`（preset_name + user_vars）、run 历史、取消能力与 SSE（`agent/src/api/swarm_routes.py`），不新建编排设施；v1.2 的报告取消/重试直接复用 run 取消与重新 start_run。
- **预设资产借鉴**：宏观框架吸收 `geopolitical_war_room.yaml`（GPR 指数、六大热点评级、历史类比）与 `sentiment_intelligence_team.yaml`（新闻情报官、政策周期与叙事框架）的成熟提示词。

### 3.2 新增 AI 资产生成

**（1）skill pack：`breaking-news-radar`（经 `agent/src/swarm/skill_catalog.py` 注册到 event_driven 分类）**

内容包含：宏观事件十分类分类法与判定边界、信源四级分级表与转载识别规则、真实性核验 rubric（独立性/一致性/辟谣识别）、新颖度三分类定义、全新范式四要素评分卡（1–5 分锚点描述）、长期赛道库与映射规则、固定 JSON 输出 schema（新建/合并动作、event_id、字段清单）、强制工作流（先 `event_lookup` 判重 → 再抽取 → 后判定）。

**（1b）采集 skill pack（v1.1 已内置，同样注册 event_driven）**：`investment-news-collector`（SkillHub 社区 skill 本地化：财联社深度双栏、标题优先事件评分、零 Token 降级）与 `wallstreetcn-news`（华尔街见闻 lives/深读/历史查询使用规则、只读与反刷屏约束）；两者的数据获取逻辑实现在 `sources.py`，skill 文档作为智能体使用规范。

**（1c）v1.2 新增智能行为**：① 跟踪复核器（tracking）——对档案待核验事件做增量证据拉取 + 同一核验 rubric 的自动真假判定，输出 `{verdict, reason, checked_at}`；② 策略师报告末尾追加机器可读块 `EXPECTED_OUTCOME` / `GUIDANCE`（单行/短段，供列表解析；缺块时按章节首句回退）；③ 事后评价为纯人工结构化输入，不调用 LLM 自动打分。

**（2）工具：`event_lookup`（新增 BaseTool，注册到工具注册表）**

入参：实体关键词、事件类型（可空）、时间窗小时数、可选 SimHash 指纹；出参：匹配事件列表（event_id、标题、状态、新颖度、首发/最近时间、证据数、相似度）。供扫描员智能体与 Task Force 角色判重、查相似历史事件。工具只读本地 DuckDB，禁网。

**（3）swarm 预设：`agent/src/swarm/presets/macro_event_task_force.yaml`（新建，不改旧预设）**

| 角色 | 职责与关键约束 |
| --- | --- |
| `event_scout` 事件情报官 | 复核输入事件事实、补全时间线、逐条声明信源层级与可靠性；retrospective 模式下列出事件分期与各阶段关键日期来源；工具：`event_lookup`、`get_stock_news`、`web_search`、`read_url`、`load_skill` |
| `impact_analyst` 影响分析师 | 三情景概率树；至少两层传导链；跨资产/行业影响矩阵（方向/幅度档/置信度/时间窗）；工具：`get_market_data`、`get_stock_news`、`read_url`、`load_skill`、`event_lookup`、`bash` |
| `historical_analyst` 历史类比师 | ≥2 个历史类比；CAR/CAAR 必须经 `bash` 调用 `src.quantlib.eventstudy.event_study`，披露模型、BMP p 值、样本量、dropped、重叠日期；样本 <5 只列个体 CAR；retrospective 模式负责实取各资产真实走势；规则与现有公司事件预设第 4 节同等严格 |
| `strategist` 机会策略师 | 受益/受损赛道与标的线索、催化日历、领先指标触发器、反方观点与证伪条件；retrospective 模式输出"没抓住的机会清单"与可复用 checklist、"若重演"预案；工具：`load_skill`、`get_market_data`、`backtest`、`read_url` |

链式 tasks：`task-scout → task-impact → task-history → task-strategy`，后一任务通过 `input_from` 获得全部上游产出（DAG 校验复用现有预设校验，禁止环/孤儿节点）。

变量：`event`（事件描述或 event_id，必填）、`mode`（live/retrospective，必填，默认 live）、`market`（默认"A股+全球"）、`time_horizon`（live 默认 3–6 个月；retrospective 为事件起止区间）。

### 3.3 Evaluation Strategy

- 雷达质量：`agent/tests/fixtures/news_cases/` 维护固定样本集（同一事件多源改写对、谣言-辟谣对、范式事件/普通事件对、中英双语样本），离线评测判重准确率/误合并率、状态判定准确率、范式分类准确率，纳入 `make test`；样本集随误判案例持续扩充。
- 报告质量：报告为结构化 markdown（固定章节标题），先做章节完整性与数据引用合规的程序化校验（凡数字须可溯源到工具输出）；人工对 MVP 四份报告做评审归档。v2.0 再考虑接入现有 eval harness 做离线 rubric 评分。

---

## 4. Technical Specifications

### 4.1 Architecture Overview

```
事件分析 /event
 EventAnalysis.tsx
  ├─ Tab1 BreakingRadar（当日 Top5 / 保留-丢弃 / 扫描批次；非 Top5 临时数据）
  ├─ Tab2 EventArchive（v1.2：档案列表/30天榜单/筛选+日期/详情含日周月复核与报告）
  └─ Tab3 TaskForce（近7天已证实事件发起 / 报告列表[时间·预期·建议] / 对比 / 评价）
      │ lib/api.ts 封装 /events/*；轮询（扫描 3s、报告 5s）
      ▼
api_server.py（仅注册新路由，不改旧逻辑）
      │
src/api/event_routes.py（前缀 /events，无 /api）
      │
src/eventradar/
  ├─ service.py    扫描编排、状态机、人工动作、Top5 快照、保留/丢弃、发起 run、报告归档
  ├─ sources.py    专业双源（财联社深度签名 + 华尔街见闻官方 JSON），四通道各 head-5（v1.2）
  ├─ scheduler.py  04:00 每日扫描；05:00 日/周一05:00 周/1日05:00 月 跟踪复核（v1.2）
  ├─ tracking.py   v1.2：档案待核验事件增量取证 + 自动真假判定 + 手动复查
  ├─ dedup.py      SimHash 指纹 + 实体×类型×时间窗聚类（合并口径保持宽松）
  ├─ extract.py    LLM 结构化抽取/一致性/范式评分（JSON schema 强制，无 key 启发式降级）
  ├─ scoring.py    信源分级表、置信度与状态升级规则、范式四要素评分
  ├─ db.py         幂等建表 DDL + DAO（短连接，沿用 watchlist db 模式）
  └─ report.py     报告章节校验、expected_outcome/guidance 解析、事后评价结构（v1.2）
      │
      ├─ DuckDB 市场库（get_market_db_path，同库不同表）
      │   radar_scan_run / radar_event / radar_evidence / radar_event_timeline
      │   radar_daily_pick(v1.2) / event_report(+复核与评价字段 v1.2)
      └─ Swarm runtime（既有）运行 macro_event_task_force 预设（取消/重试复用 run 能力）
```

**隔离原则**：新功能落在新包 `src/eventradar/`、新路由 `src/api/event_routes.py`、新预设、新 skill、新工具；对既有代码的触碰仅限：导航数组、路由表、i18n 文案、`api_server.py` 一行路由注册、工具注册表一行注册、skill_catalog 一行分类注册。不新增反向层依赖（受 `scripts/lint-deps` 与 grandfathered 边表约束）。

### 4.2 数据流

1. **扫描（手动或每日 04:00）**：`POST /events/scan {scope}` → 建 `radar_scan_run`（running）→ 四通道采集、每通道编辑部序 head-5（≤20 候选，图表/垃圾条目在采集端过滤，单源失败隔离）→ SimHash 近重过滤 → 宽松聚类归并 → LLM 批量结构化抽取（无 key 走启发式降级）→ 核验评分定初始状态 → 范式评分与赛道映射 → **清理上一轮临时事件（未入档、非当日 Top5）** → 写 `radar_event`/`radar_evidence`（已入档事件与人工终态事件跳过删除/改写）→ 生成当日 Top5 快照写 `radar_daily_pick`（档案事件再次上榜则 upsert 计数行）→ 批次置 completed，前端轮询刷新。
2. **保留 / 丢弃（v1.2）**：Top5 卡片「保留入档案」→ 事件置 `archived=true` 并长期保留、参与后续日/周/月跟踪；「丢弃」→ 同事务物理删除事件与其证据/时间线/快照引用，不写档案。
3. **后续扫描合并**：证据按 URL 防重追加；信源数与一致性满足升级条件时按状态机自动升级；范式分随证据量与热度重算，升级留痕。
4. **人工复核**：`POST /events/events/{id}/verify {action, note}` → 写状态历史；终态对后续自动扫描生效。
5. **跟踪复核（v1.2）**：05:00 三个锚点由 `scheduler.py` 调 `tracking.py`，仅处理 `archived=true` 且非终态事件 → 增量采集 + 判定 → 写 review_daily/weekly/monthly（JSON：verdict/reason/checked_at/actor），满足迁移条件时更新 `verify_status`；手动「立即复查」走同一流程但覆盖 review_monthly。
6. **发起分析**：档案/近 7 天已证实事件 → `POST /events/events/{id}/analyze`；自定义历史复盘 → `POST /events/analyze`；组装 user_vars（事件摘要 + 证据 URL + 模式）→ swarm `start_run("macro_event_task_force", …)` → 落 pending `event_report`。取消走 swarm run 取消、重试以相同入参新建 run。
7. **报告归档与解析（v1.2 增强）**：run 完成后拉取 markdown，章节校验 + 解析尾部 `EXPECTED_OUTCOME`/`GUIDANCE` 机器可读块落列表字段；事后评价由 `POST /events/reports/{id}/evaluation` 写入评价结构；删除为报告记录级硬删除。

### 4.3 数据模型（DuckDB 新表，`CREATE TABLE IF NOT EXISTS` 幂等建表）

```sql
-- 扫描批次
CREATE TABLE radar_scan_run (
    id                VARCHAR PRIMARY KEY,       -- uuid
    scope             VARCHAR NOT NULL,          -- china | global | all
    trigger_type      VARCHAR NOT NULL,          -- manual | scheduled
    status            VARCHAR NOT NULL,          -- running | completed | partial | failed
    source_status     VARCHAR,                   -- JSON: 各数据源 ok/failed/条数
    candidates        INTEGER DEFAULT 0,         -- 原始候选
    duplicates        INTEGER DEFAULT 0,         -- 近重/聚类合并数
    new_events        INTEGER DEFAULT 0,
    escalated         INTEGER DEFAULT 0,         -- 状态升级数
    to_review         INTEGER DEFAULT 0,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP
);

-- 事件（一个事件 = 一个聚类）
CREATE TABLE radar_event (
    event_id          VARCHAR PRIMARY KEY,       -- 聚类指纹派生 uuid
    title             VARCHAR NOT NULL,
    event_type        VARCHAR NOT NULL,          -- 十分类之一
    entities          VARCHAR,                   -- JSON 数组：国家/机构/公司/商品
    regions           VARCHAR,                   -- JSON 数组
    summary           VARCHAR,
    impact_direction  VARCHAR,                   -- positive | negative | uncertain
    affected_assets   VARCHAR,                   -- JSON：资产/行业及方向
    cluster_key       VARCHAR NOT NULL,          -- 主实体|类型|窗口键
    simhash           VARCHAR,                   -- 代表性标题指纹(hex)
    novelty_class     VARCHAR NOT NULL,          -- known_continuation | known_escalation | new_paradigm
    paradigm_scores   VARCHAR,                   -- JSON: {policy_duration,invest_cycle,chain_breadth,narrative_heat} 各1-5
    paradigm_total    INTEGER,                   -- 0-20
    long_term_themes  VARCHAR,                   -- JSON：命中的长期赛道
    impact_level      VARCHAR,                   -- high | medium | low
    verify_status     VARCHAR NOT NULL,          -- unverified | verifying | confirmed | disputed | rumor | dismissed
    confidence        DOUBLE,                    -- 0-1
    source_count      INTEGER DEFAULT 0,
    first_seen_at     TIMESTAMP NOT NULL,
    last_update_at    TIMESTAMP NOT NULL,
    locked_by_human   BOOLEAN DEFAULT false,     -- 人工终态锁定
    related_event_ids VARCHAR,                   -- JSON：同实体同类型的历史/关联事件
    -- v1.2 事件档案
    archived          BOOLEAN DEFAULT false,     -- 用户「保留入档案」后长期保留
    archived_at       TIMESTAMP,
    review_daily      VARCHAR,   -- JSON: {verdict,reason,checked_at,actor} 日复核
    review_weekly     VARCHAR,   -- JSON：周复核（每周一 05:00）
    review_monthly    VARCHAR,   -- JSON：月复核（每月1日 05:00；手动复查也覆盖此字段）
    UNIQUE(cluster_key)
);
CREATE INDEX idx_radar_event_status ON radar_event(verify_status, last_update_at);
CREATE INDEX idx_radar_event_type   ON radar_event(event_type, first_seen_at);
CREATE INDEX idx_radar_event_archived ON radar_event(archived, verify_status, last_update_at);

-- 证据（一篇报道一行）
CREATE TABLE radar_evidence (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR NOT NULL,
    url               VARCHAR NOT NULL,
    source_name       VARCHAR,
    source_tier       INTEGER,                   -- 1-4
    title             VARCHAR,
    snippet           VARCHAR,
    published_at      TIMESTAMP,
    fetched_at        TIMESTAMP NOT NULL,
    is_independent    BOOLEAN DEFAULT true,      -- 转载/同集团标记 false
    fetch_scan_id     VARCHAR,
    UNIQUE(url),
    FOREIGN KEY(event_id) REFERENCES radar_event(event_id)
);
CREATE INDEX idx_radar_evidence_event ON radar_evidence(event_id, source_tier);

-- 事件状态变更历史（自动/人工均留痕）
CREATE TABLE radar_event_timeline (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR NOT NULL,
    change_type       VARCHAR NOT NULL,          -- created | evidence_added | status_changed | novelty_changed | human_action
    from_value        VARCHAR,
    to_value          VARCHAR,
    actor             VARCHAR,                   -- system | 人工操作来源
    note              VARCHAR,
    created_at        TIMESTAMP NOT NULL
);

-- 每日 Top5 快照（v1.2；事件档案的入榜计数依据）
CREATE TABLE radar_daily_pick (
    id                VARCHAR PRIMARY KEY,
    pick_date         DATE NOT NULL,             -- 雷达日期（Asia/Shanghai）
    rank_position     INTEGER NOT NULL,          -- 1-5
    event_id          VARCHAR,                   -- 可空：事件被丢弃删除后快照行保留聚合价值
    title_snapshot    VARCHAR NOT NULL,          -- 当日标题快照
    source_channels   VARCHAR,                   -- JSON：当日命中的来源通道，如 ["财联社·头条","华尔街见闻·7x24"]
    scan_id           VARCHAR,
    created_at        TIMESTAMP NOT NULL,
    UNIQUE(pick_date, rank_position)
);
CREATE INDEX idx_daily_pick_event ON radar_daily_pick(event_id, pick_date);
CREATE INDEX idx_daily_pick_date  ON radar_daily_pick(pick_date);
-- 注：radar_daily_pick.event_id 不加外键约束；事件被丢弃物理删除后快照行保留
-- （event_id 置空），榜单的历史聚合口径不被删除操作破坏。

-- Task Force 报告
CREATE TABLE event_report (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR,                   -- 复盘自定义事件可空
    run_id            VARCHAR NOT NULL,
    mode              VARCHAR NOT NULL,          -- live | retrospective
    title             VARCHAR NOT NULL,
    market            VARCHAR,
    time_horizon      VARCHAR,
    status            VARCHAR NOT NULL,          -- pending | running | completed | incomplete | failed | canceled
    markdown          VARCHAR,
    sections_present  VARCHAR,                   -- JSON：固定章节存在性
    data_sources      VARCHAR,                   -- JSON：引用到的工具取数记录
    expected_outcome  VARCHAR,                   -- v1.2：策略师机器可读块解析（列表展示）
    guidance          VARCHAR,                   -- v1.2：指导建议摘要
    eval_rating       VARCHAR,                   -- v1.2：事后评价 accurate | partial | off | wrong
    eval_note         VARCHAR,                   -- v1.2：偏差说明与经验教训
    eval_period_start DATE,                      -- v1.2：对照区间起
    eval_period_end   DATE,                      -- v1.2：对照区间止
    eval_related_report_id VARCHAR,              -- v1.2：关联的后续报告
    evaluated_at      TIMESTAMP,                 -- v1.2：评价时间
    created_at        TIMESTAMP NOT NULL,
    completed_at      TIMESTAMP,
    canceled_at       TIMESTAMP
);
CREATE INDEX idx_event_report_event ON event_report(event_id, created_at);
```

- 写入均走短连接单事务（沿用 `watchlist/db.py` 模式），扫描批次与证据写入分批提交，避免长事务。
- `cluster_key` 唯一约束兜底防重复事件；LLM 判重结果与服务端指纹聚类不一致时以服务端聚类为准并记日志（供样本集回溯）。
- **v1.2 存量库升级**：`radar_event` 新列与 `event_report` 新列经启动时幂等 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 补齐（DuckDB 支持），`radar_daily_pick` 随 `initialize_schema` 新建；升级同时一次性物理清理 `archived=false` 的存量雷达事件（v1.1 临时数据语义首次生效）。

### 4.4 核验与评分规则（默认参数，集中配置）

| 规则 | 默认值 |
| --- | --- |
| 聚类时间窗 | 72 小时 |
| SimHash 海明距离阈值 | 3（64 位指纹） |
| 升"已证实"最少独立信源数 | 2，且至少 1 个 T1/T2 |
| 综合置信度确认阈值 | 0.70 |
| 全新范式总分阈值 | 15 / 20（四要素各 1–5） |
| 单轮入管候选上限 / 每通道头部条数（v1.2） | 20 / 5（四通道：财联社头条、财联社环球、见闻快讯、见闻深读；不足按实际） |
| 每日雷达 Top 展示/快照条数 | 5（写 `radar_daily_pick`） |
| Task Force Tab 可发起窗口（v1.2） | 已证实且最近更新 7 天内；更早走事件档案 |
| 入榜日次数统计窗口（v1.2） | 近 30 天（自然日，Asia/Shanghai） |
| 证据摘要长度上限 | 280 字符（与新闻工具一致） |

- 综合置信度 = 信源层级分（加权 0.4）+ 独立信源数（0.25）+ 跨源事实一致性 LLM 分（0.35），权重在 `scoring.py` 集中常量化。
- 状态机只允许相邻/规定路径转移；`dismissed/rumor/人工 confirmed` 为锁定态，自动扫描仅追加证据与 timeline 提示。

### 4.5 配置项（走统一 env schema）

在 `agent/src/config/env_schema.py` 既有模式下新增：

- `VIBE_EVENT_RADAR_ENABLED`（默认 true；false 时仅可手动扫描，定时任务不注册）
- `VIBE_EVENT_DEDUP_WINDOW_HOURS`（默认 72）
- `VIBE_EVENT_VERIFY_MIN_SOURCES`（默认 2）、`VIBE_EVENT_CONFIRM_THRESHOLD`（0.70）
- `VIBE_EVENT_PARADIGM_THRESHOLD`（默认 15）
- `VIBE_EVENT_DAILY_SCAN_ENABLED`（默认 true）、`VIBE_EVENT_DAILY_SCAN_AT`（默认 `04:00`，Asia/Shanghai 每日扫描锚点，格式 HH:MM）
- `VIBE_EVENT_REVIEW_ENABLED`（v1.2，默认 true）、`VIBE_EVENT_REVIEW_AT`（默认 `05:00`，日/周一/月首三个复核共用锚点，格式 HH:MM）；周复核固定周一、月复核固定 1 日
- `VIBE_EVENT_FEED_HEAD_N`（v1.2，默认 5，每通道取头部条数）、`VIBE_EVENT_TOP_N`（默认 5，每日 Top 快照条数）、`VIBE_EVENT_TF_FRESH_DAYS`（默认 7，Task Force Tab 可发起窗口天数）
- 信源层级表与长期赛道库存放于 `src/eventradar/` 内置默认（JSON 常规模板，不读外部文件路径），本期不暴露 env；v2.0 评估用户可编辑。
- 旧的 `VIBE_EVENT_SCAN_INTERVAL_MINUTES`（30 分钟轮扫）已随 v1.1 每日锚点方案废弃。

### 4.6 API（新路由 `src/api/event_routes.py`，前缀 `/events`）

> 实现注记：按代码库既有约定（`/watch`、`/paper`、`/options`、`/swarm`
> 等均无 `/api` 前缀），实际挂载路径如下表；扫描/报告刷新采用前端轮询
>（扫描运行中 3s、报告运行中 5s），雷达专属 SSE 事件类型留待后续迭代。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/events/events` | 雷达事件流（临时视图），支持 status/novelty/type/region/keyword/limit |
| GET | `/events/daily-picks` | v1.2 每日 Top5 快照，参数 `date` 或日期区间 |
| POST | `/events/scan` | body `{scope}`；手动触发一轮扫描（异步，前端轮询） |
| GET | `/events/scan-runs` | 最近扫描批次与各源状态 |
| GET | `/events/events/{id}` | 事件详情：字段 + 证据链 + 时间线 + 日/周/月复核 + 报告列表 |
| POST | `/events/events/{id}/verify` | body `{action: confirm\|flag_dispute\|mark_rumor\|dismiss, note}` |
| POST | `/events/events/{id}/archive` | v1.2：保留入档案（`archived=true`）/取消保留 |
| DELETE | `/events/events/{id}` | v1.2：丢弃——物理删除事件及证据/时间线（不进档案） |
| GET | `/events/archive` | v1.2 档案列表：status/novelty/type/keyword/日期区间；返回首末入榜日期、近 30 天日次数、报告数 |
| GET | `/events/archive/leaderboard` | v1.2 近 30 天入榜日次数榜单（可配 window_days） |
| POST | `/events/events/{id}/recheck` | v1.2 手动立即复查，结果写/覆盖月复核字段 |
| POST | `/events/events/{id}/analyze` | body `{mode, market, time_horizon}`；已证实事件发起 run |
| POST | `/events/analyze` | 自定义/历史事件发起复盘：`{event_title, event_period, mode:retrospective, market}` |
| GET | `/events/reports` | 报告列表（模式/状态筛选），含生成时间、expected_outcome、guidance、评价 |
| GET | `/events/reports/{id}` | 报告 markdown、章节完整性、run 链接、评价 |
| POST | `/events/reports/{id}/cancel` | v1.2 取消运行中 run，报告置 canceled |
| DELETE | `/events/reports/{id}` | v1.2 删除报告记录 |
| POST | `/events/reports/{id}/retry` | v1.2 以原参数重新发起 run，生成新版本报告 |
| PUT | `/events/reports/{id}/evaluation` | v1.2 提交/更新事后评价：`{rating, note, period_start, period_end, related_report_id}`（勾选对比为纯前端分栏，无后端接口） |

- 认证/监听面与现有路由注册方式一致，loopback 默认绑定，不新增外发通道。
- 4xx 覆盖：未证实事件禁止分析（409）、事件不存在（404）、非法状态转移（400）、扫描进行中重复提交（409）、非法枚举（422）、非档案事件不允许复查/未运行中报告不可取消（409）。
- 扫描中 3s 轮询批次、报告运行中 5s 轮询列表；SSE 事件类型继续留待后续迭代。

### 4.7 后台调度

全部锚点在 `eventradar/scheduler.py` 的 lifespan asyncio 任务中实现（与 paper scheduler 同范式，无新依赖；错过不补跑、遇忙跳过），时区固定 Asia/Shanghai：

| 锚点 | 动作 | 状态 |
| --- | --- | --- |
| 每日 04:00（`VIBE_EVENT_DAILY_SCAN_AT`） | 全量扫描 + 临时事件清理 + 当日 Top5 快照 | v1.1 已实现（快照/清理 v1.2 补） |
| 每日 05:00（`VIBE_EVENT_REVIEW_AT`） | 档案待核验事件**日复核** | v1.2 |
| 每周一 05:00 | 同上并写**周复核** | v1.2 |
| 每月 1 日 05:00 | 同上并写**月复核** | v1.2 |

- 周一/月首的 05:00 同时完成当日日复核与周/月复核（各写各的字段，不互相覆盖）。
- 复查器仅选 `archived=true` 且状态 ∈ {unverified, verifying, disputed} 的事件；事件到终态即自然退出复查集合。
- 接入 `/scheduled` 页面做可视化频率管理仍留待后续；`VIBE_EVENT_REVIEW_ENABLED=false` 可整体关闭复查任务。

### 4.8 前端

- 导航与路由：`Layout.tsx` NAV 新增 `/event`（Radar/Newspaper 图标，置于宏观分析之后）；`router.tsx` 新增 `EventAnalysis` 路由；i18n 补 `layout.eventAnalysis` 及中英文案。
- 页面 `pages/EventAnalysis.tsx`，v1.2 起三个 Tab：
  - **突发雷达**：扫描操作区（范围/立即扫描/批次状态）→ 当日 Top5 卡片（每张含「保留入档案」「丢弃」按钮、丢弃需二次确认）→ 「查看全部」临时事件视图；详情含证据链、时间线、人工复核按钮。
  - **事件档案（v1.2）**：顶部近 30 天入榜榜单 + 筛选器条（状态/新颖度/类型/关键词/**日期区间**）；档案行展示首末入榜日期、来源、日次数；详情含日/周/月复核三字段（结论徽标+依据+时间）、「立即复查」按钮、该事件全部报告列表与「再次发起分析」、已证实事件的「发起当下影响分析（live）」主按钮。
  - **Task Force**：近 7 天已证实事件快捷发起区（超期提示去档案）+ 历史复盘模板（新冠/AI/俄乌/自定义）；报告列表行含勾选框、标题、生成时间、模式、状态、预期结果、指导建议摘要、操作（打开/取消/重试/删除/评价）；「对比查看」为纯前端分栏 markdown 视图（同步滚动、章节锚点，不调用 AI）；报告详情含事后评价表单（评级/偏差/对照区间）。
- 全部请求封装进 `frontend/src/lib/api.ts`；不引入 react-query 等新数据层，沿用 Watchlist/Swarm 页面既有模式；列表更新沿用轮询（扫描 3s、运行中报告 5s）。

### 4.9 Security & Privacy

- 纯本地功能：新闻读取全部经既有工具与节流客户端，不新增外发数据通道；事件库仅存本地 DuckDB。
- `read_url` 内容经既有 `src.security.scanner` 安全提示链路；事件证据 URL 仅存链接与摘要，不落地整页内容。
- LLM 仅发送新闻标题/摘要文本，不携带本地持仓、凭证等个人数据。
- 不新增 shell/MCP 工具对外暴露；Task Force 角色的 bash 能力约束与现有预设一致（仅量化分析用途），不触碰 live/order 门禁。

### 4.10 测试策略

- 单元测试（`agent/tests/`，pytest，全部网络 mock、禁网，fixture 置于 `tests/fixtures/news_cases/`）：
  - SimHash 与聚类：换词改写合并、跨类型不合并、窗口过期新建、URL 证据防重；
  - 信源分级与状态机：单源不可升已证实、转载不计独立信源、T1 辟谣转谣言、非法转移拦截、人工锁定后自动扫描不改写；
  - 置信度计算与阈值边界；范式四要素缺项/低于阈值不得打 new_paradigm（schema 校验）；
  - `event_lookup` 工具检索准确性与只读性；
  - 扫描服务：数据源部分失败隔离、并发扫描 409、批次计数正确、Top5 快照与临时事件清理正确；
  - 报告归档：章节完整性判定、retrospective 数字无来源标记时判 incomplete；
  - 预设：`macro_event_task_force.yaml` 通过既有预设加载与 DAG 校验（无环/无孤儿/变量齐全）；
  - v1.2 采集收口：四通道各只入 head-5、总数 ≤ 20；`/charts/` 图表条目与垃圾条目被过滤；通道不足 5 条按实际；
  - v1.2 档案语义：保留置 archived 长期存活、丢弃级联物理删除、未入档临时事件在下一轮被清理、Top5 快照 upsert 与近 30 天日次数统计/榜单；
  - v1.2 跟踪复核：日/周一/月首锚点选择逻辑（日期判定纯函数可单测）、只复查档案非终态事件、复查结论写对应字段、手动复查覆盖月复核、采集失败不覆盖旧结论；
  - v1.2 报告：expected_outcome/guidance 机器块解析与回退、取消/删除/重试状态流转、7 天窗口过滤、评价写入与枚举校验。
- API 层测试参照 `agent/tests/test_portfolio_routes.py` 与 swarm routes 测试的既有模式。
- 前端 vitest：事件卡状态渲染与置灰（未证实禁止分析）、筛选器、保留/丢弃确认、档案榜单与日期筛选、报告勾选对比分栏、轮询数据合并到列表。
- 评测样本集纳入 `make test`，三项核心指标（判重准确率 ≥95%、谣言零误确认、范式分类）在样本集上回归。
- lint 门禁：新包遵守层级规则，不引入新反向边；config 外不读环境变量。

---

## 5. Risks & Roadmap

### 5.1 Technical Risks

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 免费官方接口限流/改版/图表类非文章条目混入 | 候选缺失或非新闻内容入库 | 每通道仅取头部 5 条降低调用量；URL 模式垃圾过滤（含 `/charts/`、行情页）；单源失败隔离；接口解析集中在 sources.py 便于随改版修复 |
| 头部 5 条截断漏报通道内第 6 条的重大新闻 | 当日漏事件 | 专业电讯本身经编辑部排序；72h 聚类窗 + 次日 04:00 复扫给二次入榜机会；事件档案的跟踪复核弥补；必要时调 `VIBE_EVENT_FEED_HEAD_N` |
| LLM 把谣言/单源消息误判为已证实 | 错误事件驱动后续分析 | 默认未证实；硬规则（≥2 独立信源含 T1/T2）先于 LLM；阈值门控；人工复核队列 + 档案日/周/月自动复查；样本集回归"零假确认" |
| 宽松合并把同主题不同事件并为一张卡 | 证据链混杂、Top5 虚高信源数 | 已明确接受（宁合勿漏）；配 LLM 后 merge/new 判定收紧；档案事件保留/丢弃由人最终把关；事后可拆分能力留待 v2.0 |
| 自动复查误改档案事件状态 | 长期记录被污染 | 复查沿用同一状态机硬门（单源不证实）；每次复查留 verdict/依据/时间；人工终态锁定优先；失败不覆盖旧结论 |
| 换词重写导致事件重复/误合并 | 事件流噪声或错误证据合并 | 双层判重（SimHash + 聚类键）+ 智能体 `event_lookup` + 服务端唯一键兜底；冲突时以服务端聚类为准并留日志 |
| 宏观影响分析主观性强、数字编造 | 报告可信度受损 | 固定章节 + 三情景概率 + 强制反方观点；历史数值强制走 event_study/get_market_data 并披露样本量与 p 值，规则对齐现有严格预设；报告完整性程序化校验 |
| LLM 结构化输出不稳定 | 管道中断/脏数据 | JSON schema 校验 + 限定重试次数；失败候选进复核队列而非丢弃；批次部分成功可交付 |
| 扫描与复查成本（LLM 调用量） | 费用上升 | 每日仅 1 次扫描、入管 ≤ 20 条；SimHash/聚类先于 LLM 粗筛；批量抽取；复查仅覆盖档案待核验事件且无新证据时只更新时间不调用判定 LLM |
| 与既有公司事件预设概念混淆 | 用户误用 | 命名隔离（macro_event_task_force）；菜单文案区分"宏观/突发"与 Swarm 工作室中的公司事件团队 |

### 5.2 Phased Rollout

**v1.0 MVP（已实现）**

- 菜单/路由/i18n；DuckDB 表（scan_run/event/evidence/timeline/report）
- `src/eventradar/` 包：多源采集、双层判重、结构化抽取、核验状态机、范式评分
- `breaking-news-radar` skill + `event_lookup` 工具 + `macro_event_task_force` 预设（四角色链，live/retrospective）
- 雷达前端（事件流/证据链/时间线/人工复核/手动扫描）、一键发起分析、报告列表与章节校验
- 固定评测样本集与单测；**演示产出：厄尔尼诺 live 报告 + 新冠/AI/俄乌三份复盘报告（需配置 LLM key 实跑）**

**v1.1（已实现）**

- 采集收敛为专业双源（investment-news-collector 财联社深度 + wallstreetcn-news 华尔街见闻官方接口），移除东财/DDG 检索矩阵
- 每日 04:00（Asia/Shanghai）自动扫描（env 可配可关）、雷达默认 Top5 重要度排序与前端切换
- 两个采集 skill 内置与注册、预设 scout 引用

**v1.2（本版，待实现）**

- 采集收口：四通道各 head-5、单轮 ≤20；过滤 `/charts/` 等非文章条目；合并口径维持宽松
- 每日 Top5 快照 `radar_daily_pick`；雷达卡「保留入档案 / 丢弃」（丢弃物理删除）；临时事件下轮覆盖
- 事件档案 Tab：档案列表、首末入榜日期与来源、近 30 天日次数与榜单、状态/范式/日期筛选
- 日 05:00 / 周一 05:00 / 1 日 05:00 跟踪复核（review_daily/weekly/monthly）+ 手动立即复查（覆盖月复核）
- 档案详情挂载全部报告、再次发起、已证实事件 live 按钮
- Task Force Tab：近 7 天已证实窗口；报告列表增列生成时间/预期结果/指导建议；取消/删除/勾选并排对比/失败重试；事后准确性评价
- 存量库幂等迁移与一次性临时事件清理；配套单测/API 测试/前端 vitest

**v2.0（增值方向，需另立 PRD）**

- embedding 语义聚类替换/增强 SimHash；档案事件的人工拆分/合并；叙事 virality 跨主题追踪
- 报告机会标的一键加入关注/模拟持仓形成跟踪闭环；报告导出 HTML
- 用户可编辑信源层级表与长期赛道库；事件库跨会话记忆；报告结论自动后验（预测 vs 实际走势，基于 market_data 量化打分）
- 定时任务接入 `/scheduled` 页面可视化管理；SSE 推送与未读角标；接入 eval harness 对报告做离线 rubric 评分；社交媒体情绪源接入
