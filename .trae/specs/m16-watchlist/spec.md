# M16 关注（自选标的）模块 — 产品需求规格

## Overview

- **Summary**：在左侧导航新增一级菜单【关注】（路由 `/watch`，Star 图标），面向全部投资者提供"自选 A 股标的管理 + 单标的深度投研分析"一体化工作台。模块含两个页面：**标的列表页**（默认，添加/浏览/排序/勾选/逐行取消关注）与**标的详情页**（`/watch/:symbol`，含 概览 / 客观数据 / 基本面 / 技术面 / AI 分析 五个子 Tab）。基本面、技术面、AI 分析复用平台**已发布**的 swarm 单角色运行（role_run）能力发起分析并长期留存；缠论分析结果按固定 7 维度结构化入库（DuckDB）展示；【AI 批量对比】本期仅 UI 占位。
- **Purpose**：让投资者在一个业务模块内完成自选维护、标的画像取数更新、客观原始数据查看与智能体补充抓取、基本面/技术面/综合 AI 投研分析，且全部分析记录可长期追溯、取消关注不丢历史。
- **Target Users**：全部投资者（本地 loopback 部署，单运行实例；"个人私有"以本机运行画像 `runtime_root` 为隔离边界，与现有 roles/skills/teams 存储口径一致）。

## Goals

- 自选 A 股清单：代码/名称模糊搜索加入、去重拦截、核心指标列表（名称代码/行业/现价/总市值/PE/PB）、列排序、行勾选、逐行二次确认取消关注。
- 标的详情：概览基础画像 + 两个**不走 AI** 的直接取数更新按钮；客观数据展示平台已有标准化原始数据 + 智能体补充抓取归档；三个分析 Tab 复用已发布角色执行 role_run，自动附带标的信息、可选填补充诉求、必选一个角色才可运行、串行不并行、进行中防重复。
- 缠论：识别 `Chanlun (Chan Theory) Analyst` 角色，运行完成后按固定中英 7 维度结构化解析入库，打分 −5~+5、置信度 0–100%；历史按时间倒序、支持时间范围筛选、逐条展开。
- 全部分析历史按"角色 + 时间"长期保留；取消关注仅移除清单关系，历史与归档数据在重新关注后完整可回看。
- 结论渲染复用 M15 的 `components/common/MarkdownContent`（业务文档级排版）。

## Non-Goals

- 不开发 AI 批量对比功能（仅按钮占位与"后续版本提供"提示）。
- 不支持 A 股以外市场（港股/美股/外汇/加密均不在范围）。
- 不新建智能体、不改角色/技能审批体系、不改 swarm 执行引擎；本模块只消费已发布角色。
- 勾选行本期不提供任何批量动作（无批量移除/批量运行）。
- 不做客观数据的标准化加工/图表化（仅原始数据分类展示）；基本面 Tab 的原始财务数据"暂无"时不做兜底计算。
- 不做多用户账户体系/服务端租户隔离（沿用本机单画像口径）。
- 不新增第三方前端依赖。

## Background & Context

- 路由：`frontend/src/router.tsx:66-91` 集中注册表；左侧菜单在 `frontend/src/components/layout/Layout.tsx:22-36`（NAV 数组，icon + i18n key），现有 `/skills`（Sparkles）是最近一次新增同级菜单的范本。
- 前端 API 封装：`frontend/src/lib/api.ts:443-758`（request 助手、`createRoleRun` L741、`listRoleRuns` L746、`swarmSseUrl` L606、`getSwarmRun` L605）；SSE 用 `hooks/useSSE.ts`；运行视图复用 `components/swarm/RunView.tsx`（RoleSquare L674 已用它渲染单角色运行）；通用确认弹窗 `components/common/ConfirmDialog.tsx`；文档渲染 `components/common/MarkdownContent.tsx`。
- 角色目录：`agent/src/swarm/role_catalog.py` 提供 `list_approved_role_refs()`（已批准扁平目录：内置 preset 角色 + approved 自建角色），条目含 `ref/name/purpose`；**角色无分类字段**。内置角色 ref 形如 `technical_analysis_panel:chanlun_analyst`，其展示名为 `Chanlun (Chan Theory) Analyst`（preset YAML L234-355，其 Required outputs 正好是本模块要求的 7 维度）。
- 角色运行：`POST /swarm/role-runs`（`api/swarm_routes.py:1042-1068`）→ `SwarmRuntime.start_run(role_run={role_ref,target,question})`；`build_role_run()`（`swarm/role_runs.py:51-120`）**强制 target、question 非空**，因此"可选诉求"留空时由后端注入按 Tab 分类生成的默认研究问题（内含标的 symbol/名称）。历史查询 `GET /swarm/role-runs?target=&role_ref=&from=&to=`，run 明细含 `final_report/tasks/events`，SSE 端点 `/swarm/runs/{id}/events`。
- 行情取数（均为无 Key、IP 友好链路）：Eastmoney push2 `clist`（经共享限流器 `backtest/loaders/eastmoney_client.py`）可按关键字搜 A 股并返回 f12 代码/f14 名称/f2 现价/f9 PE/f23 PB/f20 总市值/f100 行业；`market_screener_tool.py:30-52` 已有该端点封装范本。个股 F10（上市时间/行业/总股本等）可走 akshare `stock_individual_info_em()`（依赖已在 pyproject）。统一 OHLCV 入口 `src/market_data.py:fetch_market_data()`。
- DuckDB：本地仓库 `~/.vibe-trading/data/market.duckdb`（`scripts/local_db/schema.sql` 已定义 instrument_master / daily_bar / valuation_daily / financial_statement 等表；`init_local_db.py:48` 现为硬编码 Path.home，尚未有遵循 VIBE_TRADING_HOME 的路径助手）。新增表用 `CREATE TABLE IF NOT EXISTS` 幂等建表。
- 宏模块是最近似的分层范本：L2 业务包 `src/macro/`（db/models/repository/service）+ L4 `src/api/macro_routes.py` + api_server 挂载（L267-268）。路由模块统一通过 `sys.modules` 取宿主 `require_auth`（swarm_routes.py:102-114）。
- 路径约定：`src/config/paths.py` 集中管理 runtime_root 子目录；测试沙箱重定向 HOME 并有"真实 ledger 不得被触碰"守卫（conftest），新存储必须落在 runtime_root 下。
- 分层门禁：新包按 L2 业务包组织（建议名 `watchlist`），仅允许向上依赖 L3（swarm）/L1/L0；**不得新增反向边**（layer-map.json 冻结 8 条）。L4 路由薄封装，业务逻辑放 L2。
- i18n：9 语言文件 `frontend/src/i18n/locales/{en,zh-CN,ja,ko,de,es,pt-BR,id,ar}.json`，新文案统一加 `watch.*` 命名空间与 `layout.watch`。

## Functional Requirements

- **FR-1 导航与路由**：左侧导航在【技能广场】之后新增一级菜单【关注】（Star 图标，`layout.watch`）；点击进入 `/watch` 标的列表页（模块默认页）；列表行【查看】进入 `/watch/:symbol` 详情页，详情页头部可返回列表；详情页直接刷新/分享 URL 可独立加载（自动取 symbol 加载数据）。
- **FR-2 添加标的（搜索）**：列表页右上【添加标的】弹出搜索框，输入代码或名称关键字，后端在 A 股范围模糊匹配，返回候选（代码、名称、行业）；支持输入纯 6 位代码；选中候选即加入；无结果明确提示；无数量上限。
- **FR-3 去重与移除**：同一 symbol 不可重复关注，重复加入后端拒绝（409）并提示"该标的已在关注列表中"；每行可触发"取消关注"，弹窗二次确认，确认后仅删除清单关系；不提供勾选批量动作。
- **FR-4 列表能力**：列表每行展示 名称/代码、所属行业、现价、总市值、PE、PB 与【查看】；现价/总市值/PE/PB 列点击在升/降序间切换；每行有勾选框（勾选态仅视觉标记，无批量操作）；空清单展示空状态与添加入口。数据缺失字段显示"暂无数据"占位。
- **FR-5 概览画像与取数更新**：概览展示 名称、代码、行业、现价、总市值、IPO 日期、注册资本（及更新时间）；【更新股价与估值】【更新获取基本信息】两个按钮分别直连数据 API 刷新（**严禁调用 LLM/智能体**），成功后回显最新值与更新时间，并把估值/主数据快照幂等写入 DuckDB；失败按 FR-13 处理。
- **FR-6 客观数据-标准原始数据**：客观数据 Tab 分类展示平台已有原始数据（行情 daily_bar、估值 valuation_daily、财报 financial_statement、主数据 instrument_master），以原始形态呈现、不做主观加工；表不存在或无记录时该分类显示"暂无数据"。
- **FR-7 客观数据-智能体补充抓取**：提供"补充抓取"输入区，投资者用自然语言描述所需数据后发起；后端以指定的内置数据研究类角色发起一次 role_run（自动附带 symbol/名称与数据需求），完成后把产出（需求描述、内容、来源、run_id、时间）归档到 DuckDB 新表并在本 Tab 展示；归档数据归标的所有（本机共享，其他进入同一标的的用户可见）；失败不覆盖任何已有数据。
- **FR-8 已发布角色分类目录**：三个分析 Tab 各自只列出**已发布**角色：基本面 Tab=基本面类、技术面 Tab=技术面类（含缠论角色）、AI 分析 Tab=通用投研类。分类由后端确定性规则产出（见 Assumptions），并在每个条目中给前端提供 `category` 与 `is_chanlun` 标记；未批准角色不出现。
- **FR-9 发起分析**：必须且只能选中一个角色后【运行】才可点击（未选中禁用并提示）；不提供并行/多选；发起时后端自动把当前标的 symbol/名称注入目标上下文，用户补充诉求可选填，留空则使用该 Tab 的默认研究问题；串行执行（复用 swarm role_run 队列）。
- **FR-10 进行中防重复**：同一标的同一角色存在 pending/running 的 role_run 时，再次发起返回 409，前端展示"该智能体分析进行中"状态，不产生第二条记录；进行中的运行通过 SSE 展示实时状态（复用 RunView）。
- **FR-11 分析历史留存**：三个 Tab 展示本标的本类角色的历史结果，按角色分组、分析时间倒序，可逐条展开，正文用 MarkdownContent 业务文档级渲染（标题/段落/列表/表格/强调）；历史长期保留、不自动清理。
- **FR-12 缠论结构化**：当运行的角色为缠论角色时，运行完成后后端将最终报告解析为固定 7 维度（1 结构读取 Structure read / 2 活跃支点 Active pivots / 3 背驰 Divergence / 4 买卖点 Buy/sell points / 5 多级别计划 Multi-level plan / 6 艾略特验证 Elliott corroboration / 7 缠论打分 Chanlun score），绑定 symbol 与分析时间写入 DuckDB；打分限定 −5~+5（含），结构置信度限定 0–100%；解析失败时不伪造维度，该条标记为"非结构化返回"并保留原文可查看。
- **FR-13 异常处理**：取数更新、补充抓取、分析发起/执行失败或超时时，页面明确提示原因并提供重试；任何失败不得覆盖、清空既有数据与历史；无数据字段统一"暂无数据"；不阻断页面其余区域。
- **FR-14 AI 批量对比占位**：列表页保留【AI 批量对比】按钮，点击仅提示"功能将在后续版本提供"，不发起任何请求/分析。
- **FR-15 多语言**：新增文案在 9 个语言文件齐全（命名空间 `watch.*` + `layout.watch`），无 raw key、无缺失语言条目。

## Non-Functional Requirements

- **NFR-1 工程门禁**：`make lint`（含 lint-deps 分层门禁、ruff、安全扫描）、`make test-fast`（unit 标记）、前端 `npx vitest run` 与 `make fe-build`（tsc）全部通过；新增后端逻辑具备不依赖网络/Key 的单元测试（HTTP 与行情函数全部可注入 mock）。
- **NFR-2 性能**：列表行情快照按"已关注 symbol 批量一次请求"刷新，不为每行单独发 HTTP；搜索请求防抖（≥300ms）；分析历史与缠论历史走分页/上限（默认 20、上限 100，与现有 role-runs 一致）。
- **NFR-3 数据安全**：所有 DuckDB 写入为短连接、参数化 SQL、幂等 upsert；新存储路径全部位于 runtime_root / 市场库内，测试沙箱下不触碰真实 `~/.vibe-trading`；不读取 config 之外的环境变量（env 门禁）。
- **NFR-4 视觉一致**：沿用 Tailwind design token 与现有页面（SkillPlaza/RoleSquare）卡片/表格/弹窗风格与深色模式；不引入新依赖、不加自定义 CSS 文件。
- **NFR-5 可访问性**：Tab、按钮、勾选、弹窗具备 aria 标签与键盘可达性，遵循 RunView M15 已落地的可访问性模式。

## Constraints

- **Technical**：后端 FastAPI 路由薄封装 + L2 业务包；pydantic 模型 + JSON/DuckDB 存储；前端 React 19 + TS + Tailwind + react-router + react-i18next + vitest；复用 RunView/useSSE/MarkdownContent/ConfirmDialog。
- **Business**：仅 A 股；只调用已发布角色；本期不做 AI 批量对比；分析单角色串行；取消关注不删历史。
- **Dependencies**：行情依赖 Eastmoney/akshare 免费链路（网络仅在真实运行时发生，测试 mock）；DuckDB 依赖已在 pyproject；无新前端依赖。
- **分层**：新增 `src/watchlist`（L2）+ `src/api/watchlist_routes.py`（L4）；禁止新增 grandfathered reverse edges。

## Assumptions

- **角色三分类规则（无原生分类字段，需在审批环节确认的产品规则）**：后端用确定性规则给已发布角色打 category：
  - `technical`：内置 `technical_analysis_panel` preset 下全部角色，或角色名/purpose 命中技术面关键词（技术面/技术分析/缠论/Chanlun/Elliott/波浪/Ichimoku/SMC/K线/均线/MACD 等）；其中 ref 为 `technical_analysis_panel:chanlun_analyst` 或名称精确匹配 `Chanlun (Chan Theory) Analyst` 标记 `is_chanlun=true`。
  - `fundamental`：内置 `fundamental_research_team / earnings_research_team / equity_research_team / value_investing_committee` 下角色，或命中基本面关键词（基本面/财务/财报/盈利/估值/价值/Fundamental/Financial/Earnings）。
  - `general`：其余全部已发布角色（通用投研/综合研判/宏观/行业等）。
  - 规则在单一模块内集中维护并单元测试固化；后续若平台为角色增加原生分类字段，切换数据源即可。
- **默认研究问题**：用户留空补充诉求时，后端按 Tab 注入中文默认问题模板（如"对标的 {name}（{symbol}）执行完整的基本面/技术面/综合投研分析并给出结构化结论"），满足 build_role_run 非空校验，且确保标的信息随运行传递。
- **补充抓取执行角色**：使用内置 `equity_research_team`（或同类具备 get_market_data 等数据工具）中的一个数据研究角色作为系统指定角色，前端不提供选择；若该内置角色未来不可用，后端返回明确错误而非静默降级到 LLM 之外的通道。
- **注册资本字段**：免费链路可能不返回注册资本，取不到时显示"暂无数据"，不作为取数失败。
- **symbol 规范**：统一使用工程规范代码（600519.SH / 000001.SZ / 8xxxxx.BJ）；搜索结果做代码→规范 symbol 转换（按交易所号段/市场前缀）。
- **快照刷新时机**：进入列表页时批量拉取一次最新快照；不做后台轮询。详情概览的现价以手动"更新"与进入详情时拉取为准。
- 缠论报告解析为**尽力而为**：现有缠论角色 prompt 已强制 7 段输出与分值范围，但 LLM 输出存在波动，故允许"非结构化返回"兜底展示，绝不编造维度数值。

## Acceptance Criteria

### AC-1: 导航入口与模块路由
- **Type**: `rule`
- **Given**: 投资者打开平台
- **When**: 查看左侧导航并点击【关注】
- **Then**: 导航存在 Star 图标的一级菜单【关注】（位于技能广场之后）；点击进入 `/watch` 标的列表页（默认页）；列表【查看】跳转 `/watch/:symbol` 详情页且默认停留在"概览"子 Tab；详情页有返回列表入口；直接访问详情 URL 可独立加载
- **Pass Condition**: 路由表注册 `/watch` 与 `/watch/:symbol`；NAV 含新项；vitest 断言菜单与跳转
- **Evidence**: router.tsx、Layout.tsx 代码 + 前端测试

### AC-2: A股搜索添加与候选字段
- **Type**: `rule`
- **Given**: 空或已有自选的清单
- **When**: 打开添加弹窗，输入代码/名称关键字（含纯 6 位代码）并选中候选
- **Then**: 仅在 A 股范围返回匹配候选（代码、名称、行业），选中后清单出现该标的并展示核心字段；无匹配时提示无结果；加入不设数量上限
- **Pass Condition**: 后端搜索服务单测（注入 clist 响应）+ 路由测试 + 前端弹窗测试
- **Evidence**: watchlist 市场服务测试、watchlist_routes 测试、Watchlist 页面测试

### AC-3: 重复关注拦截与逐行取消关注
- **Type**: `rule`
- **Given**: 某 symbol 已在清单
- **When**: 再次加入同一标的 → 后端 409 且提示"已在关注列表中"，不产生重复行；对某行点取消关注并在二次确认中确认 → 该标的从清单消失但历史分析/归档数据仍可按 symbol 查到；取消确认弹窗则保留
- **Pass Condition**: store 去重单测（重复加入抛错）、路由 409 测试、删除后分析/客观数据查询仍返回历史；前端 ConfirmDialog 两分支测试
- **Evidence**: 后端 test_watchlist_store / test_watchlist_routes + 前端测试

### AC-4: 列表字段、排序、勾选与空状态
- **Type**: `rule`
- **Given**: 清单含多只标的（含指标缺失者）
- **When**: 浏览列表、点击现价/总市值/PE/PB 列头排序、勾选若干行
- **Then**: 列字段齐全（名称/代码、行业、现价、总市值、PE、PB、查看）；排序在升/降序切换且缺失值不报错；勾选仅视觉标记无任何批量动作入口；缺失字段显示"暂无数据"；空清单显示空状态与添加入口
- **Pass Condition**: 前端组件测试覆盖排序两方向、勾选态、缺值占位、空状态；快照为一次批量请求（NFR-2，单测断言只调用一次批量取数）
- **Evidence**: Watchlist.test.tsx

### AC-5: 概览画像与两个直接取数更新
- **Type**: `rule`
- **Given**: 进入某标的详情概览 Tab
- **When**: 查看画像；点击【更新股价与估值】、【更新获取基本信息】
- **Then**: 展示名称/代码/行业/现价/总市值/IPO日期/注册资本与更新时间，缺项显示"暂无数据"；两个更新动作只调用行情/F10 数据通道（测试中验证未实例化/调用任何 LLM 或 swarm runtime），成功后回显并幂等写入 instrument_master/valuation_daily；显示更新时间
- **Pass Condition**: 服务测试断言更新路径不触达 runtime/LLM（mock 监测零调用）、DuckDB upsert 可重复执行结果一致；路由测试
- **Evidence**: test_watchlist_market_service、test_watchlist_db、test_watchlist_routes

### AC-6: 客观数据标准原始数据展示
- **Type**: `rule`
- **Given**: 市场库存在/不存在相关表或记录
- **When**: 打开客观数据 Tab
- **Then**: 分类展示行情/估值/财报/主数据已有原始记录（原始值、带来源/日期），不做加工；无表/无记录的分类显示"暂无数据"且不报错
- **Pass Condition**: repository 单测（有数据/空库两分支）+ 前端渲染测试
- **Evidence**: test_watchlist_objective_repository、WatchDetail 测试

### AC-7: 智能体补充抓取归档与共享
- **Type**: `rule`
- **Given**: 投资者在客观数据 Tab 输入数据需求并发起
- **When**: 角色运行完成
- **Then**: 后端以系统指定内置数据研究角色发起 role_run（payload 含 symbol/名称/需求文本）；产出归档至 DuckDB 新表（symbol、需求、内容、来源、run_id、时间），随后本 Tab 可见；抓取失败/超时不覆盖任何既有数据并返回可重试错误
- **Pass Condition**: 服务测试（mock runtime 成功/失败两路径）验证归档行字段与失败不写入；表 DDL 幂等
- **Evidence**: test_watchlist_fetch_service、test_watchlist_db

### AC-8: 已发布角色三分类目录与缠论标记
- **Type**: `rule`
- **Given**: 平台存在若干内置与自建（含未批准）角色
- **When**: 分别请求 fundamental/technical/general 三类可选角色目录
- **Then**: 每类仅含已批准且命中该类确定性规则的角色，条目含 ref/name/purpose/category/is_chanlun；未批准自建角色不出现；缠论角色唯一落在 technical 且 is_chanlun=true；分类规则有固化单测
- **Pass Condition**: 分类纯函数单测覆盖内置 preset 代表角色、关键词命中、未批准过滤、缠论识别
- **Evidence**: test_watchlist_role_catalog

### AC-9: 发起分析：必选一个、自动附带标的、诉求可选
- **Type**: `rule`
- **Given**: 在任一分析 Tab
- **When**: 未选角色时运行按钮禁用并有提示；选中一个角色（诉求留空/填写两种情况）后运行
- **Then**: 未选不能发起；后端校验 role_ref 属于该 Tab 分类且已批准，否则 400；发起 payload 的 target 含规范 symbol，question 含标的名称（留空时为后端默认问题模板）；一次仅运行一个角色（无并行入口）
- **Pass Condition**: 路由测试（无角色/未批准/错类 → 400；正常 → run 建立且 target/question 含标的上下文）；前端禁用态测试
- **Evidence**: test_watchlist_analysis_routes、WatchDetail.test

### AC-10: 进行中防重复（409）
- **Type**: `rule`
- **Given**: 同 symbol + 同 role_ref 已有 pending/running 的 role_run
- **When**: 再次发起
- **Then**: 返回 409 且前端提示"该智能体分析进行中"并展示进行中状态；不创建第二条 run 记录；进行中超时/僵尸由现有 swarm stale 机制回收后可再次发起
- **Pass Condition**: 服务测试构造进行中 run 断言 409 与 store 中 run 数量不变
- **Evidence**: test_watchlist_analysis_service

### AC-11: 分析历史长期留存与回看
- **Type**: `rule`
- **Given**: 同一标的存在多角色多次 role_run（含已完成与失败）
- **When**: 打开对应分析 Tab
- **Then**: 历史按角色分组、时间倒序列出（支持分页参数），逐条可展开查看完整结论，正文以 MarkdownContent 渲染（表格/标题/列表样式生效）；取消关注再重新关注后历史完整可见
- **Pass Condition**: 路由过滤测试（symbol/角色/时间）+ 重新关注可见性测试；前端断言历史区使用 MarkdownContent
- **Evidence**: test_watchlist_routes、WatchDetail.test

### AC-12: 缠论7维度结构化入库与取值约束
- **Type**: `rule`
- **Given**: 一次缠论角色运行完成并产出 7 段报告
- **When**: 后端解析完成回调
- **Then**: DuckDB `chanlun_analysis` 新增一行，含 symbol、run_id、分析时间、7 个固定维度文本（中英名称固定）、score ∈ [−5,+5] 整数、confidence ∈ [0,1]；越界值被拒绝（该行落非结构化兜底，不写伪造值）；非 7 段输出时标记 structured=false 并保留原文
- **Pass Condition**: 解析纯函数单测：标准 7 段样例、分值越界、缺段、置信度格式（78%/0.78 两写法）四组用例；DB CHECK/约束测试
- **Evidence**: test_chanlun_parser、test_watchlist_db

### AC-13: 缠论历史倒序、时间筛选与展开
- **Type**: `rule`
- **Given**: 标的有多条缠论记录
- **When**: 打开技术面 Tab 缠论区
- **Then**: 默认按分析时间倒序列出 symbol/时间/打分/置信度；支持起止日期筛选；点开记录展示完整 7 维度；非结构化记录展示原文与提示
- **Pass Condition**: 路由测试（倒序、日期过滤）+ 前端列表/展开测试
- **Evidence**: test_watchlist_routes、WatchDetail.test

### AC-14: 失败与无数据不破坏旧数据
- **Type**: `rule`
- **Given**: 取数/抓取/分析任一环节失败、超时或无数据
- **When**: 触发对应操作
- **Then**: UI 明确提示原因且提供重试；既有 DuckDB 数据、JSON 清单、历史 run 均不被覆盖或删除；无数据字段显示"暂无数据"；页面其余区域可正常操作
- **Pass Condition**: 服务测试断言失败路径无写/删操作（mock 计数）；前端错误态测试
- **Evidence**: test_watchlist_market_service、WatchDetail.test

### AC-15: AI批量对比占位
- **Type**: `rule`
- **Given**: 列表页存在【AI 批量对比】按钮
- **When**: 点击
- **Then**: 仅出现"功能将在后续版本提供"提示；不发起任何后端请求（测试断言无网络调用）
- **Pass Condition**: 前端测试断言提示出现且 api 未被调用
- **Evidence**: Watchlist.test.tsx

### AC-16: 多语言 9 语言齐全
- **Type**: `rule`
- **Given**: 9 个语言文件
- **When**: 检查 watch 命名空间与 layout.watch
- **Then**: 每个语言文件均含相同键集合，页面在英文/中文下无 raw key
- **Pass Condition**: 现有 i18n 键完整性测试（或新增断言）通过；手工切换两语言验证
- **Evidence**: i18n.test.ts / 新增测试

### AC-17: 分层门禁与环境变量门禁
- **Type**: `rule`
- **Given**: 新代码落位 src/watchlist(L2)、src/api/watchlist_routes.py(L4)、config/paths.py 扩展
- **When**: 运行 `scripts/lint-deps`、`tools/ci_env_var_gate.py`、ruff
- **Then**: 无新增反向边、watchlist 不出现 os.getenv/os.environ、无 F821 等硬性 ruff 违规
- **Pass Condition**: `make lint` 全绿；layer-map.json 无需修改
- **Evidence**: lint 命令输出

### AC-U1: 页面交互与视觉质量
- **Type**: `rubric`
- **Dimension**: 关注模块两页面的信息架构、交互流畅度与视觉一致性
- **Scale**: 1-5
- **Anchors**: 1=布局混乱、关键操作缺失或不可达；3=功能齐备但样式/交互与平台现有页面有明显割裂；5=与 RoleSquare/SkillPlaza 风格统一、五 Tab 结构清晰、列表排序/勾选/弹窗/历史展开/缠论 7 维表均直观可用、深色模式正常
- **Pass Threshold**: >= 4
- **Evidence**: 浏览器实际渲染走查（列表→添加→详情五子 Tab→发起分析→缠论历史）截图评审

### AC-U2: 测试与门禁质量
- **Type**: `rubric`
- **Dimension**: 新增功能的自动化证据充分度
- **Scale**: 1-5
- **Anchors**: 1=无测试或依赖真实网络/Key；3=主路径有测试但边界（去重/409/解析失败/空库）缺失；5=后端存储/分类/解析/路由与前端交互全覆盖且全部离线可跑、门禁全绿
- **Pass Threshold**: >= 4
- **Evidence**: make lint / make test-fast / vitest / fe-build 输出与新增测试清单

## Open Questions

- [x] 用户范围：全部投资者开放，自选清单个人私有（HITL 确认：本地画像隔离）。
- [x] 市场范围：仅 A 股。
- [x] 分析留存：全部长期保留，按角色 + 时间回看；取消关注不删除。
- [x] 执行方式：必选一个角色、串行、诉求可选、自动附带标的。
- [x] 勾选：仅 UI，无批量动作；移除走逐行二次确认。
- [x] 添加：代码/名称模糊搜索、选中即加入、去重、无上限。
- [x] 客观数据：已有标准原始数据 + 智能体补充抓取归档（共享）。
- [x] 异常：明确原因 + 重试 + 不覆盖旧数据 + 暂无数据占位。
- [x] 进行中：拦截重复发起；超时可重试不产生重复记录。
- [x] 结论渲染：业务文档级渲染；缠论额外固定 7 维结构化。
- [x] 缠论历史：倒序 + 时间筛选 + 逐条展开。
- [ ] 角色三分类规则为后端确定性关键词/preset 映射（见 Assumptions），请在审批时确认该规则口径；补充抓取的系统指定角色一并确认。
