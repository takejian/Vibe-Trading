# 宏观经济分析功能 - 产品需求文档（spec.md）

> 来源需求：`BDD.md`（经 12 轮 HITL 澄清确认）。本文件只定义"做什么"与验收标准，不含实现分解。

## Overview

- **Summary**：在 Vibe-Trading Web 端新增"宏观经济分析"能力：左侧菜单栏新增栏目（提示词 a/b/c 浏览、提示词编辑、历史浏览），智能体欢迎页在"A股回测"旁新增"宏观分析"模块；本期实现提示词 a（宏观经济周期判定）——用户从预设经济体清单选择经济体后，系统以最新可得数据月份调用 LLM 一次性产出标准化周期判定 JSON，写入 MySQL `vibe.macro_cycle_judgment` 表，并在前端结论优先分层展示；同一经济体同一月份不重复生成。
- **Purpose**：为个人投资者提供快速周期结论、为专业研究人员提供可追溯可对比的周期研究档案。
- **Target Users**：个人投资者、专业研究人员（共用同一份结果）；管理员（本机操作者 / API Key 持有者）可编辑提示词正文。

## Goals

- G1：左侧菜单栏新增"宏观经济分析"栏目页：提示词 a/b/c 列表（a 可用，b/c 预留不可用）、每条提示词有编辑入口、工具编排调用流程预留入口、点击 a 进入"经济体 → 月份时间线 → 详情"的历史浏览。
- G2：智能体页面欢迎屏在"A股回测"分类旁新增"宏观分析"分类模块，其中提示词 a 可交互：选经济体 → 发起分析 → 生成中/超时/数据不足状态反馈 → 结论优先展示。
- G3：后端提供宏观分析 API：提示词查询/编辑、经济体清单、数据就绪探测、发起判定、历史列表、详情读取。
- G4：周期判定结果持久化到 MySQL `vibe` 库；经济体+月份唯一复用；输出合规校验失败自动重试恰好 1 次；失败/超时不留存。
- G5：提示词正文可由管理员编辑（编辑后仅影响新分析，结构约束不变）；为 b/c 提示词与工具编排流程预留可扩展的数据模型与界面位。

## Non-Goals

- N1：不实现提示词 b / c 的实际分析逻辑（仅预留展示位与数据槽位）。
- N2：不实现 AI 工具编排调用流程的可视化配置与执行（仅预留入口与存储字段）。
- N3：不做多用户体系、角色表、登录鉴权改造；"管理员"沿用现有 settings 写权限模型（本机 loopback 操作者或 API Key 持有者）。
- N4：不走多 agent / ReAct / swarm 流程，不强制自动拉取全量宏观指标喂给模型；本期为一次性 LLM 调用。
- N5：不做历史结果删除、归档、年限清理（永久保留）。
- N6：不做经济体的自由输入扩充（仅预设清单：中国、美国、日本、欧元区）。

## Background & Context

- 前端：React 19 + Vite + TS；菜单定义在 [Layout.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/layout/Layout.tsx#L22-L32) 的 `NAV`；路由在 [router.tsx](file:///home/ai/Vibe-Trading/frontend/src/router.tsx)；"A股回测"是欢迎屏 [WelcomeScreen.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/chat/WelcomeScreen.tsx#L18-L39) 中分类 chip 的第一项（`welcome.categories.multiMarketBacktest`）；API 封装在 [api.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts) 的 `request<T>()`。
- 后端：FastAPI 路由在 [api_server.py](file:///home/ai/Vibe-Trading/agent/api_server.py#L185-L264) 以 `register_*_routes(app)` 模式注册；鉴权依赖 `require_auth` / `require_settings_write_auth`（[security.py](file:///home/ai/Vibe-Trading/agent/src/api/security.py#L571-L657)）。
- LLM 最小调用封装：`ChatLLM.chat(messages, timeout=...) -> LLMResponse`，文本在 `response.content`（[chat.py](file:///home/ai/Vibe-Trading/agent/src/providers/chat.py#L454-L469)）。
- 配置：所有环境变量必须在 [env_schema.py](file:///home/ai/Vibe-Trading/agent/src/config/env_schema.py) 定义 pydantic 字段，由 `tools/ci_env_var_gate.py` 机械强制；仓库当前无任何 MySQL 依赖，仅有 duckdb；需新增 `pymysql`。
- 数据库：本机 MySQL 8 已运行（3306），`vibe` 库已存在且为空；用户给定建表 DDL（表 `macro_cycle_judgment`，索引 `idx_economy_date`）；账号 root。
- 宏观数据：FRED 工具（需 FRED_API_KEY，覆盖美国及部分全球序列）与 akshare（已安装，含中国宏观接口）可作为数据就绪探测的可选探针；测试环境禁用网络，探测须可注入/mock。

## Functional Requirements

### FR-1：栏目入口与提示词浏览

- FR-1.1：左侧菜单栏新增"宏观经济分析"菜单项，点击进入 `/macro` 页面。
- FR-1.2：页面展示三个提示词条目：a 宏观经济周期判定（可用）、b 待扩展（不可用）、c 待扩展（不可用）；每条均展示"编辑"入口；另展示"工具编排调用流程"预留入口。
- FR-1.3：点击 a 进入其分析历史浏览区；点击 b/c 或其编辑入口不发起任何分析，仅提示后续版本开放；工具编排入口同样仅提示后续开放。

### FR-2：智能体页面宏观分析模块

- FR-2.1：欢迎屏示例库分类 chip 行在"A股回测"旁新增"宏观分析"分类；选中后展示提示词 a 卡片/交互区（经济体下拉选择 + 发起分析按钮 + 状态与结果区），b/c 以"敬请期待"不可用形态展示。
- FR-2.2：发起分析后按 FR-4/FR-5/FR-6 的规则执行，并在当前模块内展示结果或状态。

### FR-3：经济体清单与数据就绪

- FR-3.1：预设经济体清单固定为：中国、美国、日本、欧元区；前端只能选择，不能输入清单外经济体。
- FR-3.2：未指定月份时，系统按宏观数据发布时滞推算"最新可得数据月份"（YYYY-MM），并以尽力而为的探针校验数据可获得性。
- FR-3.3：探针不可用/未配置时按推算月份视为就绪；探针明确无数据或报错时判定"数据不足"。
- FR-3.4：数据不足时不调用 LLM，返回可识别的"数据不足"状态；用户可通过"补充说明"或"显式指定数据截止月份"继续（强制按用户输入执行）。

### FR-4：发起周期判定（提示词 a）

- FR-4.1：请求体含 economy；statistics_date、supplement（补充说明）可选。有效月份 = 用户指定月份，否则为 FR-3.2 推算月份。
- FR-4.2：发起前先查库：该 economy+有效月份已存在结果时直接返回该结果并标注"当月已有结果"，不调用 LLM。
- FR-4.3：生成中对同一 economy+月份的并发/重复请求返回 409"分析生成中"，不排队、不产生第二条记录。
- FR-4.4：调用 `ChatLLM` 一次性对话（系统提示词 = 当前生效的提示词 a 正文；用户消息含经济体、有效月份、可选补充说明），不经过 agent loop / 工具调用 / 多智能体。
- FR-4.5：LLM 超时按失败处理：不留存、前端提示超时可稍后重试。
- FR-4.6：成功结果写入 `macro_cycle_judgment`，持久化的 economy 与 statistics_date 以服务端有效口径为准（防止模型自报月份导致去重失效）。

### FR-5：输出合规校验与重试

- FR-5.1：输出必须为纯 JSON（`json.loads` 可解析；不做 markdown/多余文字的宽容提取），且为含全部 10 个业务字段的对象：economy、statistics_date、current_cycle、judgment_result、dimension_check、meso_verify、history_cycle_anchor、judgment_confidence、core_support、core_risk、extended_remark（11 个字段；extended_remark 允许空字符串，其余须为非空字符串）。
- FR-5.2：current_cycle 必须包含四种标准周期阶段表述之一：衰退期 / 复苏期 / 过热期 / 滞胀期（允许其后附过渡描述）；judgment_confidence 必须包含 高 / 中 / 低 之一。
- FR-5.3：首次不合规时自动重试恰好 1 次（以更强约束消息再次请求）；重试合规则正常入库展示。
- FR-5.4：重试仍不合规则判定失败：不入库，返回"分析失败，请稍后重试"。

### FR-6：历史浏览与详情

- FR-6.1：历史按经济体分组：选择经济体后按月份由近到远返回时间线，每条含 statistics_date、current_cycle（周期阶段）、judgment_confidence、create_time。
- FR-6.2：点击月份记录进入详情：顶部突出 economy、statistics_date、current_cycle、judgment_confidence；下方分区依次展示 judgment_result、dimension_check、meso_verify、history_cycle_anchor、core_support、core_risk；extended_remark 默认折叠、点击展开。
- FR-6.3：历史结果永久保留；提示词编辑不改变既有历史。

### FR-7：提示词管理（仅管理员）

- FR-7.1：提供提示词列表/详情接口，返回 code（a/b/c）、名称、是否可用、正文（a 返回正文；b/c 返回占位说明）、是否可编辑、编排预留标记。
- FR-7.2：编辑接口（PUT）仅受 `require_settings_write_auth` 保护；非授权调用返回 401/403，前端将编辑控件置为不可用并说明。
- FR-7.3：仅允许编辑 a 的正文，且不得改变十项结论的输出结构约束（结构模板与校验规则由代码固定，不参与编辑）；b/c 的编辑返回不可用。
- FR-7.4：编辑保存后只影响后续新发起的分析。

### FR-8：可扩展性预留

- FR-8.1：提示词以数据库记录存储（code、name、prompt_text、enabled、sort_order、orchestration_config JSON 可空、时间戳），新增提示词无需改表。
- FR-8.2：前端提示词条目、后端服务与接口按"code 驱动"组织，b/c 的启用不改动路由与页面骨架。

## Non-Functional Requirements

- NFR-1（配置合规）：新增 DB 连接配置必须通过 env_schema（MACRO_DB_HOST/PORT/USER/PASSWORD/NAME），同步 `.env.example`；禁止在 `agent/src/config/` 之外直接读环境变量；密码不得写入代码或提交到 git（写入 gitignored 的 `agent/.env`）。
- NFR-2（分层与门禁）：新代码遵循 AGENTS.md 分层（macro 业务模块位于 L2；api 位于 L4），不新增反向依赖；`make lint`（lint-deps、ruff 硬规则、安全扫描）必须通过。
- NFR-3（可测试性）：宏观数据探测、LLM 调用、MySQL 访问三者均可注入/mock；单元测试不依赖真实 MySQL 与网络；新增后端 pytest 与前端 vitest，`make test-fast` 与前端 vitest 相关用例通过。
- NFR-4（健壮性）：DB 不可达时，历史/发起接口返回明确错误信息（503 风格业务错误），不导致 API 进程崩溃；连接短开短用、异常不泄漏密码。
- NFR-5（安全）：所有新接口默认在现有鉴权之后（读接口 `require_auth`，写接口 `require_settings_write_auth`）；沿用 loopback 默认绑定，不扩大监听面。
- NFR-6（前端一致性）：新页面/组件沿用现有 Tailwind 设计 token 与 i18n 机制（至少补 zh-CN、en 文案）；支持深色模式；交互状态（加载/禁用/错误/折叠）完整。
- NFR-7（性能）：单次判定为同步一次性调用，请求超时可配置（默认复用 LLM timeout）；历史列表为单经济体简单索引查询。

## Constraints

- **Technical**：Python 3.11+；新增依赖 `pymysql`（写入 pyproject 并安装到 .venv）；MySQL 8，库名 `vibe`，表/字段/索引严格按用户 DDL（`macro_cycle_judgment`）；应用启动或首次访问时以 `CREATE TABLE IF NOT EXISTS` 保证表存在。提示词表为新增表。
- **Business**：本期仅 a 可用；周期阶段四分类标准表述不可改；经济体+月份唯一；重试恰好 1 次；历史永久保留。
- **Dependencies**：LLM 需已配置可用 provider（用户现有 LANGCHAIN_PROVIDER 配置）；MySQL 本机可达；探针为可选增强（akshare/FRED key 缺失不阻断主流程）。

## Assumptions

- A1：以"当前日期上一个完整自然月"作为最新可得数据月份的推算基准（宏观月度指标普遍存在约 1 个月发布时滞）。
- A2：用户提供的 MySQL root 账号仅用于本机开发库；连接信息走环境变量，默认 host=127.0.0.1、port=3306、user=root、db=vibe，密码经 `agent/.env` 注入。
- A3：本系统为单机本地优先应用，loopback 操作者即视为"管理员"；非 loopback 时凭 API Key 获得编辑权限（与 settings 写权限一致）。
- A4：模型具备目标经济体宏观常识，提示词中不强制附带实时宏观数据快照；补充说明与探针仅用于决定"能否分析/按哪一月分析"，不确定内容由模型写入 extended_remark。
- A5：提示词 a 的标准正文以需求中给定文本为初始值（系统角色 + 输出要求 + JSON 结构），允许管理员改正文但不改代码侧结构校验。

## Acceptance Criteria

### AC-1：左侧栏目与提示词列表
- **Type**: `rule`
- **Given**: 使用者已登录 Web 主界面
- **When**: 使用者打开左侧菜单并进入"宏观经济分析"栏目
- **Then**: 页面在 `/macro` 展示 a/b/c 三个提示词条目，a 标注可用、b/c 标注待扩展不可用；每条旁有编辑入口；页面可见"工具编排调用流程"预留入口
- **Pass Condition**: `/macro` 路由存在且菜单项可导航；a 可点击进入历史区；b/c 与编排入口点击均不产生任何分析请求，仅出现后续版本开放提示
- **Evidence**: 前端路由/菜单代码、vitest 组件测试、浏览器实际页面截图

### AC-2：智能体页宏观分析模块位置与构成
- **Type**: `rule`
- **Given**: 使用者位于智能体欢迎页（空会话欢迎屏）
- **When**: 展开示例库分类
- **Then**: 分类行在"A股回测"旁展示"宏观分析"分类；选中后展示提示词 a 交互区（经济体下拉、发起按钮）及不可用的 b/c
- **Pass Condition**: WelcomeScreen 分类中存在"宏观分析"且与 A 股回测相邻；交互区可选择四个预设经济体并发起
- **Evidence**: WelcomeScreen 组件代码、vitest 测试

### AC-3：预设经济体清单约束
- **Type**: `rule`
- **Given**: 使用者在任一宏观分析交互区
- **When**: 打开经济体选择
- **Then**: 只能看到并选择 中国 / 美国 / 日本 / 欧元区，不能输入其他经济体；非清单经济体的后端请求被拒绝（4xx）
- **Pass Condition**: 前端下拉仅 4 项；后端对清单外 economy 返回校验错误且不调用 LLM、不查库写入
- **Evidence**: 后端服务/路由单测（pytest）、前端组件测试

### AC-4：成功生成并入库展示
- **Type**: `rule`
- **Given**: 经济体"中国"在有效月份无历史结果，探针就绪（或显式指定月份），LLM 返回含全部字段且周期阶段/置信度表述标准的合法 JSON
- **When**: 使用者发起分析
- **Then**: 系统一次性调用 LLM，将 11 个字段写入 `macro_cycle_judgment`（economy/statistics_date 以服务端口径为准），并返回完整结果；前端以结论优先分层形态展示
- **Pass Condition**: mock LLM 合法输出时，pytest 断言仓储收到一行含全部字段的插入且返回体字段齐全；前端渲染顶部结论 + 六个分区 + 默认折叠的扩展备注
- **Evidence**: 后端服务单测（fake 仓储 + mock ChatLLM）、前端 vitest、真实 MySQL 手工验证行数据

### AC-5：同月结果复用
- **Type**: `rule`
- **Given**: 该 economy+有效月份已存在判定记录
- **When**: 再次发起
- **Then**: 不调用 LLM，直接返回已有结果并带"已有/缓存"标记
- **Pass Condition**: 单测中 ChatLLM 调用次数为 0，返回体与库中记录一致且 `cached=true`
- **Evidence**: pytest 服务层测试

### AC-6：生成中防重复
- **Type**: `rule`
- **Given**: 某 economy+月份判定正在进行（模拟 LLM 调用未返回）
- **When**: 同口径第二次请求到达
- **Then**: 返回 409 与"分析生成中"语义；第二个请求不产生插入
- **Pass Condition**: pytest 并发/锁测试断言 409 且仓储插入仅 1 次；前端按钮在生成中禁用并提示
- **Evidence**: pytest、前端测试

### AC-7：输出不合规自动重试一次
- **Type**: `rule`
- **Given**: LLM 首次返回含多余文字/非法 JSON，第二次返回合法 JSON
- **When**: 发起分析
- **Then**: 系统恰好再请求 1 次，最终成功入库；若第二次仍不合规，则不入库并返回失败
- **Pass Condition**: pytest 分别断言"首次坏+二次好→成功且 LLM 恰调用 2 次"与"两次都坏→失败、0 插入、失败语义"
- **Evidence**: pytest

### AC-8：周期阶段/置信度表述校验
- **Type**: `rule`
- **Given**: LLM 返回的 current_cycle 不含四阶段任一标准词，或 judgment_confidence 不含 高/中/低
- **When**: 校验输出
- **Then**: 判定为不合规并触发 FR-5.3 重试流程
- **Pass Condition**: 参数化 pytest 覆盖：标准词+过渡描述通过；非标准词不通过
- **Evidence**: pytest

### AC-9：数据不足的拦截与补充后放行
- **Type**: `rule`
- **Given**: 就绪探针明确无数据/报错（或经济体不支持），且用户未指定月份/补充
- **When**: 发起分析
- **Then**: 不调用 LLM，返回"数据不足"业务状态并给出可继续方式
- **And When**: 同一请求携带显式 statistics_date 或 supplement
- **Then**: 跳过探针拦截，正常调用 LLM 执行分析
- **Pass Condition**: mock 探针返回不足 → pytest 断言无 LLM 调用与数据不足响应；携带月份/补充 → 断言调用发生
- **Evidence**: pytest、前端状态渲染测试

### AC-10：超时不留存
- **Type**: `rule`
- **Given**: LLM 调用抛出超时异常
- **When**: 发起分析
- **Then**: 不插入任何记录，返回超时失败语义；锁被释放，稍后可重新发起
- **Pass Condition**: pytest 模拟超时异常 → 0 插入、错误状态正确、同口径再次请求可进入（不被锁挡）
- **Evidence**: pytest

### AC-11：历史时间线与详情
- **Type**: `rule`
- **Given**: 某经济体存在多条月份记录
- **When**: 查询历史与某月份详情
- **Then**: 列表按月份倒序返回摘要字段；详情返回全部 11 字段；前端详情页顶部结论突出、六分区顺序正确、扩展备注默认折叠
- **Pass Condition**: pytest 仓储/接口断言顺序与字段；vitest 断言分区顺序与折叠态
- **Evidence**: pytest、vitest

### AC-12：提示词编辑权限与生效范围
- **Type**: `rule`
- **Given**: 编辑者具备 settings 写权限（loopback/API Key）；不具备者发起 PUT
- **When**: 分别请求 PUT 提示词 a 正文
- **Then**: 有权限者保存成功且后续判定使用新正文；无权限者得到 401/403；既有历史不变；尝试编辑 b/c 或改动结构模板被拒绝
- **Pass Condition**: pytest（TestClient 覆盖授权与未授权）+ 服务测试断言新调用使用新正文；前端对无权限者禁用编辑
- **Evidence**: pytest、前端测试

### AC-13：配置与建表合规
- **Type**: `rule`
- **Given**: 配置了 MACRO_DB_* 环境变量的本机环境与空的 `vibe` 库
- **When**: 后端首次使用宏观模块
- **Then**: 自动创建 `macro_cycle_judgment`（字段/索引与用户 DDL 一致）与提示词表并播种 a/b/c；env 门禁、lint-deps、ruff 硬规则通过；密码不出现在代码/提交中
- **Pass Condition**: 真实 MySQL 中 `SHOW CREATE TABLE` 与 DDL 关键字段/索引一致；`make lint` 通过；`git diff` 无明文密码
- **Evidence**: MySQL 查询输出、make lint 输出、git 检查

### AC-14：数据库不可达的优雅失败
- **Type**: `rule`
- **Given**: MySQL 连接失败（错误端口/凭据）
- **When**: 调用历史或发起接口
- **Then**: 返回明确的服务不可用错误，不抛出未处理异常、不使进程崩溃、响应不含密码
- **Pass Condition**: pytest 用连接失败的 fake/真实错误配置断言错误响应与日志脱敏
- **Evidence**: pytest

### AC-15：结果详情信息架构质量
- **Type**: `rubric`
- **Dimension**: 结论可达性与研究可用性
- **Scale**: 1-5
- **Anchors**: 1 = 字段堆砌、投资者看不到结论；3 = 有结论但层级混杂、研究人员需来回翻找；5 = 首屏即见经济体/月份/周期阶段/置信度，六分区顺序符合 BDD，扩展备注折叠自然，投资者与研究人员都能在一屏内各取所需
- **Pass Threshold**: >= 4
- **Evidence**: 浏览器截图、独立审查走查

### AC-16：宏观模块与现有产品体验一致性
- **Type**: `rubric`
- **Dimension**: 视觉与交互一致性
- **Scale**: 1-5
- **Anchors**: 1 = 新模块风格突兀、破坏欢迎屏/菜单布局；3 = 功能可用但样式细节不一致；5 = 菜单项、分类 chip、面板、弹窗与现有组件/Tailwind token/深色模式/i18n 完全一致，无布局回归
- **Pass Threshold**: >= 4
- **Evidence**: 浏览器明暗主题截图、独立审查走查、既有页面回归检查

## Open Questions

- [x] Q1：使用者角色？→ 两类兼顾（澄清项 1）。
- [x] Q2：分析对象选择方式？→ 预设清单（澄清项 2）。
- [x] Q3：月份确定方式？→ 默认最新月份（澄清项 3）。
- [x] Q4：b/c 本期范围？→ 仅预留（澄清项 4）。
- [x] Q5：编辑与编排本期程度？→ 仅编辑 a 正文，编排预留（澄清项 5）。
- [x] Q6：JSON 不合规处理？→ 自动重试 1 次（澄清项 6）。
- [x] Q7：数据不足处理？→ 提示并支持补充说明/指定月份（澄清项 7）。
- [x] Q8：生成中/超时处理？→ 防重复+状态提示，超时不留存（澄清项 8）。
- [x] Q9：编辑权限？→ 所有人可查看，仅管理员可编辑（澄清项 9）。
- [x] Q10：历史保留？→ 永久保留（澄清项 10）。
- [x] Q11：历史浏览组织？→ 按经济体分组+月份时间线（澄清项 11）。
- [x] Q12：详情展示？→ 结论优先、分层展开、备注折叠（澄清项 12）。
- [ ] Q13（实现期注意，不阻塞）：探针具体指标选取（如中国 CMI/CPI、美国 CPI/UNRATE 等）在实现时按 akshare/FRED 可用序列确定，失败一律降级为 FR-3.3 的推算月份/数据不足路径。
