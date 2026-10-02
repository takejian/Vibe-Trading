# M16 关注（自选标的）模块 — 实施计划

> 垂直切片按依赖序排列。后端任务 T1–T7、前端任务 T8–T14、全模块门禁 T15。
> 每个任务自带测试（保持"实现+测试同任务"原则），全部离线可跑（网络/LLM 注入 mock）。

## Task 1: 路径助手 + 自选清单 JSON 存储
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `agent/src/config/paths.py` 新增 `get_watchlist_dir()`（runtime_root/watchlist）与 `get_market_db_path()`（runtime_root/data/market.duckdb，遵循 VIBE_TRADING_HOME，替代散落硬编码；`scripts/local_db/init_local_db.py` 改为引用该助手，保持默认路径不变）。
  - 新建 L2 包 `agent/src/watchlist/__init__.py`、`models.py`（pydantic：`WatchEntry(symbol,name,industry,added_at,updated_at)`、快照字段内嵌 quote 缓存 `price/total_market_cap/pe/pb/quote_updated_at`）、`store.py`（`WatchlistStore`，文件 `watchlist.json`，镜像 RoleStore 原子写：tempfile+os.replace；方法 list/add（重复抛 `ValueError`/专用异常 → 路由 409）/remove/get/upsert_snapshot；损坏行跳过；id/symbol 校验 `^\d{6}\.(SH|SZ|BJ)$`）。
- **Acceptance Criteria Addressed**: AC-3, AC-11, AC-17
- **Test Requirements**:
  - `rule` TR-1.1：tmp 路径下 add/list/remove 正常；重复 add 同一 symbol 抛重复异常且文件仍只有一行；remove 不存在 symbol 行为定义明确（幂等返回或 404，由实现选定并测试固化）
  - `rule` TR-1.2：并发/异常安全——写入走临时文件+replace；损坏 JSON 不炸全量读取（空清单降级）
  - `rule` TR-1.3：路径助手遵循 VIBE_TRADING_HOME；`make lint` 无 os.getenv 违规（新文件零 os.environ）
  - `rule` TR-1.4：init_local_db.py 引用助手后 DEFAULT_DB 行为不变（其现有测试或导入检查通过）
- **Notes**: 新增测试文件 `agent/tests/test_watchlist_store.py`

## Task 2: A股搜索与快照/F10 取数服务（纯函数 + 可注入 fetcher）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `agent/src/watchlist/market.py`：
    - `normalize_a_share_symbol(code)`：6 位代码→规范 symbol（6/9 开头 .SH（含 688）；0/2/3 开头 .SZ；4/8 开头 .BJ；其余拒绝）。
    - `search_a_shares(keyword, fetcher=None)`：经 `backtest.loaders.eastmoney_client.get_json` 调 clist 关键字接口（fields 至少 f12/f14/f100），返回 `[{symbol,name,industry}]`，限 20 条；去重、代码规范化、关键字为空返回空；超时/HTTP 失败抛 `WatchlistDataError`（无凭据信息）。
    - `fetch_quote_snapshot(symbols, fetcher=None)`：批量一次 clist 请求取 f2 现价/f9 PE/f23 PB/f20 总市值/f14 名称/f100 行业；"-" 哨兵 → None；空列表短路不发请求；返回按 symbol 索引 dict。
    - `fetch_company_profile(symbol, fetcher=None)`：akshare `stock_individual_info_em`（延迟 import，无 akshare/网络时抛 WatchlistDataError），映射 上市时间→list_date、行业、总股本；注册资本取不到为 None。
  - 所有网络函数均支持注入 fetcher，默认 fetcher 集中在文件底部；模块不缓存、不重试（重试在服务层/前端）。
- **Acceptance Criteria Addressed**: AC-2, AC-4, AC-5
- **Test Requirements**:
  - `rule` TR-2.1：代码号段映射单测（600519→SH、000001→SZ、300750→SZ、830799/430047→BJ、非法拒绝）
  - `rule` TR-2.2：注入 clist 样例响应，搜索返回规范化候选且限 20 条；空关键字零调用；"-" 哨兵 → None
  - `rule` TR-2.3：批量快照多 symbol 仅产生一次 fetcher 调用（NFR-2），字段映射正确；空列表零调用
  - `rule` TR-2.4：profile 映射单测（含注册资本缺失→None、上市时间字符串→date）
  - `rule` TR-2.5：fetcher 抛异常时统一包装 WatchlistDataError，错误信息无 URL/凭据
- **Notes**: 测试文件 `agent/tests/test_watchlist_market.py`，全程不触网

## Task 3: DuckDB 持久化层（新表 DDL + 快照 upsert + 客观数据读写 + 缠论表）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新建 `agent/src/watchlist/db.py`：`watchlist_connection()` 短连接（get_market_db_path，自动建父目录）；`initialize_schema()` 幂等执行新 DDL：
    - `watchlist_objective_data(id UUID PK, symbol VARCHAR, category VARCHAR, request_note VARCHAR, payload VARCHAR/*JSON*/, source VARCHAR, run_id VARCHAR, created_by VARCHAR, created_at TIMESTAMP)` + 索引 (symbol, created_at)。
    - `chanlun_analysis(id UUID PK, run_id VARCHAR UNIQUE, symbol VARCHAR, analyzed_at TIMESTAMP, dim1_structure_read … dim7_chanlun_score 文本列、score INTEGER CHECK(score BETWEEN -5 AND 5)、confidence DOUBLE CHECK(0..1)、structured BOOLEAN、raw_report VARCHAR, created_at TIMESTAMP)` + 索引 (symbol, analyzed_at)。
  - `upsert_instrument(master dict)` / `upsert_valuation(symbol, trade_date, pe,pb,mcap,source)`：对既有 instrument_master/valuation_daily 幂等 INSERT OR REPLACE。
  - `list_raw_data(symbol)`：分别查 daily_bar（近 N 日上限）、valuation_daily、financial_statement、instrument_master，表不存在（CatalogException）时该分类返回空列表不报错。
  - `insert_objective_record(...)` / `list_objective_records(symbol)`；`insert_chanlun_record(...)` / `list_chanlun_records(symbol, date_from, date_to)`（倒序、limit/offset 上限 100）。
  - 全部参数化 SQL；写连接 autocommit/with 事务。
- **Acceptance Criteria Addressed**: AC-5, AC-6, AC-7, AC-12, AC-14
- **Test Requirements**:
  - `rule` TR-3.1：tmp duckdb 上 initialize_schema 连跑两次成功（幂等）；新表/既有表共存
  - `rule` TR-3.2：instrument/valuation upsert 同主键重复执行结果一致（后值覆盖、行数不增）
  - `rule` TR-3.3：空库（未建旧表）list_raw_data 四分类均返回空且不抛异常；灌入样例行后分类正确
  - `rule` TR-3.4：缠论插入 score 越界（6/-6）被 CHECK 拒绝；confidence 越界拒绝；正常行可按时间倒序+日期区间查出
  - `rule` TR-3.5：objective 记录写入/列出字段完整（payload JSON 可解析、run_id 留存）
- **Notes**: 测试文件 `agent/tests/test_watchlist_db.py`

## Task 4: 已发布角色三分类目录（确定性纯规则）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None（仅依赖现有 role_catalog）
- **Description**:
  - 新建 `agent/src/watchlist/role_catalog_filter.py`：
    - 常量：技术面 preset 集合（含 technical_analysis_panel）、基本面 preset 集合（fundamental_research_team/earnings_research_team/equity_research_team/value_investing_committee）；中英关键词表（技术：技术/缠论/Chanlun/Elliott/波浪/Ichimoku/SMC/K线/均线/MACD/动量/形态/Technical；基本面：基本面/财务/财报/盈利/估值/价值/Fundamental/Financial/Earnings/Value）。
    - `classify_role(entry) -> (category, is_chanlun)`：preset 优先；自建 approved 角色走关键词（name+purpose）；无命中→general。
    - `list_analyst_roles(category, store=None)`：基于 `list_approved_role_refs()` + detail（取 purpose）扁平化，过滤分类，输出 `{ref,name,purpose,category,is_chanlun}`；未批准角色不出现。
    - 缠论识别：ref == `technical_analysis_panel:chanlun_analyst` 或 name 精确匹配（大小写/空白归一）。
  - 单元测试用 monkeypatch 替换 list_approved_role_refs，不触盘真实 roles 目录（另可加一条 tmp store 集成用例）。
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-4.1：内置代表角色分类正确（chanlun_analyst→technical/is_chanlun=true；classic_ta/ichimoku/wave/smc→technical/is_chanlun=false；fundamental/earnings 角色→fundamental；macro/risk/aggregator 等→general）
  - `rule` TR-4.2：关键词自建角色命中两域；无关键词→general；未批准角色被上游过滤（本函数不出现）
  - `rule` TR-4.3：`list_analyst_roles("technical")` 每项含 category/is_chanlun 字段且不含其他分类
- **Notes**: 测试文件 `agent/tests/test_watchlist_role_filter.py`

## Task 5: 分析与补充抓取服务（发起/防重/历史 + 缠论解析持久化）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2, Task 3, Task 4
- **Description**:
  - 新建 `agent/src/watchlist/analysis.py`：
    - `default_question(category, symbol, name, brief)`：brief 留空时生成中文默认研究问题（含名称与 symbol）；非空时在诉求前注入标的上下文行。
    - `start_analysis(symbol, category, role_ref, brief, runtime=None, store=None)`：校验 symbol 已关注？（允许对已关注标的；未关注 404/400 由路由定）；角色须属该分类且 approved（复用 T4，不符→ValueError→400）；扫描 role_run 历史，同 symbol(target)+trial_role 处于 pending/running → 抛 `AnalysisInProgress`（→409）；调 `SwarmRuntime.start_run("", {}, role_run={role_ref,target: symbol 或 "名称(symbol)",question})`。
    - `list_analyses(symbol, category, role_ref, date_from, date_to, limit)`：调 store.list_runs(10000) 过滤 kind=role_run、target 命中 symbol、角色属于该分类，复用现有 reconcile；返回摘要（id/角色/时间/状态/qualified/报告摘录）。
    - 补充抓取 `start_objective_fetch(symbol, note, runtime=None)`：校验 note 非空；target=symbol、question=需求文本（含标的信息）；role_ref 取系统指定内置数据研究角色常量（先解析存在性，不存在抛服务错误）；同样防重；run 完成后的归档由 `persist_run_artifacts(run)` 在路由读取/轮询 reconcile 时惰性执行（见下）。
    - `persist_run_artifacts(run)`：对已完成且未归档的 role_run：缠论角色→解析 final_report 写 chanlun_analysis（run_id UNIQUE 幂等）；数据抓取角色→把 final_report 作为 objective 记录归档（同样按 run_id 幂等）。在历史/明细查询前调用，保证完成后落库，无需后台守护线程。
  - 新建 `agent/src/watchlist/chanlun_parser.py`：纯函数 `parse_chanlun_report(text) -> dict|None`，按 1–7 编号标题切分（兼容 `**1.`、`1.`、`###`、中英标题）；提取 score（−5..+5 整数）与 confidence（"78%" 与 "0.78" 两写法→0..1）；缺段/越界→None（交调用方落 structured=false 原文行）。
- **Acceptance Criteria Addressed**: AC-7, AC-9, AC-10, AC-12
- **Test Requirements**:
  - `rule` TR-5.1：默认问题含名称与 symbol；brief 非空时标的上下文被注入且不吞掉用户诉求
  - `rule` TR-5.2：start_analysis 正常路径以 role_run 三元组调 runtime（fake runtime 捕获参数），target/question 符合要求
  - `rule` TR-5.3：角色不属于该分类/未批准 → ValueError；同 symbol+role 进行中 → AnalysisInProgress，且 fake store 中 run 数不增加
  - `rule` TR-5.4：list_analyses 过滤 symbol/分类/角色/日期正确，倒序
  - `rule` TR-5.5：parse_chanlun_report 四组用例——完整 7 段（含百分制/小数制置信度各一）、缺段→None、score=+6 越界→None、score=−5/confidence=0/100% 边界合法
  - `rule` TR-5.6：persist_run_artifacts 对缠论成功 run 落库且重复调用不产生重复行（UNIQUE/幂等）；非结构化报告写 structured=false 原文行；抓取 run 落 objective 表
- **Notes**: 测试文件 `agent/tests/test_watchlist_analysis.py`、`agent/tests/test_chanlun_parser.py`；runtime/store 全部用 fake

## Task 6: 后端路由 watchlist_routes + 挂载
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3, Task 5
- **Description**:
  - 新建 `agent/src/api/watchlist_routes.py`，仿 swarm_routes 从宿主 sys.modules 取 `require_auth`，`register_watchlist_routes(app)`；在 `agent/api_server.py` 于 swarm 路由后挂载。
  - 端点：
    - `GET /watch/list`：清单 + 批量快照合并（快照失败：字段 null + quote_error 标记，不 500）。
    - `POST /watch` `{symbol|candidate}`：加入（搜索候选直传 symbol+name+industry）；重复→409。
    - `DELETE /watch/{symbol}`：逐行移除。
    - `GET /watch/search?q=`：A股搜索。
    - `GET /watch/{symbol}/profile`：画像（库内 + 可刷新）。
    - `POST /watch/{symbol}/refresh-quotes`、`POST /watch/{symbol}/refresh-profile`：直接取数（service 内不引用 runtime/LLM）并 upsert，返回最新值与更新时间；数据通道异常→502/400 + 明确 detail。
    - `GET /watch/{symbol}/objective`：四类原始数据 + 补充抓取记录。
    - `POST /watch/{symbol}/objective-fetch` `{note}`：发起抓取 run（note 空→400）。
    - `GET /watch/agents?category=fundamental|technical|general`。
    - `POST /watch/{symbol}/analyze` `{category,role_ref,question?}`：校验/防重→409/400，返回 run 摘要。
    - `GET /watch/{symbol}/analyses?category=&role_ref=&from=&to=&limit=`（查询前 persist_run_artifacts 惰性落库）。
    - `GET /watch/{symbol}/chanlun?from=&to=&limit=`。
  - 统一错误：ValueError→400、FileNotFoundError→404、AnalysisInProgress→409、WatchlistDataError→502；path 参数走宿主校验。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-13, AC-14
- **Test Requirements**:
  - `rule` TR-6.1：TestClient（tmp VIBE_TRADING_HOME + 注入 fake fetcher/runtime）覆盖：清单空→加入→重复 409→列表含快照→删除；搜索；profile/refresh 两按钮成功与数据通道失败两路径，且 refresh 测试中断言 fake runtime/LLM 零调用
  - `rule` TR-6.2：objective 空库 200 + 分类空数组；objective-fetch 空 note→400；成功返回 run id
  - `rule` TR-6.3：analyze 未选/错类/未批准→400；进行中→409；正常→200 且返回 run id/status；analyses 过滤与 chanlun 列表（倒序/日期）正确
  - `rule` TR-6.4：全部端点带 require_auth 依赖（审查 + 现有鉴权测试模式）
- **Notes**: 测试文件 `agent/tests/test_watchlist_routes.py`；参考 swarm custom skill routes 的 TestClient 写法

## Task 7: 后端门禁与分层回归
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6
- **Description**:
  - 运行 `make lint`（lint-deps 确认 watchlist(L2) 仅依赖 L0/L1/L3 允许方向、无新反向边；ruff 硬规则；env var gate；安全扫描）与 `make test-fast`，修复全部发现。
- **Acceptance Criteria Addressed**: AC-17, AC-U2
- **Test Requirements**:
  - `rule` TR-7.1：`scripts/lint-deps` 退出码 0，layer-map.json 无改动
  - `rule` TR-7.2：ruff/watchlist 相关文件零违规；env 门禁扫描零新增
  - `rule` TR-7.3：`make test-fast` 全绿（含新增 watchlist 测试）
- **Notes**: 输出命令结果作为完成证据

## Task 8: 前端 API 客户端与类型
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6（可与 T6 并行对型，最终以后端为准）
- **Description**:
  - 在 `frontend/src/lib/api.ts` 新增类型（WatchEntry/QuoteSnapshot/CompanyProfile/ObjectiveData/AgentOption/AnalysisSummary/ChanlunRecord）与方法：listWatch/addWatch/removeWatch/searchWatch/getWatchProfile/refreshWatchQuotes/refreshWatchProfile/getObjective/startObjectiveFetch/listWatchAgents/startWatchAnalysis/listWatchAnalyses/listChanlun；复用既有 request 助手与错误抛出约定；SSE 直接复用 `swarmSseUrl(runId)`。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-8.1：方法 URL/方法体与后端路由逐一对应（类型检查通过；api 层在页面测试中间接验证）
  - `rule` TR-8.2：`npx tsc -b`（fe-build）无类型错误
- **Notes**: 无独立测试文件，由页面测试覆盖

## Task 9: i18n（9 语言）+ 导航 + 路由
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 8
- **Description**:
  - 9 个 locale 增加 `layout.watch` 与 `watch.*` 全量键（列表/详情/五 Tab/弹窗/按钮/状态/错误/缠论 7 维中英标题维度名走 i18n 或前端常量双语）。
  - `Layout.tsx` NAV 在 skillPlaza 后插入 `{to:"/watch", icon: Star, label: t("layout.watch")}`（lucide Star 已可用则直接用，否则按现有导入风格加入）。
  - `router.tsx` lazy 注册 `/watch`→Watchlist、`/watch/:symbol`→WatchDetail。
- **Acceptance Criteria Addressed**: AC-1, AC-16
- **Test Requirements**:
  - `rule` TR-9.1：9 语言文件 watch/layout.watch 键集合完全一致（脚本或测试断言）；en/zh-CN 人工核对无语义缺失
  - `rule` TR-9.2：路由/菜单渲染测试：导航出现"关注"，点击到 /watch；直接渲染 /watch/:symbol 不崩
- **Notes**: 参考 M14 新增 skillPlaza 命名空间的落点

## Task 10: 标的列表页（表格/排序/勾选/添加弹窗/取消关注/对比占位）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 9
- **Description**:
  - 新建 `frontend/src/pages/Watchlist.tsx`：顶部标题 +【AI 批量对比】占位按钮 +【添加标的】；表格列 勾选/名称代码/行业/现价/总市值/PE/PB/操作（查看→navigate `/watch/:symbol`、取消关注→ConfirmDialog）；列头排序（现价/市值/PE/PB，null 值排末尾，三态或两态与现网表格一致）；添加弹窗含防抖搜索输入（≥300ms）、候选列表、选中即加入并刷新、无结果提示、重复错误后端 message 回显；空状态；加载/错误骨架（复用 common/Skeleton）。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-4, AC-14, AC-U1
- **Test Requirements**:
  - `rule` TR-10.1：渲染字段齐全；点击列头排序两方向正确、null 不崩；勾选仅改视觉无批量按钮出现
  - `rule` TR-10.2：添加弹窗搜索防抖→候选→点击加入→列表刷新；409 message 显示；无结果态
  - `rule` TR-10.3：取消关注走 ConfirmDialog，确认调 removeWatch，取消不调；查看跳转 /watch/:symbol
  - `rule` TR-10.4：AI 批量对比点击仅出现提示且无任何 api 调用（vi.fn 断言）；空状态渲染
- **Notes**: 测试 `pages/__tests__/Watchlist.test.tsx`，api 全部 mock

## Task 11: 详情页框架 + 概览 Tab + 客观数据 Tab
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 10
- **Description**:
  - 新建 `frontend/src/pages/WatchDetail.tsx`（或 pages/watch/ 目录）：头部标的名/代码 + 返回列表；5 个子 Tab（概览/客观数据/基本面/技术面/AI 分析，Tab 状态可入 URL hash 或内存，刷新默认概览）；useParams 取 symbol，未关注/404 展示返回引导。
  - 概览：画像描述列表（名称/代码/行业/现价/总市值/IPO 日期/注册资本/更新时间，缺项"暂无数据"）；【更新股价与估值】【更新获取基本信息】按钮带 loading/成功失败反馈，失败 message + 可重试。
  - 客观数据：四个原始数据分区表（行情/估值/财报/主数据，空分区"暂无数据"）+ 补充抓取区（textarea + 发起按钮，空内容禁用，发起后展示运行状态，完成刷新归档列表；归档记录展示需求/时间/来源/正文）。
- **Acceptance Criteria Addressed**: AC-5, AC-6, AC-7, AC-13, AC-14, AC-U1
- **Test Requirements**:
  - `rule` TR-11.1：概览字段渲染与缺项占位；两更新按钮点击调用正确 api（quotes/profile 各一次）并回显；失败显示错误与重试
  - `rule` TR-11.2：客观数据四分区（有/无数据两分支）；补充抓取空内容禁用、成功后刷新、失败提示
  - `rule` TR-11.3：返回列表按钮与 404 引导
- **Notes**: 测试 `pages/__tests__/WatchDetail.test.tsx`

## Task 12: 基本面/技术面/AI 分析 Tab（角色选择 + 运行 + 历史）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 11
- **Description**:
  - 新建可复用组件 `components/watch/AnalysisTab.tsx`（props: category, symbol, symbolName）：角色单选列表（来自 listWatchAgents(category)，展示 name/purpose，未选中时运行禁用+提示）；补充诉求 textarea（可选）；运行→startWatchAnalysis（409 时展示"该智能体分析进行中"并刷新历史/进行中卡片）；进行中与刚发起的 run 复用 `RunView`（mock 友好：沿用 RunView 既有 props：runId/symbol 等，以 RoleSquare L647-680 用法为准）+ `useSSE(swarmSseUrl)`；历史区按角色分组、时间倒序、可展开，正文用 `MarkdownContent`；分页"加载更多"或固定 limit=20。
  - 基本面 Tab 顶部额外加载原始财务数据区（GET /objective 的财报分区只读复用，暂无显示"暂无数据"）。
  - AI 分析 Tab 使用 category=general；结论区允许图表/数据随 Markdown 呈现（MarkdownContent 已支持）。
- **Acceptance Criteria Addressed**: AC-9, AC-10, AC-11, AC-14, AC-U1
- **Test Requirements**:
  - `rule` TR-12.1：未选角色运行禁用；选中后调用参数含 category/role_ref/symbol，question 留空不传也可（后端默认）
  - `rule` TR-12.2：409 响应显示进行中提示且不渲染重复运行视图；成功发起后 RunView 以该 runId 渲染（断言传参/mock RunView）
  - `rule` TR-12.3：历史按角色分组倒序、展开后用 MarkdownContent 渲染含表格的结论
  - `rule` TR-12.4：三个 Tab 分别请求各自分类目录；基本面财务数据缺省态
- **Notes**: 测试并入 WatchDetail.test.tsx 或 `components/watch/__tests__/AnalysisTab.test.tsx`

## Task 13: 技术面缠论专区（7 维历史表 + 时间筛选 + 展开）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 12
- **Description**:
  - 新建 `components/watch/ChanlunHistory.tsx`：技术面 Tab 内缠论角色运行结果专区；表格列 分析时间/symbol/缠论打分（−5~+5，正负着色）/结构置信度（百分比）；默认倒序；起止日期筛选（前缀比较，同 M14 教训）；行展开显示固定中英 7 维度（顺序与命名严格按 spec：结构读取/活跃支点/背驰/买卖点/多级别计划/艾略特验证/缠论打分 + 英文）；structured=false 记录展示原文与"非结构化返回"提示；进行中的缠论 run 在专区顶部显示状态（复用 AnalysisTab 的运行机制，缠论角色项有视觉标记）。
- **Acceptance Criteria Addressed**: AC-12, AC-13, AC-U1
- **Test Requirements**:
  - `rule` TR-13.1：mock 多条记录断言倒序、打分/置信度格式化（+3、78%）、日期筛选生效
  - `rule` TR-13.2：展开后 7 个维度中英标题齐全且顺序固定；非结构化记录显示原文+提示
- **Notes**: 测试 `components/watch/__tests__/ChanlunHistory.test.tsx`

## Task 14: 前端全量测试与构建
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 13
- **Description**:
  - 运行全量 `npx vitest run` 与 `make fe-build`（tsc + vite），修复类型/测试问题；不新增依赖；深色模式抽查。
- **Acceptance Criteria Addressed**: AC-U2
- **Test Requirements**:
  - `rule` TR-14.1：全量 vitest 退出码 0（既有 758+ 用例 + 新增无回归）
  - `rule` TR-14.2：fe-build 退出码 0
- **Notes**: 记录用例总数

## Task 15: 端到端走查与全门禁
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 7, Task 14
- **Description**:
  - `make lint` + `make test-fast` + `make fe-build` 最终复跑；启动后端+前端（scripts/dev 或现有方式），浏览器走查：导航→搜索加入（真实/录制品）→列表排序勾选→详情五子 Tab→发起一次分析（可用 mock LLM 或已配置通道；若环境无 LLM 则以历史 run 数据演示 RunView/缠论区）→缠论 7 维展示→取消关注→重新关注历史仍在；深浅色截图，按 AC-U1 rubric 打分。
  - 临时预览/录制入口走查后删除（M15 教训）。
- **Acceptance Criteria Addressed**: AC-U1, AC-U2
- **Test Requirements**:
  - `rule` TR-15.1：三条门禁命令输出全绿并记录
  - `rubric` TR-15.2：交互视觉质量；scale 1-5；anchors 同 AC-U1；threshold >= 4；evidence 浏览器截图与走查记录

## Task 16: 独立评审问题修复（FAIL → PASS）
- **Status**: `done`（第二轮 fresh-context 独立复审已给 **PASS**；复审建议项 1/2 已收口、3-6 登记 backlog，详见 review.md §4.4-§6）
- **Priority**: `high`
- **Depends On**: Task 15
- **Description**: 独立 fresh-context 评审结论 FAIL（见 review.md §6 前的问题清单），逐项修复并回归：
  - **B1（阻塞，数据损坏）**：`WatchlistStore.update_meta` 循环缺 symbol 守卫，多标的清单下刷新任一标的会覆盖第一行 name/industry/updated_at（store.py:172-192）。加匹配守卫；补"两行清单刷新第二行第一行不变"回归测试（store + routes）。
  - **B2（阻塞，AC-11）**：分析历史 DTO 仅 280 字 excerpt、已完成行无入口。后端 analyses DTO 增加完整 `final_report`；前端历史展开以 MarkdownContent 渲染完整正文，所有状态行提供"查看运行"只读 RunView 入口；测试契约改断言全文。
  - **I4（AC-3 字面要求）**：取关后 objective/analyses/chanlun 三个 GET 仍应按 symbol 返回历史（当前 404）。移除三处 `_entry_or_404` 关注态强制（symbol 仍规范化校验），更新固化 404 的测试为 200+历史保留。
  - **I1（AC-2/FR-2）**：搜索候选必须含行业。search 路由对候选 secid 批量复用 ulist（≤20 一次请求）补 industry；补测试。
  - **I2（AC-16）**：缠论徽章硬编码中文改 i18n（9 语言新键 watch.an.chanlunBadge）。
  - **I3（FR-13）**：详情页非 404 加载失败要有明确原因+重试 UI，不渲染空白壳。
  - **I5（FR-7）**：补充抓取发起后归档区可见"进行中"提示；切回客观 Tab 自动重拉，完成后无需手动刷新即可见。
  - **N2**：GET /watch/list 的批量快照合并为一次 JSON 写回（消除 N 次读改写与 lost-update 竞态）。
  - **N3**：instrument_master.source 写死 "akshare" 改为实际来源 "eastmoney"。
  - **N4**：symbol 号段收紧排除 B 股（900xxx 沪 B、200xxx 深 B），更新合法号段测试。
  - **N6**：role_run symbol 归属改词边界匹配，避免问题文本含代码跨标的误归档。
  - **N7**：基本面 Tab 仅复用财务分区 RawTable，不显示补充抓取输入区（按 T11 既定设计）。
  - **N8**：列表取消关注失败补 catch 与错误反馈。
  - **N10**：watchlist.json 损坏降级时 logger.warning 留痕。
  - **N1**：清理 9 语言 5 个死键（an.financialTitle/an.purpose/an.running/ch.inProgress/rec.payload）——注意 an.running 删除前确认已无引用。
  - 已知限制（不改，记入 review）：N5 时间本地化、N9 多 worker 409 原子性。
- **Acceptance Criteria Addressed**: AC-2, AC-3, AC-7, AC-11, AC-13, AC-14, AC-16, AC-U2
- **Test Requirements**:
  - `rule` TR-16.1：B1 两行清单回归；B2 全文断言 + 已完成行 View run 入口；I4 取关后三端点 200 历史保留
  - `rule` TR-16.2：I1 候选行业非空；N4 B 股代码被拒；N6 词边界归档
  - `rule` TR-16.3：全门禁复跑全绿
