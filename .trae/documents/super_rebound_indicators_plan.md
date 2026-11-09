# 超跌反弹需求实现计划

## Repository Research

### 现有架构
- **后端**：`agent/src/super_rebound/` 模块，包含 `db.py`（pymysql 短连接 + DDL）、`service.py`（业务层）、`scheduler.py`（asyncio 定时调度，15min tick）、`api/super_rebound_routes.py`（FastAPI 路由，全部 behind `require_auth`）
- **数据库**：MySQL `vibe` 库，已有表 `rebound_margin_daily_trade`、`etf_daily_flow`、`etf_daily_net_flow`（均由 `db.py` 的 `initialize_schema()` 管理）
- **LLM**：`from src.providers.chat import ChatLLM` → `llm.chat(messages, timeout=30)` → 返回 `response.content`；gold_monitor 有 JSON 抽取模式（`_extract_json` 处理 markdown 包裹的 JSON）
- **定时调度**：`asyncio.create_task` + `app.state` 存任务 + 窗口判断，失败仅 log 不中断，已在 FastAPI lifespan 注册
- **前端**：React 19 + Tailwind + lucide-react + echarts；`SuperRebound.tsx` 入口管理 tab 切换（`finance` / `indicator`）；`IndicatorPanel.tsx` 目前全是 TODO stub；`superRebound.ts` 统一 API client；菜单通过 `Layout.tsx` 配置

### 关键约束
- 新表须在 `db.py` 的 `_DDL` 字符串中追加，由 `initialize_schema()` 统一执行 `CREATE TABLE IF NOT EXISTS`
- 所有新 API 必须 behind `require_auth`
- 定时任务开关存 `rebound_schedule_config` 表，每次 tick 查 DB 判断是否执行（实现全局开关）
- 大模型调用失败仅 log + 返回空值，不阻塞前端

---

## Files and Modules

### 后端变更

| 文件 | 变更内容 |
|------|----------|
| `agent/src/super_rebound/db.py` | 1. `_DDL` 追加 5 张新表 DDL；2. 新增指标定义 CRUD（upsert/get_all/get_active）；3. 新增提示词 CRUD + 初始化种子数据；4. 新增指标结果 upsert + 批量写入 + 按日期+指数查询；5. 新增每日超跌状态 upsert + 按日期范围查询；6. 新增定时配置 CRUD |
| `agent/src/super_rebound/service.py` | 1. 新增 `get_indicator_defs()` / `upsert_indicator_def()` / `delete_indicator_def()`；2. 新增提示词 `get_prompts()` / `upsert_prompt()` + `get_prompt(prompt_type)`；3. 新增 `fetch_indicator_values_via_llm()`（调用 LLM 获取各指标原始值）；4. 新增 `compute_indicator_judgment()`（本地代码：值 vs 判断标准 → 0/1）；5. 新增 `compute_dimension_score()` / `compute_total_score()`；6. 新增 `run_indicator_eval()` 主流程（LLM 取值 → 本地判断 → 写结果表 → 写每日状态表）；7. 新增 `fetch_volume_price_chip_via_llm()` / `fetch_rebound_tracking_via_llm()`（定性判断，直接 LLM 返回结论）；8. 新增 `get_daily_status_list(trade_date_start, trade_date_end, index_code)`；9. 新增 `get_schedule_config()` / `toggle_schedule()`；10. 新增初始化入口 `ensure_schema_seeded()` |
| `agent/src/super_rebound/scheduler.py` | 1. 新增每日 23:00（北京时间）窗口；2. 先查 `rebound_schedule_config` 判断 `is_enabled`；3. 非交易日跳过；4. 调用 `service.run_indicator_eval()` + `service.fetch_volume_price_chip_via_llm()` + `service.fetch_rebound_tracking_via_llm()` |
| `agent/src/api/super_rebound_routes.py` | 新增路由组：① 指标定义 CRUD `GET/POST/DELETE /api/super-rebound/indicator/defs`；② 提示词 `GET/PUT /api/super-rebound/indicator/prompts`；③ 手动触发 `POST /api/super-rebound/indicator/eval`；④ 每日状态列表 `GET /api/super-rebound/daily-status/list`；⑤ 量价筹码手动触发 `POST /api/super-rebound/daily-status/volume-price-chip/refresh`；⑥ 反弹存续手动触发 `POST /api/super-rebound/daily-status/rebound-tracking/refresh`；⑦ 定时配置 `GET/PUT /api/super-rebound/daily-status/schedule` |

### 前端变更

| 文件 | 变更内容 |
|------|----------|
| `frontend/src/lib/superRebound.ts` | 扩展类型：`IndicatorDef` / `IndicatorPrompt` / `DailyStatusRow` / `ScheduleConfig`；扩展 API client 方法 |
| `frontend/src/pages/super-rebound/IndicatorPanel.tsx` | 完整重写：① 宽基指数选择 + 手动触发按钮 + 编辑提示词按钮；② 综合得分卡 + 信号灯；③ 维度表格（展示指标原始值、0/1 判断、维度得分）；④ 维度内 [+指标][-] 动态增删；⑤ 提示词编辑弹窗（Dialog + Textarea）；⑥ 调用新后端 API |
| `frontend/src/pages/super-rebound/DailyStatusPanel.tsx` | **新建**：① 定时任务开关（Switch）+ 状态展示；② 30 交易日超跌状态列表表格（9 列）；③ 量价与筹码 / 反弹存续跟踪 手动刷新按钮 + 提示词编辑入口；④ 最新交易日高亮 |
| `frontend/src/pages/SuperRebound.tsx` | 增加 `daily-status` tab 路由，引入 `DailyStatusPanel` |
| `frontend/src/components/layout/Layout.tsx` | 无需变更（菜单结构不变，仍在 `超跌反弹` 下） |
| `frontend/src/i18n/locales/zh-CN.json` | 新增 `superRebound` 相关文案（tab、按钮、弹窗、错误提示） |

---

## Implementation Steps

### Phase 1：数据库层（可独立验证）

1. **在 `db.py` 的 `_DDL` 字符串末尾追加 5 张新表**：`rebound_indicator_def`、`rebound_indicator_result`、`rebound_daily_status`、`rebound_prompt`、`rebound_schedule_config`
2. **在 `db.py` 中实现 CRUD 函数**：
   - 指标定义：`get_all_indicator_defs(conn)` / `upsert_indicator_def(conn, row)` / `delete_indicator_def(conn, id)` / `get_indicator_defs_by_dimension(conn, dimension)`
   - 提示词：`get_prompts(conn)` / `get_prompt_by_type(conn, prompt_type)` / `upsert_prompt(conn, row)`
   - 指标结果：`upsert_indicator_result(conn, row)`（UPSERT by `uk_date_indicator`）/ `batch_upsert_indicator_results(conn, rows)`
   - 每日状态：`upsert_daily_status(conn, row)`（UPSERT by `uk_date_index`）/ `get_daily_status_list(conn, start_date, end_date, index_code)`
   - 定时配置：`get_schedule_config(conn, task_name)` / `upsert_schedule_config(conn, row)`
3. **创建种子数据初始化函数 `seed_initial_data(conn)`**：插入 5 维度 × 各指标的初始定义 + 3 条初始提示词 + 1 条定时配置

### Phase 2：业务逻辑层

4. **实现 LLM 取值函数** `fetch_indicator_values_via_llm(index_code, prompt_content, indicator_defs)`：
   - 组装 system/user messages（参考 gold_monitor 模式）
   - 要求返回 JSON `{赔率层: {指标名: 值}, 技术超卖: {...}, ...}`
   - 调用 `ChatLLM().chat(messages, timeout=60)`
   - `_extract_json` 从响应中抽取 JSON
   - 返回 `{indicator_id: raw_value_str}` dict
   - 失败时 log + 返回空 dict，不抛异常

5. **实现本地判断函数** `compute_judgment(indicator_raw_value, judgment_criteria)`：
   - 将大模型返回的字符串值转为数值（正则提取）
   - 解析 `judgment_criteria`（支持 `> X`, `< X`, `>= X`, `<= X`, `!= X`, `== X`）
   - 比较返回 0/1

6. **实现维度得分** `compute_dimension_score(indicator_results)`：按维度内指标权重加权平均 judgment_result × 100

7. **实现主流程** `run_indicator_eval(index_code)`：
   - 读 `rebound_prompt` → 超跌指标 prompt
   - 读 `rebound_indicator_def`（is_active=1）
   - 调 `fetch_indicator_values_via_llm()` 一次性取值
   - 对每个指标本地判断 → 0/1
   - 计算各维度得分 → 综合得分 → 信号灯
   - 写 `rebound_indicator_result` 批量 upsert
   - 写 `rebound_daily_status` upsert
   - 返回完整结果供前端展示

8. **实现量价与筹码 / 反弹存续跟踪 LLM 判断**：直接调用 LLM 返回定性结论（与超跌指标不同，这两个是多维定性判断），写 `rebound_daily_status.volume_price_chip / rebound_tracking`

### Phase 3：定时任务扩展

9. **在 `scheduler.py` 中新增 23:00 窗口**：
   - 新常量 `_DAILY_STATUS_HOUR = 23`
   - 每 tick 检查：当前 hour == 23 && `service.is_schedule_enabled("daily_status_auto")` && 当日未跑 && 非周末
   - 调用 `asyncio.to_thread(service.run_indicator_eval("沪深300"))` + 量价筹码 + 反弹存续

### Phase 4：API 路由

10. **在 `super_rebound_routes.py` 中追加所有新路由**（全部 behind `Depends(require_auth)`）：
    - 指标定义 CRUD（GET/POST/PUT/DELETE）
    - 提示词查询与更新（GET/PUT）
    - 手动触发指标评估（POST）
    - 每日状态列表查询（GET）
    - 量价筹码/反弹存续手动刷新（POST × 2）
    - 定时配置查询与开关（GET/PUT）
    - `initialize_schema()` + `seed_initial_data()` 在服务器启动时调用（或添加 health check 端点触发首次创建）

### Phase 5：前端实现

11. **扩展 `superRebound.ts` 类型与 API client**

12. **重写 `IndicatorPanel.tsx`**：
    - 移除 TODO banner
    - 头部：宽基指数选择 + 编辑提示词按钮 + 手动触发按钮（loading state + 自动刷新）
    - 综合得分卡 + 信号灯（沿用现有 getSignalColor 逻辑）
    - 维度表格：每维度显示指标原始值（大模型返回）、0/1 判断结果、维度得分
    - 每行维度操作栏：[+指标] 新增弹窗（指标名称 + 判断标准 + 权重 + 排序）、[-] 删除
    - 提示词编辑：Dialog + Textarea + 保存（PUT /prompts）
    - 加载数据时调 POST `/indicator/eval` 或先 GET 缓存 → 无缓存时触发 eval

13. **新建 `DailyStatusPanel.tsx`**：
    - 顶部：定时任务 Switch 开关 + 当前状态标签
    - 主体表格：9 列（日期、赔率层、技术超卖、资金承接、情绪广度、外部流动性、综合得分、量价与筹码、反弹存续跟踪）
    - 最新交易日整行高亮
    - 量价与筹码 / 反弹存续跟踪 列内：手动刷新按钮 + 提示词编辑按钮
    - 默认近 30 交易日

14. **更新 `SuperRebound.tsx`**：添加 `daily-status` tab

15. **更新 i18n 文案**

### Phase 6：启动与集成

16. **在 `api_server.py` / lifespan 中确认** `initialize_schema()` 被调用（或确保 `register_super_rebound_routes` 时自动执行）
17. **`seed_initial_data()`** 在 schema 初始化后执行一次（幂等，用 `INSERT ... ON DUPLICATE KEY UPDATE` 或先查后插）

---

## Dependencies and Considerations

- **本地判断 vs LLM 判断**：超跌指标 5 维度走"LLM 取值 + 本地 0/1 判断"；量价与筹码、反弹存续跟踪走"LLM 直接定性判断"（多维定性标准无法简化为单阈值比较）
- **提示词一致性**：3 类 prompt 共用 `rebound_prompt` 表，prompt_content 最新值即生效，无版本控制
- **定时开关存储**：`rebound_schedule_config` 表，scheduler 每 tick 查一次 DB（表很小，开销可接受）
- **交易日判断**：`date.weekday() < 5` 先过滤周末，节假日暂不处理（后续可接入 A 股交易日历）
- **LLM 取值容错**：LLM 可能返回不完整 JSON → 缺失字段的指标 judgment_result = 0，不阻塞整体
- **数据库初始化顺序**：`initialize_schema()` 先执行所有 DDL，再 `seed_initial_data()` 插入初始数据（idempotent，不重复插）
- **多宽基指数**：当前定时任务只跑沪深 300，其他指数用户手动触发（可扩展为遍历所有 index_code）
- **`providers.chat.ChatLLM`** 是实例化后 `chat(messages, timeout)` 的同步调用，在 scheduler 中用 `asyncio.to_thread()` 包裹

---

## Validation

1. **后端单元验证**：`python3 -c "from src.super_rebound import db; from src.config.accessor import get_env_config; cfg = get_env_config(); print(cfg)"` 验证 MySQL 连接；`db.initialize_schema(conn)` 执行后检查表存在
2. **种子数据验证**：SELECT COUNT(*) FROM rebound_indicator_def 应为初始 13 行左右；SELECT * FROM rebound_prompt 应有 3 条
3. **LLM 调用验证**：手动调用 `service.run_indicator_eval("沪深300")` 检查 rebound_indicator_result 与 rebound_daily_status 是否有数据
4. **API 验证**：curl `GET /api/super-rebound/indicator/prompts` 返回 3 条 prompt；`POST /indicator/eval?index_code=沪深300` 触发完整流程
5. **前端构建**：`cd frontend && npm run build` 无 TypeScript 错误
6. **E2E 验证**：浏览器打开 /super-rebound → 切换 tab → 手动触发 → 检查数据加载和错误提示

---

## Risks

| 风险 | 处理 |
|------|------|
| LLM 调用不稳定（超时/返回非 JSON） | service 层 try/except 包裹，失败 log + 返回空结果，前端展示空值 + 错误提示 |
| 判断标准解析能力有限（`> X` / `< X` 可覆盖绝大多数） | 复杂判断标准（"明显负乖离"等定性描述）允许 `judgment_result` 为 NULL，前端展示 — |
| 定时 23:00 窗口在 tick=15min 下可能漏跑 | 23:00–23:59 都在窗口内，且已有 `sr_daily_status_last_date` 防重复 |
| 大模型返回值格式不一致（如 `RSI: 28` vs `RSI=28` vs `"28%"`） | `compute_judgment` 用正则 `[-+]?\d*\.?\d+` 提取数值，`%` 自动除以 100 |
| 首次部署 MySQL 连接可能失败 | db.py 的 `rebound_connection()` 已有 fallback（先 SUPER_REBOUND_DB_* 再 MACRO_DB_*），启动时健康检查 |
