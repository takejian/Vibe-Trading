# M13 角色广场与角色准入 实施计划

## Repository Research

现有 M12（网页团队编排 + 技能广场）已提供可直接复用的完整范式：

- 后端路由集中在 [swarm_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/swarm_routes.py)：预设列表/详情、`POST /swarm/runs`（支持 `custom` 临时编排与 `skill_trial` 单技能试运行，二者互斥）、运行列表（`kind` 过滤、`target` 模糊、`from/to` 时间区间）、自定义团队 CRUD（`/swarm/custom-teams`）、技能目录/试运行/管理员导入同步。
- 单技能试运行 [skill_trials.py](file:///home/ai/Vibe-Trading/agent/src/swarm/skill_trials.py)：复用整套 swarm 执行机制（store、SSE、取消、成果质量纪律、grounding），图为单 agent/task；`preset_tool_union()` 提供全部预设工具并集。
- 自定义编排校验 [custom_spec.py](file:///home/ai/Vibe-Trading/agent/src/swarm/custom_spec.py)：节点 id 正则、时长 1–1800 秒、工具按预设目录静默裁剪、技能越界硬错误、边校验（悬空/自环/成环/无起点/孤立），`validate_custom_spec_graph` 供自定义团队保存复用。
- 数据模型 [models.py](file:///home/ai/Vibe-Trading/agent/src/swarm/models.py#L260-L327)：`SwarmRun` 含 `kind`（team/skill_trial）、`trial_skill`、`research_target/research_question`；`SwarmAgentSpec` 字段为 id/role/system_prompt/tools/skills/max_iterations/timeout_seconds/model_name/max_retries。
- 技能装配与全局通过状态：[skill_catalog.py](file:///home/ai/Vibe-Trading/agent/src/swarm/skill_catalog.py)、[skill_approvals.py](file:///home/ai/Vibe-Trading/agent/src/swarm/skill_approvals.py)（JSON 文件持久化）。路径助手 [paths.py](file:///home/ai/Vibe-Trading/agent/src/config/paths.py)。
- worker 渲染：[worker.py](file:///home/ai/Vibe-Trading/agent/src/swarm/worker.py#L600-L608) 用 `_FallbackDict` 安全渲染 prompt 模板，system_prompt 仅替换 `{upstream_context}`。
- 前端：[SwarmStudio.tsx](file:///home/ai/Vibe-Trading/frontend/src/pages/SwarmStudio.tsx)（tab: studio/history/skills；view: gallery/edit/run），组件目录 [components/swarm/](file:///home/ai/Vibe-Trading/frontend/src/components/swarm)（PresetGallery/FlowCanvas/NodeEditorPanel/LaunchBar/RunView/HistoryList/SaveTeamDialog/SkillSquare），纯图逻辑 [swarmGraph.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/swarmGraph.ts)，API 封装 [api.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts#L572-L661)。
- 导航：[Layout.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/layout/Layout.tsx#L22-L34) 的 `NAV` 数组；路由 [router.tsx](file:///home/ai/Vibe-Trading/frontend/src/router.tsx#L60-L82)；i18n 共 9 个语种（locales/*.json）。
- 管理员判定：沿用 `VIBE_TRADING_ENABLE_SKILL_ADMIN`（运维管理员开关，loopback 单用户模型）。M13 的放开/取消通过复用同一开关，不新增环境变量。
- 测试布局：后端 `agent/tests/test_swarm_*.py`（37 个），前端 `SwarmStudio.test.tsx`、`swarmGraph.test.ts` 等。

### 关键设计决定

1. **角色引用（role_ref）**：内置角色 = `"{preset_name}:{agent_id}"`（冒号是路径合法字符，角色 ref 用本模块自有正则校验，不走 host path 白名单）；自建角色 = 无冒号的 `role-<hex>` id。有冒号即内置。
2. **运行新 lineage**：`SwarmRun.kind` 新增 `"role_run"`，新字段 `trial_role`。角色单独运行**不自动通过**（区别于技能试运行），由管理员手动放开。
3. **自建角色持久化**：`<runtime_root>/swarm/roles/{id}.json`；初始 `approved=false`。
4. **画布与角色本体**：节点携带 `role_ref`，画布引入后仍可临时改 duty/skills/timeout，不回写角色本体；角色名（role）画布不可改。
5. **失效引用**：发起评估与另存/更新团队时，凡节点带 `role_ref`，后端强制解析且要求当前已通过，否则 HTTP 400；无 `role_ref` 的历史节点（旧数据/旧空白节点）按遗留口径放行。

## Files and Modules

### 后端（agent/）

- `src/config/paths.py`：新增 `get_roles_dir()` → `<root>/swarm/roles`。
- `src/swarm/models.py`：`SwarmRun` 新增 `trial_role: str | None = None`；更新 `kind` 注释（增加 role_run）。
- `src/swarm/roles.py`（新建）：`CustomRole` 模型 + `RoleStore`（JSON CRUD、全局重名校验、要素校验、approve/unapprove）。
- `src/swarm/role_catalog.py`（新建）：从预设聚合内置角色分组、角色档案解析（内置/自建统一入口）、业务用途摘要派生。
- `src/swarm/role_runs.py`（新建）：`build_role_run()` 与 `role_run_succeeded()`，仿 skill_trials。
- `src/swarm/custom_spec.py`：节点读取并校验可选 `role_ref`（解析存在 + 已通过），随团队保存/发起强制执行。
- `src/swarm/runtime.py`：`start_run` 新增 `role_run` 参数（与 custom_spec/skill_trial/resume 互斥）。
- `src/api/swarm_routes.py`：新增角色与角色运行端点；运行列表 `kind` 模式与摘要项增加 role_run/trial_role。
- 测试（新建）：`tests/test_swarm_roles.py`、`tests/test_swarm_role_runs.py`、`tests/test_swarm_role_routes.py`。

### 前端（frontend/）

- `src/lib/api.ts`：角色相关类型与 API 封装。
- `src/lib/swarmGraph.ts`：`FlowNodeDraft` 增加 `roleRef`；payload 序列化带 `role_ref`；新增从角色档案生成节点草稿的函数。
- `src/pages/RoleSquare.tsx`（新建）：角色广场页（分组 + 组内搜索 + 创建 + 详情三页签 + 页头管理操作）。
- `src/components/swarm/RolePickerDialog.tsx`（新建）：已通过角色选择弹窗（画布"新增角色"入口）。
- `src/pages/SwarmStudio.tsx`：移除空白建节点，改为 RolePickerDialog；预设角色节点也写入 roleRef。
- `src/components/swarm/NodeEditorPanel.tsx`：有 roleRef 时角色名只读；其余编辑能力不变。
- `src/components/layout/Layout.tsx`：新增 `/roles` 菜单项。
- `src/router.tsx`：新增 `/roles` 路由（懒加载）。
- `src/i18n/locales/*.json`：9 个语种新增 roleSquare 等文案键（非英语种可先落英文文案）。
- 测试（新建/更新）：`pages/__tests__/RoleSquare.test.tsx`（新建）、`pages/__tests__/SwarmStudio.test.tsx`（更新）、`lib/__tests__/swarmGraph.test.ts`（更新）。

## Implementation Steps

1. **路径与模型**：`get_roles_dir()`；`SwarmRun.trial_role` 与 kind 扩展。
2. **自建角色存储 `roles.py`**：
   - `CustomRole`：id、name、purpose、system_prompt、tools、skills、max_iterations、timeout_seconds、approved、approved_at、created_at、updated_at。
   - `RoleStore`：原子写（沿用 tempfile+os.replace 模式）、损坏行跳过；create/update 校验：name 非空且 ≤80 字符、**全局唯一**（内置角色显示名集合来自全部预设 agent 的 `role` 字段 + 全部自建角色名）、system_prompt 非空、timeout 1–1800 整数、skills 必须在"已装配且已通过"集合、tools 必须在 `preset_tool_union()` 内（越界即 400，不静默，保证角色本体干净）。
   - approve（置位 + approved_at）/unapprove。
3. **角色目录 `role_catalog.py`**：
   - `builtin_role_names()`：全部预设 agent 的 role 显示名（供重名校验）。
   - `list_role_groups()`：每个预设一个分组 `{ref(preset name), title, description, roles:[{ref:"preset:agent_id", name, purpose(由 system_prompt 首行清洗截断派生)}]}`；自建角色作为独立分组返回（含 approved 标记）。
   - `resolve_role(ref)` / `get_role_profile(ref)`：内置从预设解析完整档案；自建从 RoleStore 读取；未知 ref 抛 KeyError/ValueError。
   - `is_role_approved(ref)`：内置恒真；自建查 store。
4. **角色运行 `role_runs.py`**：
   - `build_role_run(role_ref, target, question)`：三者非空校验 → resolve_role → 单 agent/task：内置用该角色自身 tools/skills/system_prompt（system_prompt 中非 `{upstream_context}` 的占位符用安全 FallbackDict 按 target/question 渲染，保留 `{upstream_context}` 给 worker）；自建用存储要素，tools 再过滤运行期注册表（沿用既有 drop 纪律）；prompt_template 追加 research question；返回 `kind="role_run"`、`trial_role=role_ref` 的 pending SwarmRun。
   - `role_run_succeeded(run)`：completed 且存在非空 summary（或 final_report 非空）。
5. **runtime 接线**：`start_run(..., role_run=None)`，互斥校验；成功路径不写任何自动通过状态。
6. **custom_spec 强制 role_ref 校验**：节点接受可选 `role_ref`；当存在时要求 `resolve_role` 成功且 `is_role_approved`，否则 ValueError（发起、另存、更新团队全部覆盖）；无 role_ref 节点维持遗留行为。
7. **HTTP 端点（swarm_routes.py）**：
   - `GET /swarm/roles`（分组目录，可选 `q` 关键字、`scope=mine|all`）
   - `GET /swarm/roles/{role_ref}/detail`（自有正则 `^[A-Za-z0-9][A-Za-z0-9_.:-]{1,90}$`）
   - `POST /swarm/roles`（空白创建）
   - `PUT /swarm/roles/{role_id}`、`DELETE /swarm/roles/{role_id}`（仅自建；无冒号）
   - `POST /swarm/roles/{role_id}/approve`：管理员开关 + **前置：该角色已有 ≥1 次成功 role_run**（遍历 store 运行记录判定），不满足 409
   - `POST /swarm/roles/{role_id}/unapprove`（仅管理员）
   - `POST /swarm/role-runs`、`GET /swarm/role-runs`（role_ref/target/from/to；`scope=all` 仅管理员，默认本人）
   - `_run_summary_item` 增加 `trial_role`；列表 kind 正则增加 role_run。
8. **前端 API 层与图逻辑**：类型 + 封装；`roleRef` 字段、序列化、`draftFromRoleProfile()`（新节点 id 用 `nextNodeId`，种子取自角色档案）。
9. **RoleSquare 页面**：
   - 列表：内置预设分组（组内搜索）+ 自建角色分组 + "创建角色"空白表单（名称/用途/提示词/能力勾选/技能勾选/时长）。
   - 详情：页头显示状态与按身份显示的操作（创建者：编辑/删除二次确认；管理员：放开通过（不满足前置时置灰并说明）/取消通过）；三页签——角色档案（提示词全文、工具清单、技能清单、能力，只读）、单独运行（标的+问题→RunView）、评估历史（本人 role_run 列表，结论可结构化回看；管理员可切换查看全部）。
10. **SwarmStudio 改造**："＋ 新增角色"打开 RolePickerDialog（仅已通过角色、可搜索、可多选）；预设原角色节点写入 `roleRef="preset:agent_id"`；移除 addNode 空白创建入口。
11. **导航/路由/i18n**：Layout 增加菜单项（icon 选 Users 之外如 UserSquare/Bot）；router 增加 `/roles`；9 个 locale 增加文案键。
12. **后端测试**：角色 CRUD/重名/要素校验；approve 前置与管理员 403；unapprove 后发起团队评估与另存均被拦截（role_ref 失效高亮口径），历史快照与运行记录保留；role_run 构建校验与成功判定。
13. **前端测试**：RoleSquare 渲染/创建/三页签/管理员操作可见性；SwarmStudio 新增角色走弹窗、无空白创建；role_ref 序列化往返。

## Dependencies and Considerations

- 分层门禁（lint-deps）：新模块均在 `src/swarm`（L3）内部，只依赖同层或更低层（presets、models、config、agent.skills 位于 L1）；路由在 `src/api`（L4）。不得新增逆向边。
- 环变量读取门禁：后端新代码需要开关时经 `get_env_config()` 访问，禁止直接 `os.getenv`。
- 内置角色显示名在不同预设间可能重复，重名唯一性只约束"自建 vs 内置/其他自建"，不要求内置之间去重（按预设分组天然消歧）。
- 业务用途简介：预设 YAML 无独立 description 字段，由 system_prompt 首行派生（清洗 Markdown 标记、截断）；不修改任何预设文件。
- 自定义角色引用的工具/技能后续退出清单：角色运行时由注册表 drop 工具；技能越界在发起团队评估时按既有硬错误处理。
- 单用户 loopback 模型下"仅创建者可见"由接口不返回未通过自建角色给他人保证；本地运行时本人可在"自建角色"分组看到全部状态。
- RunView/HistoryList 为通用组件，role_run 复用其结构化 markdown 渲染（残缺表格降级纯文本为既有能力）。

## Validation

- `make lint`：依赖分层 + ruff + 安全扫描（含 env-var 门禁）全部通过。
- `make test`：全量 pytest 全绿（新测试约 20+ 场景）。
- `cd frontend && npx vitest run`：前端测试全绿（新增/更新用例）。
- `make fe-build`：TypeScript 类型检查与生产构建通过。
- 手工/接口抽验（不依赖真实 LLM，用 mock/不合格成果路径）：创建未通过角色 → 管理员无法放开（409）→ 模拟一次成功 role_run 后放开 → 画布可引入 → 取消通过后自定义团队载入失效高亮、发起 400、历史快照仍可回看。

## Risks

- 内置角色 system_prompt 含 `{market}` 等预设变量：用安全 FallbackDict 渲染（未知变量保留/置空），并保留 `{upstream_context}` 占位；若渲染异常按 worker 既有失败路径处理并在测试中固化。
- 冒号 role_ref 与 host path 校验冲突：新端点不使用 `_host_validate_path_param`，采用模块内严格正则；长度上限 90 防止异常输入。
- 旧自定义团队无 role_ref：明确按遗留数据放行，不做阻断式追溯；新引入的角色一律携带 role_ref，存量团队再次另存后自然纳入新口径。
- 多语种文案缺口：非英语种先以英文文案落键，保证 i18next 不回显键名，后续翻译补齐。
