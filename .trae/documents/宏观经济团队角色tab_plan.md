# 宏观经济分析：智能体团队 / 宏观角色 Tab 实施计划

## Repository Research

### 现状结论

1. **菜单与页面已存在**：左侧菜单"宏观经济分析"（路由 `/macro`）已在
   [Layout.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/layout/Layout.tsx#L20-L37)
   和 [router.tsx](file:///home/ai/Vibe-Trading/frontend/src/router.tsx#L72-L98)
   注册；页面为 [Macro.tsx](file:///home/ai/Vibe-Trading/frontend/src/pages/Macro.tsx)，
   当前平铺展示提示词 a/b/c、工具编排预留入口、按经济体浏览的历史时间线。
2. **智能体页面"宏观分析"模块已存在**：
   [WelcomeScreen.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/chat/WelcomeScreen.tsx#L362)
   已嵌入 `MacroAnalysisPanel`（embedded 形态），本次无需改动。
3. **后端团队 API 已完备**（[swarm_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/swarm_routes.py)）：
   - `GET /swarm/presets`：团队摘要（name/title/description/agent_count/variables）
   - `GET /swarm/presets/{name}/detail`：完整定义（agents 含 role/system_prompt/tools/skills、
     variables 含 name/description/required、任务依赖）
   - `POST /swarm/runs`：body `{preset_name, user_vars}` 即可按预置编排发起团队运行
     （[runtime.start_run](file:///home/ai/Vibe-Trading/agent/src/swarm/runtime.py#L302-L382)，
     无 custom/skill_trial 时走 `build_run_from_preset`）
   - `GET /swarm/runs/{id}` + SSE `GET /swarm/runs/{id}/events`：运行详情与实时事件
4. **后端单角色 API 已完备**：
   - `GET /swarm/roles`：按 preset 分组的全部角色目录（ref 形如 `preset:agent_id`，
     含 name/purpose），见 [role_catalog.py](file:///home/ai/Vibe-Trading/agent/src/swarm/role_catalog.py#L65-L121)
   - `GET /swarm/roles/{ref}/detail`：角色完整画像
   - `POST /swarm/role-runs`：body `{role_ref, target, question}` 发起单节点角色运行，
     见 [role_runs.py](file:///home/ai/Vibe-Trading/agent/src/swarm/role_runs.py#L51-L100)
5. **前端 API client 已封装全部所需方法**：
   [api.ts](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts#L577-L611) 中
   `listSwarmPresets / getSwarmPresetDetail / createSwarmRun / getSwarmRun / swarmSseUrl`；
   [L712-L761](file:///home/ai/Vibe-Trading/frontend/src/lib/api.ts#L712-L761) 中
   `listRoleGroups / getRoleDetail / createRoleRun`。
6. **运行态展示组件可直接复用**：
   [RunView.tsx](file:///home/ai/Vibe-Trading/frontend/src/components/swarm/RunView.tsx)
   已被 SwarmStudio 与 RoleSquare 同时用于 team run 和 role run（自动订阅 SSE、
   节点状态、final_report、取消、onBack），无需为角色运行另写展示组件。
7. **i18n**：9 个语言文件，`fallbackLng: "en"`
   （[i18n/index.ts](file:///home/ai/Vibe-Trading/frontend/src/i18n/index.ts#L143)）。
   本次新增文案写入 zh-CN.json 与 en.json，其余语言走英文回退。
8. **结论：后端零改动**，本次仅新增前端展示/编排层。

### 关键设计决策

- **固定目录映射放在前端**：BDD 规定的 4 团队 4 主题、18 角色 7 主题是产品定义的
  宏观目录（且 Macro Allocator/Analyst 来自非宏观 preset），以静态映射表 + 现有
  API 数据（name/purpose/profile）实现，不新增后端端点。
- **Tab 懒挂载 + 挂载后保活**：首次点击某 tab 才挂载并拉数据；挂载后用
  `hidden` 类切换而非卸载，保证切换 tab 不中断 SSE 与运行进度；默认 tab
  （周期判定）初次渲染不触发任何新增 API 调用，现有 [Macro.test.tsx](file:///home/ai/Vibe-Trading/frontend/src/pages/__tests__/Macro.test.tsx)
  的 4 个 mock 不受影响。
- **团队发起**：表单字段由 preset detail 的 `variables` 动态生成
  （market/horizon、goal/timeframe、crisis/market、market/goal），前端校验
  required 后以 `createSwarmRun(preset, userVars)` 发起。
- **角色发起**：按 role-runs 契约提供 target（评估标的）、question（研究问题）
  两个必填项；不触发原团队编排。
- 团队/角色运行的结论**不进入**"经济体+月份"周期判定档案，与 BDD 第三节第 7 条一致。

## Files and Modules

- `frontend/src/components/macro/macroCatalog.ts`（新增）：
  4 团队主题映射、18 角色 ref→7 主题映射及类型；团队/角色展示名 i18n key。
- `frontend/src/components/macro/MacroTeamTab.tsx`（新增）：
  4 主题分区、团队卡片展开（简介/角色清单/参数表单）、发起团队运行、内嵌 RunView。
- `frontend/src/components/macro/MacroRoleTab.tsx`（新增）：
  7 主题分区展示 18 角色（数据取自 listRoleGroups 并按静态映射重排）、角色详情
  （来源团队/职责/技能）、target+question 表单、发起角色运行、内嵌 RunView。
- `frontend/src/pages/Macro.tsx`（修改）：
  标题下新增 tab 导航（周期判定/智能体团队/宏观角色）；把现有提示词+历史内容
  保留为默认 tab 内容（仅结构包裹，逻辑不动）；页面容器放宽至 max-w-6xl。
- `frontend/src/i18n/locales/zh-CN.json`、`en.json`（修改）：
  新增 `macro.tabs.*`、`macro.teamTheme.*`、`macro.roleTheme.*`、团队卡片、
  角色发起表单、状态与错误文案。
- 测试（新增）：
  - `frontend/src/components/macro/__tests__/MacroTeamTab.test.tsx`
  - `frontend/src/components/macro/__tests__/MacroRoleTab.test.tsx`
  - 在 `frontend/src/pages/__tests__/Macro.test.tsx` 增补 tab 切换用例
    （默认 tab 既有用例保持不变）。

## Implementation Steps

1. **新建 `macroCatalog.ts`**：定义
   - `MACRO_TEAM_THEMES`：4 项 `{themeKey, presetName}`，顺序
     宏观策略 / 宏观利率外汇 / 地缘分析 / 资产轮转；
   - `MACRO_ROLE_THEMES`：7 项 `{themeKey, refs[]}`，18 个 ref 为
     - 宏观经济与周期：`macro_strategy_forum:global_economist`、
       `macro_strategy_forum:domestic_economist`、
       `sector_rotation_team:cycle_analyst`、
       `equity_research_team:macro_analyst`
     - 利率与外汇：`macro_rates_fx_desk:rates_analyst`、
       `macro_rates_fx_desk:fx_strategist`
     - 大宗商品与通胀：`macro_rates_fx_desk:commodity_inflation_analyst`、
       `geopolitical_war_room:energy_analyst`
     - 地缘政治与供应链：`geopolitical_war_room:geopolitical_analyst`、
       `geopolitical_war_room:supply_chain_analyst`
     - 政策研究：`macro_strategy_forum:policy_analyst`
     - 行业轮动：`sector_rotation_team:prosperity_analyst`、
       `sector_rotation_team:flow_analyst`、
       `sector_rotation_team:rotation_strategist`
     - 综合策略与资产配置：`macro_strategy_forum:chief_strategist`、
       `geopolitical_war_room:chief_strategist`、
       `macro_rates_fx_desk:macro_pm`、
       `etf_allocation_desk:macro_allocator`
2. **改造 `Macro.tsx`**：新增 tab 状态（`cycle|team|role`，默认 cycle）与
   tab 导航按钮（含 testid：`macro-tab-cycle/team/role`）；用"首次激活记录 +
   hidden 类"实现懒挂载保活；现有内容原样放入 cycle 面板。
3. **实现 `MacroTeamTab`**：
   - 挂载时 `listSwarmPresets()`，按静态映射过滤出 4 团队并分区渲染卡片
     （testid：`macro-team-card-{preset}`、"发起团队分析"按钮）；
   - 展开时 `getSwarmPresetDetail(name)`：展示 description、agents 的
     role 列表（purpose 取 API 派生值）、按 variables 生成输入框
     （name/description/required）；
   - 校验 required 后 `createSwarmRun(preset, userVars)` → 用返回 id 渲染
     `RunView`（带 onBack）；发起期间按钮禁用，409 等错误按文案提示；
   - 卡片级状态：仅展开的团队拉 detail；同一团队运行中防重复。
4. **实现 `MacroRoleTab`**：
   - 挂载时 `listRoleGroups()`，建立 `ref → RoleGroupItem` 索引，按
     `MACRO_ROLE_THEMES` 重排为 7 分区（testid：`macro-role-item-{ref}`，
     两个 Chief Strategist 用 ref 天然区分并标注来源团队）；
   - 选中角色时 `getRoleDetail(ref)`：展示来源团队、purpose、skills；
     渲染 target/question 必填表单（testid：`macro-role-target/question/run`）；
   - `createRoleRun({role_ref, target, question})` → RunView；运行中防重复、
     失败/超时提示。
5. **i18n**：zh-CN/en 写入全部新增 key，en 作为其余 7 语言回退。
6. **测试**：
   - 新增两个组件测试：mock API，验证主题分区、18 角色齐全、展开详情、
     表单校验、发起后 RunView 出现（按 runId mock getSwarmRun/SSE 不订阅时
     RunView 仍渲染详情，参考现有 RunView.test 的 mock 方式）；
   - Macro.test.tsx 增补：默认在周期判定 tab、点击 team/role tab 后出现
     对应 testid；原 4 个用例不回归。
7. **自检**：`npm run build`（tsc 类型检查）与 `npx vitest run`
   针对 macro 相关测试；后端无需改动、不动后端测试。

## Dependencies and Considerations

- 复用现有组件：RunView（team/role 双形态已验证）、MarkdownContent、
  lucide 图标、Tailwind 卡片样式与现有 macro 组件保持一致。
- `withAuthTicket` 已在 `swarmSseUrl` 内处理鉴权，tab 内直接使用即可。
- worker 对缺失模板变量用 `_FallbackDict` 渲染为空，因此 required 校验
  必须在前端完成，避免提交空变量运行。
- 用户级 preset 覆盖（~/.vibe-trading/swarm/presets）会改变 preset 内容：
  角色目录若引用的 agent id 消失，`getRoleDetail/createRoleRun` 会返回 4xx，
  前端按错误文案提示，不影响其他卡片。
- en/zh 以外语言暂不补译，符合 fallbackLng 机制与既有发版习惯。

## Validation

- `cd frontend && npx tsc -b`（或 `npm run build`）：无类型错误。
- `cd frontend && npx vitest run src/pages/__tests__/Macro.test.tsx
  src/components/macro src/components/swarm/__tests__/RunView.test.tsx`：
  全部通过。
- 手动验证（后端 `make serve` + 前端 `scripts/dev` 或 npm dev）：
  1. `/macro` 默认周期判定内容不变；
  2. 团队 tab：4 主题 4 卡片、展开见角色与参数、发起后 RunView 实时进度、
     切回周期判定再切回运行不中断；
  3. 角色 tab：7 分区共 18 角色、两个 Chief Strategist 标注来源团队、
     Macro Allocator/Analyst 可发起单角色运行；
  4. 必填项留空时按钮禁用/提示；运行中防重复。
- 后端无改动，无需跑后端套件；如执行可 `make test-fast` 确认无连带影响。

## Risks

- **RunView 在 tab 内嵌布局不适应**（画布宽度）：容器已放宽至 max-w-6xl；
  RunView 自身为自适应布局，RoleSquare 有同款内嵌先例，风险低。
- **懒挂载时机导致默认 tab 额外请求**：通过"点击才挂载"严格规避，现有
  Macro.test 的 4 mock 设计即可验证此约束。
- **18 角色 ref 与 YAML agent id 不一致**：已逐个核对 6 个 preset 的
  id（global/domestic/policy/chief、rates/fx/commodity/macro_pm、
  geopolitical/energy/supply_chain/chief、cycle/prosperity/flow/rotation、
  equity macro_analyst、etf macro_allocator）；测试断言 18 项齐全防回归。
- **范围蔓延**：提示词 b/c、工具编排配置、团队/角色历史入口均不在本期，
  保持 BDD 已确认的"展示 + 可发起"边界。
