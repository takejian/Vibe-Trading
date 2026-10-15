# PRD：事件分析（Event Analysis）

| 项 | 内容 |
| --- | --- |
| 版本 | v1.0（草案，待评审） |
| 日期 | 2026-10-14 |
| 范围 | 前端 Web UI + FastAPI 后端 + 本地 DuckDB；全球宏观与中国市场突发事件，跨资产影响分析 |
| 关联模块 | Swarm 多智能体编排（presets/runtime/SSE）、技能体系（skills/skill_catalog）、定时任务（scheduled）、行情与量化（market_data、quantlib.eventstudy）、新闻工具（stock_news/web_search/read_url）、关注列表（watchlist）、模拟持仓（paper）、报告中心（reports） |

---

## 1. Executive Summary

### 1.1 Problem Statement

重大投资机会往往由**突发事件与范式级新事物**驱动（新冠疫情、AI 产业浪潮、俄乌战争、超强厄尔尼诺），这类机会的共同特征是：发生时新闻混杂、真假难辨，多数人在"是否真实、是否是新事物、影响多大、如何应对"四个问题上反应迟缓，等形成共识时机会已经错过。当前系统的能力缺口：

1. **没有突发新闻雷达**：现有 `get_stock_news` 只能按需查询个股/通用财经头条，无持续采集、多源聚合、去重聚类与真实性核验，同一事件被各媒体换词重写后会被反复当作"新闻"。
2. **没有事件实体与判重机制**：事件无指纹、无生命周期、无证据合并，智能体/skill 无法回答"这件事之前是不是已经报过"。
3. **现有 Event-Driven Task Force 只覆盖个股公司事件**（并购、减持、诉讼，见 `agent/src/swarm/presets/event_driven_task_force.yaml`），不处理宏观/地缘/范式级事件；其影响分析对象是单个公司估值，而用户需要的是跨资产、跨行业赛道的传导分析与历史机会复盘。

### 1.2 Proposed Solution

在菜单栏新增独立的**事件分析**（Event Analysis，路由 `/event`），页内两个模块：

1. **突发雷达（Breaking Radar）**：按宏观事件分类矩阵从中/英文多源采集新闻，经"去重聚类 → 结构化抽取 → 真实性核验 → 新颖度/范式判定"四段门控管道，输出带**核验状态、信源数、影响等级、新颖度标签**的事件流。真实性通过信源分级 + 独立信源交叉确认 + LLM 一致性判断综合打分，未达阈值的事件进入人工复核队列；新颖度判定把事件分为"已知延续 / 已知升级 / **全新范式**"，全新范式事件（新事物，重大机会候选）置顶并建议发起深度分析。判重与识别由新增 `breaking-news-radar` skill + 扫描员智能体配合新增 `event_lookup` 工具完成。
2. **Event-Driven Task Force（宏观增强版）**：新增 swarm 预设 `macro_event_task_force`（事件情报官 → 影响分析师 → 历史类比师 → 机会策略师链式编排），支持两种模式——`live`（当下事件展望，如"超强厄尔尼诺已形成，对未来几个月的影响"）与 `retrospective`（历史事件复盘，如新冠、AI、俄乌，重点输出"当时没抓住的机会"与可复用的早期信号 checklist）。雷达事件卡可一键带上下文发起分析，报告归档并在报告中心可见。

### 1.3 Success Criteria

1. 手动触发一次扫描后，**3 分钟内**事件流可见结果；同一事件被 3 个不同信源换词报道时，事件流中**只出现 1 个事件**、其证据链含 3 条来源（固定样本集判重准确率 ≥ 95%，误合并率 ≤ 5%）。
2. 真实性状态机判定可复现：单源消息默认"未证实"，禁止自动升为"已证实"；固定样本集中谣言/反转新闻 100% 不进入"已证实"（宁可留在复核队列，不允许假确认）。
3. 标注为"全新范式"的事件必须同时给出四要素评分（政策持续性/投资周期/产业链宽度/叙事热度）与长期赛道映射，缺一项不得打该标签（结构化校验，非提示词自觉）。
4. 任一雷达事件可一键发起 macro Task Force run，run 上下文自动包含事件摘要与全部证据链接；run 过程经现有 SSE 流式可见，结束后报告在事件详情与 `/reports` 两处可查。
5. MVP 交付时可现场演示四份报告产出：**厄尔尼诺 live 报告** + **新冠 / AI / 俄乌三份 retrospective 复盘报告**，复盘报告中的资产走势数据必须来自 `get_market_data` 实取、事件研究数值必须来自 `quantlib.eventstudy`，禁止臆造数字（沿用现有 preset 的 BMP p 值/样本量披露规则）。
6. 全部采集走既有免费数据源与限流客户端，不新增付费依赖、不新增对外监听面。

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

- 雷达页顶部提供"立即扫描"按钮与扫描范围选择（中国 / 全球 / 全部，默认全部）；点击后显示扫描进度（采集源数、候选条数、各管道阶段计数），完成后 SSE 推送结果并刷新事件流。
- 采集覆盖 10 类宏观事件矩阵：地缘冲突 / 货币财政政策 / 贸易关税 / 疫情公共卫生 / 气候灾害 / 技术突破 / 产业监管 / 大选政治 / 金融信用事件 / 大宗商品供给冲击；每类中、英文双语各至少一组检索式。
- 数据源顺序：`get_stock_news(global)`（东财财经头条，经既有节流客户端）→ `web_search`（ddgs 多引擎，中文热点词 + 英文 breaking 词，带时效过滤）→ 对高价值候选用 `read_url` 深读正文；单一数据源失败不阻断整轮扫描（部分失败在扫描结果中标注）。
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

- 已证实事件详情页提供"启动 Task Force"按钮，可选模式（默认 live）、市场（A股/全球，默认全部）、时间跨度（默认 3–6 个月）；提交即调用 `POST /api/swarm/runs`（preset_name=`macro_event_task_force`），事件摘要与证据链接自动注入 user_vars，无需复制粘贴。
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

#### Story 7：定时扫描（v1.1）

> 作为用户，我希望不用手动点，系统也能按固定频率自动扫描，新的重大事件出现时我在页面上能看到未读提示。

**验收标准：**

- 定时扫描复用现有定时任务框架（`/scheduled` 菜单与 scheduled_routes），注册为系统任务"事件雷达扫描"，默认每 30 分钟一轮，可在定时任务页启停/改频率/改范围；不另起常驻调度器。
- 仅状态升级（新事件、升为已证实、升为全新范式）触发前端未读计数与 SSE 角标；纯证据追加不打扰。
- 自动扫描同样走人工终态保护（Story 3）与全部门控规则，无特权通道。

#### Story 8：报告与事件的历史回看

> 作为用户，我希望事件和报告都能按时间回看：当时系统怎么报的、后来报告结论是什么。

**验收标准：**

- 事件流支持按时间/类型/区域/状态/新颖度筛选与关键词搜索；事件详情保留状态变更历史（时间线：创建、每次证据追加、每次状态变更及操作人=自动/人工）。
- 报告列表：标题、关联事件、模式（live/retrospective）、run 状态、创建时间、完整性标记；可查看 markdown 正文与对应 swarm run 的完整过程。
- 同一事件允许多次分析（如厄尔尼诺月度更新），报告按版本倒序排列。

### 2.4 Non-Goals（本期明确不做）

- 不做新闻/事件驱动的自动下单或模拟仓自动调仓；报告中的标的仅为研究线索。
- 不做秒级/分钟级实时推送；扫描粒度为 30 分钟级（手动 + 定时）。
- 不接入付费数据源（Bloomberg/RavenPack/万得等）；仅用现有免费源与限流客户端。
- 不做面向社交媒体（X/微博/股吧）的实时舆情流式采集（现有 sentiment 团队预设与未来 social_alpha 方向另议）。
- 不做多用户、权限体系与事件库云同步；本地单用户，事件库存本地 DuckDB。
- 不改动既有个股公司事件预设 `event_driven_task_force.yaml` 及其使用入口。
- 不新增 LLM 模型；全部智能能力通过现有 LLM 网关与既有模型完成。
- 不做移动端与桌面端专门适配（沿用现有 Web/SPA 渠道）。

---

## 3. AI System Requirements

### 3.1 既有 AI 能力的消费（无新增模型）

- **新闻采集**：复用 `get_stock_news`（`agent/src/tools/stock_news_tool.py`，scope=global，东财/Yahoo 节流客户端）、`web_search`（`agent/src/tools/web_search_tool.py`，ddgs 多引擎回退 + 可选阿里 IQS）、`read_url`（`agent/src/tools/web_reader_tool.py`）。
- **LLM 结构化补全**：管道中的事件抽取、跨源一致性判定、新颖度/范式评分复用现有 LLM 客户端的单次结构化输出能力（与 macro/sentiment 分析同一网关），强制 JSON schema 输出与 schema 校验重试；不新接模型供应商。具体客户端入口实现时与 macro 模块对齐，禁止在 config 层之外读环境变量（受 `tools/ci_env_var_gate.py` 约束）。
- **行情与事件研究**：`get_market_data` 取历史 K 线；`src.quantlib.eventstudy.event_study` 做 CAR/CAAR 与 BMP/Patell 检验。
- **Swarm 编排**：复用 `POST /api/swarm/runs`（preset_name + user_vars）、run 历史与 SSE（`agent/src/api/swarm_routes.py`），不新建编排设施。
- **预设资产借鉴**：宏观框架吸收 `geopolitical_war_room.yaml`（GPR 指数、六大热点评级、历史类比）与 `sentiment_intelligence_team.yaml`（新闻情报官、政策周期与叙事框架）的成熟提示词。

### 3.2 新增 AI 资产生成

**（1）skill pack：`breaking-news-radar`（经 `agent/src/swarm/skill_catalog.py` 注册到 event_driven 分类）**

内容包含：宏观事件十分类分类法与判定边界、信源四级分级表与转载识别规则、真实性核验 rubric（独立性/一致性/辟谣识别）、新颖度三分类定义、全新范式四要素评分卡（1–5 分锚点描述）、长期赛道库与映射规则、固定 JSON 输出 schema（新建/合并动作、event_id、字段清单）、强制工作流（先 `event_lookup` 判重 → 再抽取 → 后判定）。

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
事件分析 /event (新)
 EventAnalysis.tsx
  ├─ Tab1 BreakingRadar（事件流/详情/复核队列/扫描批次）
  └─ Tab2 TaskForce（发起分析/进行中/报告列表/报告详情）
      │ lib/api.ts 新增 /api/events/* 封装；useSSE 新增雷达/run 事件
      ▼
api_server.py（仅注册新路由，不改旧逻辑）
      │
src/api/event_routes.py（新增，前缀 /api/events）
      │
src/eventradar/（新增业务包）
  ├─ service.py    扫描编排、状态机、人工动作、发起 run、报告归档
  ├─ sources.py    多源采集（复用 stock_news/web_search/read_url 工具执行器）
  ├─ dedup.py      SimHash 指纹 + 实体×类型×时间窗聚类
  ├─ extract.py    LLM 结构化抽取/一致性/范式评分（JSON schema 强制）
  ├─ scoring.py    信源分级表、置信度与状态升级规则、范式四要素评分
  ├─ db.py         幂等建表 DDL + DAO（短连接，沿用 watchlist db 模式）
  └─ report.py     报告章节完整性校验与归档
      │
      ├─ DuckDB 市场库（get_market_db_path，同库不同表）
      │   radar_scan_run / radar_event / radar_evidence / event_report
      ├─ Swarm runtime（既有）运行 macro_event_task_force 预设
      └─ 定时任务框架（既有，v1.1 注册"事件雷达扫描"系统任务）
```

**隔离原则**：新功能落在新包 `src/eventradar/`、新路由 `src/api/event_routes.py`、新预设、新 skill、新工具；对既有代码的触碰仅限：导航数组、路由表、i18n 文案、`api_server.py` 一行路由注册、工具注册表一行注册、skill_catalog 一行分类注册。不新增反向层依赖（受 `scripts/lint-deps` 与 grandfathered 边表约束）。

### 4.2 数据流

1. **手动扫描**：`POST /api/events/scan {scope}` → 建 `radar_scan_run`（running）→ 多源采集候选（工具失败隔离）→ SimHash 近重过滤 → 聚类键归并 → LLM 批量结构化抽取（先由智能体经 `event_lookup` 判重，服务端二次指纹校验兜底）→ 核验评分确定初始状态 → 范式四要素评分与赛道映射 → 写 `radar_event`/`radar_evidence`（人工终态事件跳过自动改写）→ 批次置 completed → SSE 推送新增/升级摘要。
2. **后续扫描合并**：证据按 URL 防重追加；信源数与一致性满足升级条件时按状态机自动升级（未证实→核验中→已证实；争议/谣言只可由人工或辟谣证据触发）；范式分随证据量与热度重算，升级留痕。
3. **人工复核**：`POST /api/events/{id}/verify {action, note}` → 写状态历史；终态（已证实人工确认/谣言/丢弃）对后续自动扫描生效。
4. **发起分析**：`POST /api/events/{id}/analyze {mode,market,time_horizon}`（或 `/api/events/analyze` 自定义历史事件）→ 组装 user_vars（事件摘要 + 证据 URL 列表 + 模式）→ 调 swarm runtime `start_run(preset_name="macro_event_task_force", user_vars=...)` → 落一条 pending `event_report`（run_id 关联）。
5. **报告归档**：SSE 收到 run 完成事件后拉取 run 产出 markdown，章节完整性校验通过后置 complete；复盘模式额外做数据引用合规检查（数字须带工具来源标记）。
6. **定时扫描（v1.1）**：以系统定时任务调用同一 service 入口，语义与手动扫描完全一致。

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
    UNIQUE(cluster_key)
);
CREATE INDEX idx_radar_event_status ON radar_event(verify_status, last_update_at);
CREATE INDEX idx_radar_event_type   ON radar_event(event_type, first_seen_at);

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

-- Task Force 报告
CREATE TABLE event_report (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR,                   -- 复盘自定义事件可空
    run_id            VARCHAR NOT NULL,
    mode              VARCHAR NOT NULL,          -- live | retrospective
    title             VARCHAR NOT NULL,
    market            VARCHAR,
    time_horizon      VARCHAR,
    status            VARCHAR NOT NULL,          -- pending | running | completed | incomplete | failed
    markdown          VARCHAR,
    sections_present  VARCHAR,                   -- JSON：固定章节存在性
    data_sources      VARCHAR,                   -- JSON：引用到的工具取数记录
    created_at        TIMESTAMP NOT NULL,
    completed_at      TIMESTAMP
);
CREATE INDEX idx_event_report_event ON event_report(event_id, created_at);
```

- 写入均走短连接单事务（沿用 `watchlist/db.py` 模式），扫描批次与证据写入分批提交，避免长事务。
- `cluster_key` 唯一约束兜底防重复事件；LLM 判重结果与服务端指纹聚类不一致时以服务端聚类为准并记日志（供样本集回溯）。

### 4.4 核验与评分规则（默认参数，集中配置）

| 规则 | 默认值 |
| --- | --- |
| 聚类时间窗 | 72 小时 |
| SimHash 海明距离阈值 | 3（64 位指纹） |
| 升"已证实"最少独立信源数 | 2，且至少 1 个 T1/T2 |
| 综合置信度确认阈值 | 0.70 |
| 全新范式总分阈值 | 15 / 20（四要素各 1–5） |
| 单轮候选上限 / 单源条数上限 | 200 / 50（防噪声源放大） |
| 证据摘要长度上限 | 280 字符（与新闻工具一致） |

- 综合置信度 = 信源层级分（加权 0.4）+ 独立信源数（0.25）+ 跨源事实一致性 LLM 分（0.35），权重在 `scoring.py` 集中常量化。
- 状态机只允许相邻/规定路径转移；`dismissed/rumor/人工 confirmed` 为锁定态，自动扫描仅追加证据与 timeline 提示。

### 4.5 配置项（走统一 env schema）

在 `agent/src/config/env_schema.py` 既有模式下新增：

- `VIBE_EVENT_RADAR_ENABLED`（默认 true；false 时仅可手动扫描，定时任务不注册）
- `VIBE_EVENT_SCAN_INTERVAL_MINUTES`（默认 30）
- `VIBE_EVENT_DEDUP_WINDOW_HOURS`（默认 72）
- `VIBE_EVENT_VERIFY_MIN_SOURCES`（默认 2）、`VIBE_EVENT_CONFIRM_THRESHOLD`（0.70）
- `VIBE_EVENT_PARADIGM_THRESHOLD`（默认 15）
- 信源层级表与长期赛道库存放于 `src/eventradar/` 内置默认（JSON 常规模板，不读外部文件路径），本期不暴露 env；v2.0 评估用户可编辑。

### 4.6 API（新路由 `src/api/event_routes.py`，前缀 `/events`）

> 实现注记：按代码库既有约定（`/watch`、`/paper`、`/options` 等均无 `/api`
> 前缀），实际挂载路径如下表；MVP 的扫描/报告刷新采用前端轮询
>（扫描运行中 3s、报告运行中 5s），SSE 事件类型留待 v1.1 接入。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/events/events` | 事件流，支持 status/novelty/type/region/keyword 筛选 |
| POST | `/events/scan` | body `{scope}`；手动触发一轮扫描，返回 scan_run 摘要（异步，前端轮询） |
| GET | `/events/scan-runs` | 最近扫描批次与各源状态 |
| GET | `/events/events/{id}` | 事件详情：字段 + 证据链 + 状态时间线 + 报告列表 |
| POST | `/events/events/{id}/verify` | body `{action: confirm\|flag_dispute\|mark_rumor\|dismiss, note}` |
| POST | `/events/events/{id}/analyze` | body `{mode, market, time_horizon}`；已证实事件发起 run，返回 run_id |
| POST | `/events/analyze` | 自定义/历史事件发起复盘：`{event_title, event_period, mode:retrospective, market}` |
| GET | `/events/reports` | 报告列表（模式/状态筛选） |
| GET | `/events/reports/{id}` | 报告 markdown、章节完整性、run 链接 |

- 认证/监听面与现有路由注册方式一致，loopback 默认绑定，不新增外发通道。
- 4xx 覆盖：未证实事件禁止分析（409）、事件不存在（404）、非法状态转移（400）、扫描进行中重复提交（409）、非法枚举（422）。
- MVP 不新增 SSE 事件类型：扫描中 3s 轮询批次、报告运行中 5s 轮询列表；`radar_scan_progress`/`radar_event_new`/`radar_event_updated`/`event_report_completed` 等 SSE 事件留待 v1.1 接入现有连接。

### 4.7 后台调度

- MVP **不新增常驻后台任务**：仅手动扫描。
- v1.1 通过现有定时任务框架注册"事件雷达扫描"系统任务（频率默认 30 分钟、范围默认全部，用户可在 `/scheduled` 启停与修改），直接复用 `service.run_scan()`，不另起 APScheduler/lifespan 任务。

### 4.8 前端

- 导航与路由：`Layout.tsx` NAV 新增 `/event`（Radar/Newspaper 图标，置于宏观分析之后）；`router.tsx` 新增 `EventAnalysis` 路由；i18n 补 `layout.eventAnalysis` 及中英文案。
- 新页面 `pages/EventAnalysis.tsx`，两个 Tab：
  - **突发雷达**：顶部扫描操作区（范围选择/立即扫描/批次状态）→ 事件流卡片列表（状态色、新颖度角标、范式分、信源数、影响等级、时间）→ 筛选器条；抽屉/详情页含证据链表、状态时间线、相似事件、[启动 Task Force] 按钮；复核队列作为独立子 Tab/筛选视图，提供人工操作按钮。
  - **Task Force**：发起区（选事件或历史复盘模板：新冠/AI/俄乌 + 模式/市场/区间）、进行中 run（复用 swarm run 状态组件）、报告列表、报告 markdown 详情（复用现有 markdown 渲染）。
- 全部请求封装进 `frontend/src/lib/api.ts`；不引入 react-query 等新数据层，沿用 Watchlist/Swarm 页面既有模式。
- 事件流/报告更新由 SSE 驱动；页面不可见时不轮询。

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
  - 扫描服务：数据源部分失败隔离、并发扫描 409、批次计数正确、SSE 事件载荷；
  - 报告归档：章节完整性判定、retrospective 数字无来源标记时判 incomplete；
  - 预设：`macro_event_task_force.yaml` 通过既有预设加载与 DAG 校验（无环/无孤儿/变量齐全）。
- API 层测试参照 `agent/tests/test_portfolio_routes.py` 与 swarm routes 测试的既有模式。
- 前端 vitest：事件卡状态渲染与置灰（未证实禁止分析）、筛选器、复核操作确认、SSE 事件合并到列表。
- 评测样本集纳入 `make test`，三项核心指标（判重准确率 ≥95%、谣言零误确认、范式分类）在样本集上回归。
- lint 门禁：新包遵守层级规则，不引入新反向边；config 外不读环境变量。

---

## 5. Risks & Roadmap

### 5.1 Technical Risks

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 免费新闻源限流/内容农场噪声 | 候选缺失或被垃圾新闻淹没 | 多引擎回退（现有 ddgs 机制）、信源分级降权 T4、单源条数与单轮候选上限、部分失败不致命 |
| LLM 把谣言/单源消息误判为已证实 | 错误事件驱动后续分析 | 默认未证实；硬规则（≥2 独立信源含 T1/T2）先于 LLM；阈值门控；人工复核队列；样本集回归"零假确认" |
| 换词重写导致事件重复/误合并 | 事件流噪声或错误证据合并 | 双层判重（SimHash + 聚类键）+ 智能体 `event_lookup` + 服务端唯一键兜底；冲突时以服务端聚类为准并留日志 |
| 宏观影响分析主观性强、数字编造 | 报告可信度受损 | 固定章节 + 三情景概率 + 强制反方观点；历史数值强制走 event_study/get_market_data 并披露样本量与 p 值，规则对齐现有严格预设；报告完整性程序化校验 |
| LLM 结构化输出不稳定 | 管道中断/脏数据 | JSON schema 校验 + 限定重试次数；失败候选进复核队列而非丢弃；批次部分成功可交付 |
| 扫描成本（LLM 调用量） | 高频扫描费用上升 | SimHash/聚类在 LLM 之前完成粗筛；批量抽取；默认 30 分钟粒度；候选上限 |
| 与既有公司事件预设概念混淆 | 用户误用 | 命名隔离（macro_event_task_force）；菜单文案区分"宏观/突发"与 Swarm 工作室中的公司事件团队 |

### 5.2 Phased Rollout

**MVP（第一批，可用闭环）**

- 菜单/路由/i18n；DuckDB 四张表（scan_run/event/evidence/timeline）+ report 表
- `src/eventradar/` 新包：多源采集、双层判重、结构化抽取、核验状态机、范式评分
- `breaking-news-radar` skill + `event_lookup` 工具注册
- 雷达前端：事件流、事件详情（证据链/时间线）、复核队列、手动扫描与 SSE 刷新
- `macro_event_task_force` 预设（四角色链，live/retrospective 双模式）
- 一键发起分析、报告列表与详情、章节完整性校验
- 固定评测样本集与单测；**演示产出：厄尔尼诺 live 报告 + 新冠/AI/俄乌三份复盘报告**

**v1.1（自动化与体验补全）**

- 定时扫描接入 `/scheduled`（系统任务、可配置频率/范围）、未读角标
- 扫描批次与各源状态可视化；信源层级管理界面（只读查看）
- 报告标的跳转关注列表；叙事热度曲线（证据量时间序列）
- 前端 vitest 补全、空态/错误文案打磨

**v2.0（增值方向，需另立 PRD）**

- embedding 语义聚类替换/增强 SimHash；叙事 virality 跨主题追踪
- 报告机会标的一键加入关注/模拟持仓形成跟踪闭环；报告导出 HTML
- 用户可编辑信源层级表与长期赛道库；事件库跨会话记忆与报告结论后验（预测 vs 实际走势）
- 接入 eval harness 对报告做离线 rubric 评分；社交媒体情绪源接入
