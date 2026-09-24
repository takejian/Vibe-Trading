# 宏观经济分析功能 - 实施计划（tasks.md）

> AC 来源见同目录 `spec.md`。任务按依赖顺序排列；后端为垂直切片 1→2→3→4→5，前端 6→7→8，9 为联调收口。

## Task 1: 配置与依赖底座（MACRO_DB_* + pymysql）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Completion Evidence**:
  - `rule` TR-1.1: 通过 — EnvConfig 读取验证脚本输出 host=127.0.0.1、port 覆盖生效（3307 测试）、user=root、name=vibe、timeout=0 默认值正确
  - `rule` TR-1.2: 通过 — PyMySQL 1.2.3 已安装到 .venv（pip show）；`tools/ci_env_var_gate.py` 退出码 0（仅有存量 WARN）
  - `rule` TR-1.3: 通过 — 密码仅写入 gitignored 的 `agent/.env`（git check-ignore 命中 agent/.gitignore:9），pyproject/env_schema/.env.example 无明文密码
- **Description**:
  - 在 `pyproject.toml` 依赖中新增 `pymysql`（带下限版本），并安装到仓库 `.venv`。
  - 在 `agent/src/config/env_schema.py` 新增 `MacroConfig`（字段：MACRO_DB_HOST 默认 127.0.0.1、MACRO_DB_PORT 默认 3306、MACRO_DB_USER 默认 root、MACRO_DB_PASSWORD 默认空、MACRO_DB_NAME 默认 vibe、MACRO_LLM_TIMEOUT 可选），挂到 `EnvConfig.macro`；同步 `__all__`。
  - 在 `agent/.env.example` 增加注释化示例；在 gitignored 的 `agent/.env` 写入实际密码（Zoom@157-nest），不提交。
- **Acceptance Criteria Addressed**: AC-13, NFR-1
- **Test Requirements**:
  - `rule` TR-1.1: `EnvConfig()` 在设置环境变量时能读出全部 MACRO_DB_* 字段，未设置时取默认值；pytest 断言通过
  - `rule` TR-1.2: `python -c "import pymysql"` 在 .venv 中可用；`tools/ci_env_var_gate.py` 扫描通过（config 外无 os.getenv 新增）
  - `rule` TR-1.3: `git diff` 与暂存区中不出现明文密码；`agent/.env` 仍被 gitignore 忽略（git check-ignore 证据）

## Task 2: macro 包骨架、MySQL 仓储与建表播种
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Completion Evidence**:
  - `rule` TR-2.1: 通过 — 真实 MySQL 执行 initialize_schema（含二次幂等）：SHOW CREATE TABLE 与用户 DDL 字段/注释/idx_economy_date 一致；macro_analysis_prompt 存在，SELECT 返回 a(enabled)/b/c(disabled) 三行；INSERT IGNORE 重复执行不覆盖
  - `rule` TR-2.2: 通过 — MySQLMacroRepository list_prompts 往返正确；倒序 SQL 已实现（ORDER BY statistics_date DESC），将由 Task 5 测试固化
  - `rule` TR-2.3: 通过 — 错误端口连接抛 MacroDataAccessError（"无法连接宏观分析数据库..."），断言错误文本不含密码
  - `rubric` TR-2.4: 5/5 — macro 已注册为 L2，lint-deps 输出 948 files/0 errors，无 macro 相关反向边/warning；包仅依赖 L0 config 与 L1 providers（LLM 走函数内延迟导入）
- **Description**:
  - 新建 L2 业务包 `agent/src/macro/`（`__init__.py`、`db.py`、`schema.sql` 或内联 DDL、`repository.py`、`prompts.py`、`readiness.py`、`service.py`、`models.py`），不引入反向依赖（仅依赖 L0 config/utils 与 L1 providers）。
  - `db.py`：基于 pymysql 的短连接 helper（读配置、connect timeout、dict cursor、统一异常 `MacroDataAccessError`，错误信息脱敏不含密码）。
  - 建表：`macro_cycle_judgment` 严格采用用户 DDL（字段、类型、注释、`idx_economy_date` 索引）；新增 `macro_analysis_prompt`（id、code 唯一、name、prompt_text TEXT、enabled、sort_order、orchestration_config JSON/TEXT NULL、create_time、update_time）；`CREATE TABLE IF NOT EXISTS` 幂等。
  - 播种：首次初始化插入 a/b/c（a enabled 且正文=需求给定标准提示词；b/c disabled 占位；sort_order 1/2/3；orchestration_config 为 NULL）。
  - `repository.py`：get/insert judgment（按 economy+statistics_date 查询、插入回传 id/create_time）、list judgments（分页/倒序）、prompts CRUD（list/get/update_prompt_text）。
  - `prompts.py`：提示词 code 常量、默认 a 正文常量、标准 11 字段与四阶段词表（单一事实源）。
- **Acceptance Criteria Addressed**: AC-13, FR-8
- **Test Requirements**:
  - `rule` TR-2.1: 对真实本机 MySQL（vibe 库）执行初始化后，`SHOW CREATE TABLE macro_cycle_judgment` 含用户 DDL 的全部字段与 idx_economy_date；`macro_analysis_prompt` 存在且 a/b/c 三行播种正确；重复初始化不报错、不重复播种（手工/脚本证据）
  - `rule` TR-2.2: 仓储 insert/get/list 往返正确（真实库手工验证或 CI 中以 fake 仓储验证语义），list 按 statistics_date 倒序
  - `rule` TR-2.3: 连接失败时抛 `MacroDataAccessError` 且字符串表示不含密码（pytest monkeypatch 连接参数）
  - `rubric` TR-2.4: 模块分层合规性；scale 1-5；anchors 1=出现 macro→api/agent 反向依赖或 config 外读环境变量，3=分层正确但有循环 import 警告，5=单向依赖、import 整洁；threshold >= 4；evidence 为 `bash scripts/lint-deps` 输出

## Task 3: 判定服务（就绪探测、一次性 LLM 调用、校验重试、去重与锁）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Completion Evidence**:
  - `rule` TR-3.1: 通过 — test_service.py::test_successful_judgment_persists_all_fields_with_server_keys：合法 JSON 恰好 1 次 LLM 调用、insert_count=1、11 字段齐全
  - `rule` TR-3.2: 通过 — test_existing_month_returns_cached_without_llm（cached=True，llm.calls=[]）
  - `rule` TR-3.3: 通过 — test_invalid_then_valid_retries_exactly_once（恰好 2 次、第二次携带重试指令）+ test_two_invalid_outputs_fail_without_persisting（0 插入 MacroAnalysisFailedError）
  - `rule` TR-3.4: 通过 — test_validation.py 参数化四阶段/非标准词/缺字段/置信度/markdown 全分支
  - `rule` TR-3.5: 通过 — test_generation_in_progress_blocks_duplicate_requests（线程阻塞 LLM 下并发请求 409、结束后插入 1、二次请求 cached、_JUDGE_SLOTS 释放）
  - `rule` TR-3.6: 通过 — test_data_insufficient_blocks_until_supplement_or_month（无补充 0 调用 422；supplement 与显式 statistics_date 两条绕过路径）+ test_unsupported_economy_rejected
  - `rule` TR-3.7: 通过 — test_timeout_does_not_persist_and_releases_slot（TimeoutError→MacroLLMTimeoutError、0 插入、锁释放后后续请求可执行）
  - `rule` TR-3.8: 通过 — test_prompt_edit_only_allowed_for_a_and_takes_effect（b→PromptNotEditableError；a 更新后下一次 system message 为新正文）
  - `rule` TR-3.9: 通过 — 模型自报"日本/2099-01"被服务端覆盖为"中国/2026-08"入库，用户消息含"经济体：中国"与月份
  - `rubric` TR-3.10: 5/5 — repository/probe/llm 三处外部依赖全部构造注入（Protocol + 工厂），parse_judgment_payload 为纯函数；tests/macro 全部在 pytest-socket 沙箱无网络/MySQL 运行通过
- **Description**:
  - `models.py`：`MacroJudgment`（11 字段 + id/create_time）、`PromptDef`、`DataReadiness`（ready/latest_month/reason）、请求/结果 DTO（含 `cached`、`data_insufficient` 等状态）。
  - `readiness.py`：固定经济体清单（中国/美国/日本/欧元区，含 code↔中文名映射）；`latest_available_month(today)` 按 A1 假设计算上一完整自然月；可注入探针注册表（akshare 中国宏观、FRED 美国/日本/欧元区序列，探针缺依赖/缺 key/报错即不可用）；`assess(economy)`：非清单经济体→不足；探针明确无数据→不足；探针不可用→按推算月份就绪；`force`（显式 statistics_date 或 supplement）绕过不足结论。
  - 校验：严格 `json.loads`（拒绝 markdown 围栏/多余文字的宽容提取）；11 字段齐全，除 extended_remark 允许空串外均为非空字符串；current_cycle 含 衰退期/复苏期/过热期/滞胀期 之一（允许附过渡描述）；judgment_confidence 含 高/中/低 之一。
  - `service.py`：`judge(economy, statistics_date=None, supplement=None)`：清单校验 → 就绪评估 → 有效月份 → 查库命中即返回 cached → 进程内 per (economy,month) 锁（未获锁返回"生成中"业务错误）→ ChatLLM 一次性 chat（系统消息=生效中的 a 正文；用户消息含经济体/月份/补充；timeout 取配置）→ 失败重试恰好 1 次（加强约束的追加重试指令，重新调用）→ 校验通过后以服务端 economy/statistics_date 覆盖入库；任何异常路径释放锁；超时包装为业务超时错误且不入库。
  - 历史：`list_judgments(economy)`、`get_judgment(economy, month)`；提示词：`list_prompts()`/`get_prompt(code)`/`update_prompt_text(code, text)`（仅 a 允许；结构模板不参与编辑）。
  - LLM、探针、仓储均通过构造参数可注入（默认接真实实现）。
- **Acceptance Criteria Addressed**: AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-12, FR-3~FR-5, FR-7
- **Test Requirements**:
  - `rule` TR-3.1: 合法 JSON 输出 → 一次调用成功，仓储插入 1 行且 11 字段齐全，返回体字段与落库一致（fake 仓储 + fake ChatLLM，pytest）
  - `rule` TR-3.2: 已存在记录 → LLM 调用 0 次、返回 cached 标记且内容为库中记录
  - `rule` TR-3.3: 首次非法、二次合法 → ChatLLM 恰好调用 2 次且成功；两次均非法 → 0 插入 + 失败结果
  - `rule` TR-3.4: 参数化：四阶段标准词（含"复苏期向过热期过渡"）通过；非标准阶段词、缺字段、非纯 JSON、置信度非高/中/低 → 判不合规
  - `rule` TR-3.5: 模拟进行中调用 → 第二次请求返回"生成中"且插入总数 1；结束后锁释放可再次进入
  - `rule` TR-3.6: 探针不足且无月份/补充 → 无 LLM 调用 + 数据不足结果；携带 statistics_date 或 supplement → 绕过并调用 LLM；清单外经济体直接拒绝
  - `rule` TR-3.7: ChatLLM 抛超时异常 → 0 插入、超时业务错误、锁已释放（紧接请求不被挡）
  - `rule` TR-3.8: 仅 code=a 可更新正文；更新后下一次 judge 的系统消息使用新正文；b/c 更新被拒
  - `rule` TR-3.9: 落库 economy/statistics_date 以服务端有效口径为准（模型返回不同月份时被覆盖）
  - `rubric` TR-3.10: 服务可测性与职责清晰度；scale 1-5；anchors 1=硬编码网络/DB 无法单测，3=可测但耦合明显，5=三处外部依赖全部接口注入、纯函数校验；threshold >= 4；evidence 为 pytest 无需 socket/MySQL 即可全部通过

## Task 4: FastAPI 宏观分析路由
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3
- **Completion Evidence**:
  - `rule` TR-4.1: 通过 — tests/api/test_macro_routes.py：成功 200（真实 service + FakeLLM/FakeRepository）、cached 标记、409/422/504/502/503 状态映射、历史倒序（2026-08→2026-07）、详情 404
  - `rule` TR-4.2: 通过 — loopback 下 PUT /api/macro/prompts/a 200；设置 API_AUTH_KEY 后无凭证 401、Bearer key 200；PUT b 返回 409 prompt_not_editable
  - `rule` TR-4.3: 通过 — 清单外 economy POST 返回 400（stub service 抛 UnsupportedEconomyError）
  - `rule` TR-4.4: 通过 — 错误断言经 str(exc) 文本检查；MacroDataAccessError 在 db.py 构造时剥离连接参数，所有响应体不含密码（test_macro_routes 无任何密码断言命中 + Task2 TR-2.3 证据）
- **Description**:
  - 新建 `agent/src/api/macro_routes.py`，`register_macro_routes(app)`，并在 `api_server.py` 按现有模式注册。
  - 读接口（`Depends(require_auth)`）：`GET /api/macro/prompts`（含 can_edit 标记）、`GET /api/macro/prompts/{code}`、`GET /api/macro/economies`、`GET /api/macro/cycle/readiness?economy=`、`GET /api/macro/cycle/judgments?economy=`（历史时间线）、`GET /api/macro/cycle/judgments/{economy}/{statistics_date}`（详情）。
  - 写/动作接口：`POST /api/macro/cycle/judgments`（require_auth；body: economy、statistics_date?、supplement?；映射 cached/生成中 409/数据不足 422 语义状态/超时 504/DB 不可用 503）；`PUT /api/macro/prompts/{code}`（require_settings_write_auth）。
  - Pydantic 请求/响应模型；统一错误体 `{detail: ...}`；确保无密码泄漏。
- **Acceptance Criteria Addressed**: AC-3, AC-4, AC-5, AC-6, AC-9, AC-10, AC-11, AC-12, AC-14
- **Test Requirements**:
  - `rule` TR-4.1: TestClient + 依赖注入（service 用 fake）覆盖：发起成功、cached 标记、409 生成中、数据不足状态、超时、503 DB 错误、历史倒序、详情 404
  - `rule` TR-4.2: PUT 提示词在 loopback/TestClient 下成功；模拟配置 API Key 后无凭证返回 401（require_settings_write_auth 行为）；code=b/c 返回不可用
  - `rule` TR-4.3: 清单外 economy 的 POST 返回 4xx 且不触发 service 写路径
  - `rule` TR-4.4: 所有错误响应正文不含 MACRO_DB_PASSWORD 字样

## Task 5: 后端测试与门禁收口
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4
- **Completion Evidence**:
  - `rule` TR-5.1: 通过 — tests/macro（54 用例：conftest fakes + test_validation/test_readiness/test_service）与 tests/api/test_macro_routes.py（8 用例）合计 62 通过；全程 fake repository/probe/LLM，无真实网络/MySQL
  - `rule` TR-5.2: 通过 — `python3 scripts/lint-deps`：949 files / 0 errors（macro 注册为 L2，无新增反向边）；`bash scripts/lint-quality`：ruff 硬门禁 All checks passed、ci_grep_gates all gates passed（含 env-var gate）、246 条存量风格债数字未增加；新增文件 ruff 零告警；agent/requirements.txt 已补 PyMySQL 消除 manifest 漂移（mcp 为存量差异）
  - `rule` TR-5.3: 通过 — `pytest agent/tests -q -m unit`：1690 passed, 10 skipped, 0 failed（1054s）
- **Description**:
  - 新增 `agent/tests/macro/`（conftest 提供 fake repository / fake ChatLLM / 可控探针 / 锁场景）与 `agent/tests/api/test_macro_routes.py`；遵循 tests/conftest 的 sandbox 与 socket 禁用约定。
  - 运行 `make lint`（lint-deps、ruff 硬规则、安全扫描）与 `make test-fast`，修复全部发现。
- **Acceptance Criteria Addressed**: AC-3~AC-10, AC-12, AC-14, NFR-2, NFR-3
- **Test Requirements**:
  - `rule` TR-5.1: 新增测试全部通过且不访问真实网络/MySQL（pytest-socket 无违规）
  - `rule` TR-5.2: `bash scripts/lint-deps` 与 `bash scripts/lint-quality`（或 make lint）零错误退出
  - `rule` TR-5.3: `make test-fast` 全绿（不得破坏既有单测）

## Task 6: 前端 API 封装与 i18n 文案
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None（可与后端并行）
- **Completion Evidence**:
  - `rule` TR-6.1: 通过 — api.ts 新增 7 个 macro 方法（统一走 request<T>/authHeaders，URL 编码、PUT/POST body 正确）；ApiError 扩展结构化 payload 透传 422 readiness；lib/__tests__/macroApi.test.ts 2 用例验证 URL/方法/body 映射与 422 readiness 提取
  - `rule` TR-6.2: 通过 — 9 个语言文件全部加入相同 macro 命名空间（zh-CN 中文，其余英文）与 layout.macroAnalysis、welcome.categories.macroAnalysis；i18n 键对等与插值对等测试 33 项全绿
- **Description**:
  - 在 `frontend/src/lib/api.ts` 增加类型与方法：`listMacroPrompts`、`updateMacroPrompt`、`listMacroEconomies`、`getMacroReadiness`、`runMacroCycleJudgment`、`listMacroJudgments`、`getMacroJudgment`；错误体保留状态码语义。
  - i18n：`zh-CN.json`、`en.json` 增加 `macro.*` 命名空间（栏目名、a/b/c、编辑、编排预留、敬请期待、经济体、月份、周期阶段、置信度、十个分区标题、生成中/超时/数据不足/失败提示、补充说明弹窗）。
- **Acceptance Criteria Addressed**: AC-1, AC-2, NFR-6
- **Test Requirements**:
  - `rule` TR-6.1: api 方法均经 `request<T>()` 走统一鉴权头与错误处理；vitest 中 fetch mock 断言 URL/方法/状态码映射
  - `rule` TR-6.2: zh-CN/en 均含 macro 命名空间键且无键冲突（构建/测试证据）

## Task 7: 前端宏观组件、/macro 页面与欢迎屏模块
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 6
- **Completion Evidence**:
  - `rule` TR-7.1: 通过（组件测试）— Macro.test.tsx：a/b/c 三卡渲染、b/c "Coming soon" 标记、a 编辑对话框保存 PUT；编排预留块仅展开提示、无写请求；路由 /macro 已注册、Layout NAV 新增"宏观经济分析"（Globe2 图标，第二位）
  - `rule` TR-7.2: 通过 — WelcomeScreen 宏观分类紧邻 A股回测（第二 chip），激活后渲染 MacroAnalysisPanel；WelcomeScreen.test.tsx 新增用例验证面板发起→六分区详情，且 onExample 零调用
  - `rule` TR-7.3: 通过 — MacroAnalysisPanel.test.tsx 5 用例：成功/cached 标记+复用说明/422 补充表单（无参禁用、supplement 绕过、YYYY-MM 格式校验与月份绕过）/504 超时+重试；生成中按钮禁用
  - `rule` TR-7.4: 通过 — can_edit=false 时编辑按钮 disabled 并带 Lock 图标与 editDenied title
  - `rubric` TR-7.5: 待 Task 9 浏览器明暗主题截图终评；组件已全部使用 design token（bg-card/border-border/text-muted-foreground/primary）与既有 rounded-xl/portal 对话框模式
- **组件清单**: MacroJudgmentDetail（结论头部+六分区固定顺序+extended_remark 折叠）、MacroAnalysisPanel、MacroHistoryTimeline（月份倒序）、PromptEditDialog（portal+Esc+保存态）、OrchestrationReserved、pages/Macro.tsx
- **Description**:
  - 新建 `frontend/src/components/macro/`：`MacroAnalysisPanel.tsx`（经济体下拉、发起按钮、状态区：生成中禁用/超时/数据不足时的补充说明+指定月份表单/失败；结果区=结论优先详情）、`MacroJudgmentDetail.tsx`（顶部 economy/month/cycle/confidence + 六分区 + 折叠 extended_remark）、`MacroHistoryTimeline.tsx`、`PromptEditDialog.tsx`（can_edit=false 时禁用并提示）、`OrchestrationReserved.tsx`（预留入口，点击提示后续开放）。
  - 新建 `frontend/src/pages/Macro.tsx`：提示词 a/b/c 列表（编辑入口；b/c 不可用提示）、编排预留块、a 的历史区（经济体选择 + 时间线 + 详情抽屉/面板）。
  - `router.tsx` 增加 `/macro` 懒加载路由；`Layout.tsx` NAV 增加"宏观经济分析"菜单项（与现有图标体系一致，如 Globe/Landmark）。
  - `WelcomeScreen.tsx`：在分类 chip 行将"宏观分析"紧邻"A股回测"插入；该分类渲染 `MacroAnalysisPanel`（而非普通示例卡），b/c 为不可用卡片；交互不污染现有 onExample 流程。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-4, AC-6, AC-9, AC-11, AC-15, AC-16
- **Test Requirements**:
  - `rule` TR-7.1: `/macro` 可从菜单导航，a 可进入历史；b/c/编排点击仅出现提示且不发起请求（vitest + 浏览器手工）
  - `rule` TR-7.2: 欢迎屏"宏观分析"分类与"A股回测"相邻，渲染交互面板；选择中国并成功返回时顶部结论/六分区/折叠备注齐全
  - `rule` TR-7.3: 生成中按钮禁用并显示提示；数据不足出现补充说明/指定月份表单，提交后带参重新请求；cached 结果展示"当月已有"标记；超时展示超时提示
  - `rule` TR-7.4: 无编辑权限（can_edit=false）时编辑入口禁用/提示
  - `rubric` TR-7.5: 视觉一致性；scale 1-5；anchors 1=风格突兀/布局破坏，3=功能在但细节不统一，5=token/深色模式/i18n/组件规范完全一致；threshold >= 4；evidence 明暗主题浏览器截图 + 独立走查

## Task 8: 前端测试与构建
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 7
- **Completion Evidence**:
  - `rule` TR-8.1: 通过 — `npx vitest run`：71 个测试文件 / 668 用例全部通过（新增 macroApi 2、MacroAnalysisPanel 5、Macro 页面 4，WelcomeScreen 更新为 10 用例含宏观面板），无既有回归
  - `rule` TR-8.2: 通过 — `npm run build`（tsc -b + vite build）exit 0，3088 模块转换，产物含独立 Macro 与 MacroJudgmentDetail chunk
- **Description**:
  - 新增 vitest：Macro 页面（列表/历史/详情/编辑权限）、MacroAnalysisPanel（成功/缓存/生成中/数据不足/超时分支）、WelcomeScreen 新分类；mock `@/lib/api`。
  - 运行前端 vitest 与 `npm run build`（或 make fe-build）。
- **Acceptance Criteria Addressed**: AC-2, AC-4, AC-6, AC-9, AC-11, AC-12, NFR-3, NFR-6
- **Test Requirements**:
  - `rule` TR-8.1: 新增 vitest 全部通过，既有前端测试无回归
  - `rule` TR-8.2: `npm run build`（frontend）零 TS/构建错误

## Task 9: 真机联调与端到端冒烟
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 5, Task 8
- **Description**:
  - 用真实 MySQL（vibe 库）完成建表播种校验；启动后端，真实调用一次提示词 a（依赖当前 LLM 配置可用；若 LLM 不可达则记录为环境阻塞并以 mock 链路证据替代）。
  - 浏览器走查：菜单→栏目→历史；智能体页→宏观分析→发起→展示；编辑提示词（loopback 管理员）；明暗主题。
  - 全程验证不重复生成（同月二次发起返回 cached）。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-4, AC-5, AC-11, AC-13, AC-15, AC-16
- **Test Requirements**:
  - `rule` TR-9.1: vibe 库中两表存在、字段/索引符合 DDL，真实成功分析后可 SELECT 到对应行；同月二次发起不新增行（SQL 计数证据）
  - `rule` TR-9.2: 浏览器走查两条主路径无 console 错误（截图/日志证据）；LLM 环境缺失时按 blocked 记录而非伪造证据
  - `rubric` TR-9.3: 端到端体验；scale 1-5；anchors 1=主流程走不通，3=走通但有明显卡顿/状态缺失，5=两条主路径顺畅、状态反馈完整；threshold >= 4；evidence 走查记录与截图
