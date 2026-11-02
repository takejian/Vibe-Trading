# 投资名人持仓 & 言论跟踪 实现计划

## 仓库研究结论

**前端**（React 19 + Vite + TypeScript + Tailwind）：
- 左侧菜单配置：`frontend/src/components/layout/Layout.tsx` 的 `NAV` 数组（`to`/`icon`/`label`），新增菜单项即在此追加。
- 路由：`frontend/src/router.tsx` 用 `lazy(() => import(...))` + `createBrowserRouter`，新增页面需注册路由。
- API 层：`frontend/src/lib/api.ts` 的 `request` 封装 + 类型化方法（参考 `goldCurrent`/`goldRefresh` 等）。
- i18n：`frontend/src/i18n/locales/*.json` 的 `layout.*` 键。
- 参考页面：`frontend/src/pages/GoldMonitor.tsx`（Tab 切换、加载状态、LLM 刷新交互）。

**后端**（FastAPI + DuckDB + ChatLLM）：
- 路由注册：`agent/src/api/gold_routes.py` 的 `register_*_routes(app)` 模式，在 `agent/api_server.py` 中调用。
- 数据存储：`agent/src/gold_monitor/db.py` —— 共享 market warehouse DuckDB（`get_market_db_path()`），短连接 + `initialize_schema` + DDL 建表。
- LLM 调用：`from src.providers.chat import ChatLLM`，`llm.chat(messages, timeout=...)`，配合 `_extract_json` 解析返回。
- 定时任务：`agent/src/gold_monitor/scheduler.py` —— `start_*_scheduler(app)` / `stop_*_scheduler(app)`，`asyncio.create_task(_refresh_loop)`，在 `agent/src/api/lifecycle.py` lifespan 中启动/停止。
- 认证：所有路由挂 `Depends(require_auth)`。

## 涉及文件与模块

### 后端新增
- `agent/src/celebrity/__init__.py`
- `agent/src/celebrity/db.py` — DuckDB 表结构与 CRUD
- `agent/src/celebrity/prompts.py` — 5 套内置提示词常量
- `agent/src/celebrity/service.py` — 业务逻辑（刷新/复查/回灌/绩效/周动态）
- `agent/src/celebrity/scheduler.py` — 每周日 04:00 定时刷新
- `agent/src/api/celebrity_routes.py` — REST API 端点

### 后端修改
- `agent/api_server.py` — 注册 `register_celebrity_routes(app)`
- `agent/src/api/lifecycle.py` — 启动/停止 celebrity 定时任务

### 前端新增
- `frontend/src/pages/InvestorCelebrity.tsx` — 主页面（Tab：投资人详情 / 名人周动态）
- `frontend/src/components/celebrity/InvestorCard.tsx` — 单投资人卡片
- `frontend/src/components/celebrity/WeeklyDynamics.tsx` — 名人周动态聚合视图
- `frontend/src/components/celebrity/PromptEditorDialog.tsx` — 提示词查看/编辑弹窗

### 前端修改
- `frontend/src/components/layout/Layout.tsx` — NAV 增加「投资名人」菜单项
- `frontend/src/router.tsx` — 注册 `/investor-celebrity` 路由
- `frontend/src/lib/api.ts` — 增加 celebrity 相关 API 方法与类型
- `frontend/src/i18n/locales/zh-CN.json` 等 — 增加 `layout.investorCelebrity` 文案

## 实现步骤（依赖顺序）

### 步骤 1：后端数据层（db.py + prompts.py）
1. 创建 `agent/src/celebrity/` 包。
2. `db.py`：定义 DuckDB 表：
   - `celebrity_investor`（id, name, invest_style, remark, is_builtin, created_at, updated_at）
   - `celebrity_position`（id, investor_id, target, direction, source, update_time, confidence, created_at）
   - `celebrity_opinion`（id, investor_id, publish_time, content, source, confidence, review_result, is_latest, created_at）
   - `celebrity_adjust`（id, investor_id, time, action, target, profit_desc, source, review_result, created_at）
   - `celebrity_performance`（id, investor_id, recent_performance, return_1y..10y, max_drawdown, stability_tag, stability_desc, peer_compare, risk_note, created_at）
   - `celebrity_prompt`（prompt_key, content, updated_at）
3. `initialize_schema()`：建表 + 种子预置投资人（冯柳、段永平、巴菲特、李录、邱国鹭、张磊）+ 种子 5 套提示词。
4. 实现 CRUD：投资人增删查、持仓/观点/调仓按时间线追加（去重）、绩效 upsert、提示词读写。
5. `prompts.py`：内置 5 套提示词文本（来自 BDD 附录 A）。

### 步骤 2：后端业务逻辑（service.py）
1. `list_investors()` / `add_investor()` / `delete_investor()`（仅非内置可删）。
2. `get_investor_card(investor_id)`：聚合返回名称、风格、绩效、持仓、最新观点、历史观点、调仓动向。
3. `refresh_investor(investor_id)`：调用「最新动态提示词」→ ChatLLM → 解析 JSON → 持仓/观点/调仓按时间线追加（去重）。空数据返回 `no_new_info`。
4. `backfill_history(investor_id)`：调用「历史回灌提示词」→ 追加历史持仓与观点。
5. `get_performance(investor_id)` / `save_performance(investor_id, data)`：调用「绩效评价提示词」或手动保存。
6. `review_opinions(investor_id, items)`：调用「观点复查提示词」→ 回填 confidence + review_result。
7. `review_adjusts(investor_id, items)`：调用「调仓复查提示词」→ 回填 profit_desc + review_result。
8. `get_weekly_dynamics()`：聚合全部投资人的最新观点 + 最新调仓，按更新时间倒序分组。
9. `get_prompt(key)` / `update_prompt(key, content)`。
10. `update_invest_style(investor_id, style)`。
11. 公共 LLM 调用 + JSON 提取工具函数（复用 gold_monitor 的 `_extract_json` 模式）。

### 步骤 3：后端 API 路由（celebrity_routes.py）
- `GET /api/celebrity/investors` — 投资人列表
- `POST /api/celebrity/investors` — 新增投资人（name, invest_style, remark）
- `DELETE /api/celebrity/investors/{investor_id}` — 删除（仅非内置）
- `GET /api/celebrity/investors/{investor_id}/card` — 完整卡片
- `POST /api/celebrity/investors/{investor_id}/refresh` — 手动刷新
- `POST /api/celebrity/investors/{investor_id}/backfill` — 历史回灌
- `GET /api/celebrity/investors/{investor_id}/performance` — 获取绩效
- `POST /api/celebrity/investors/{investor_id}/performance` — 触发生成绩效
- `PUT /api/celebrity/investors/{investor_id}/performance` — 手动保存绩效
- `PUT /api/celebrity/investors/{investor_id}/style` — 更新投资风格
- `POST /api/celebrity/review/opinions` — 观点复查（body: investor_id, items[]）
- `POST /api/celebrity/review/adjusts` — 调仓复查
- `GET /api/celebrity/weekly` — 名人周动态聚合
- `GET /api/celebrity/prompts/{key}` — 获取提示词
- `PUT /api/celebrity/prompts/{key}` — 更新提示词

### 步骤 4：后端定时任务（scheduler.py）+ 注册
1. `scheduler.py`：`start_celebrity_scheduler(app)` / `stop_celebrity_scheduler(app)`，循环每周日 04:00 调用 `refresh_all_investors()`（逐个刷新）。
2. `api_server.py`：`from src.api.celebrity_routes import register_celebrity_routes; register_celebrity_routes(app)`。
3. `lifecycle.py`：在 lifespan 中 import 并 `start_celebrity_scheduler(app)` / `stop_celebrity_scheduler(app)`。

### 步骤 5：前端 API 层（api.ts）
- 增加 `CelebrityInvestor`、`CelebrityCard`、`CelebrityPosition`、`CelebrityOpinion`、`CelebrityAdjust`、`CelebrityPerformance`、`CelebrityWeeklyItem` 等类型。
- 增加对应 API 方法（`celebrityInvestors`、`celebrityCard`、`celebrityRefresh`、`celebrityBackfill`、`celebrityPerformance`、`celebrityReviewOpinions`、`celebrityReviewAdjusts`、`celebrityWeekly`、`celebrityPromptGet/Update` 等）。

### 步骤 6：前端菜单 + 路由 + i18n
- `Layout.tsx`：NAV 追加 `{ to: "/investor-celebrity", icon: Users, label: t('layout.investorCelebrity') }`。
- `router.tsx`：注册 `/investor-celebrity` → `InvestorCelebrity`。
- 各 locale JSON 增加 `layout.investorCelebrity`（zh-CN: "投资名人"，en: "Investor Celebrities"）。

### 步骤 7：前端页面与组件
1. `InvestorCelebrity.tsx`：Tab 状态（detail/weekly）、投资人下拉、加载状态、悬浮刷新按钮。
2. `InvestorCard.tsx`：展示名称、投资风格（可编辑）、绩效评价（获取/手动填写）、当前持仓表、最新观点、历史观点表（复选框+复查）、调仓动向表（复选框+复查）、回灌历史按钮、各提示词查看/编辑入口。
3. `WeeklyDynamics.tsx`：居中展示所有投资人周动态分组，按人名+内容，点击人名跳转详情 Tab。
4. `PromptEditorDialog.tsx`：提示词查看与编辑弹窗。

## 依赖与注意事项

- 后端 LLM 调用依赖 `ChatLLM`（`src.providers.chat`），需配置可用的 LLM provider；无配置时刷新/复查/回灌/绩效接口返回明确错误。
- 数据存储使用共享 market warehouse DuckDB，表名前缀 `celebrity_` 避免冲突。
- 「按时间线追加、去重」：以 `(investor_id, time/publish_time, target/content)` 作为去重键。
- 预置投资人 `is_builtin=true` 不可删除；手动新增 `is_builtin=false` 可删除。
- 定时任务后台执行，不阻塞请求；失败仅日志记录。
- 前端 Tab 切换保留选中投资人状态（用 state 管理，不重置）。
- 提示词存数据库，前端可编辑即时生效。

## 验证

- 后端：`make test` 或针对性 pytest，验证 schema 初始化、CRUD、去重逻辑。
- 后端：手动 curl 各 API 端点（需 auth key）验证返回结构。
- 前端：`make fe-build` 确保 TypeScript 编译通过；`scripts/dev up` 启动后浏览器访问 `/investor-celebrity` 验证菜单、Tab、卡片、周动态、刷新、复查流程。
- 定时任务：确认 lifespan 启动后 scheduler task 创建成功（日志）。

## 风险

- **LLM 返回非 JSON / 字段缺失**：service 层做防御性解析，缺失字段置空，不崩溃；参考 gold_monitor 的 `_extract_json` + try/except 模式。
- **去重误判**：去重键选择需谨慎，避免把不同时间的同名标的误去重；用 `(investor_id, time, target)` 三元组。
- **定时任务与手动刷新并发写**：DuckDB 短连接 + 事务，追加操作幂等（去重），并发安全风险低。
- **大模型幻觉编造持仓**：提示词已强约束「禁止编造」，service 层不做额外清洗（信任提示词约束），但保留 source/confidence 字段供用户判断。
