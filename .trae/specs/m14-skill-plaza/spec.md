# M14 技能广场独立化与技能准入 — 实施规格

> 依据：`docs/BDD.md` V1.3 新增的 M14「技能广场与技能准入」（3.11 验收用例、4.11 业务规则、5.13 原型、6.2 第 10/11/14 条、第 7 章术语）。
> 参照实现：M13 角色广场（`agent/src/swarm/roles.py`、`role_catalog.py`、`role_runs.py`、`agent/src/api/swarm_routes.py`、`frontend/src/pages/RoleSquare.tsx`）。

## 1. 现状关键事实

- 技能 = 含 `SKILL.md`（frontmatter: `name/description/category` + markdown 正文）的目录；`SkillsLoader` 从内置目录 `agent/src/skills/` 与用户目录 `~/.vibe-trading/skills/user/` 加载，**用户目录优先、同名覆盖**。
- 全局审批存 `~/.vibe-trading/skills/approvals.json`（`SkillApprovalStore`，仅 name→approved）；技能试运行（`kind=skill_trial`）成功后 `runtime._finalize` 自动 `mark_approved`。
- 角色可选技能 = `SkillApprovalStore.approved_names() ∩ assembled_skill_names`（`roles.py:_allowed_skills`）。
- 管理员能力开关 = 配置 `vibe_trading_enable_skill_admin`（路由层 `_skill_admin_enabled()`），前端经 `GET /swarm/skills/capabilities` 获取；本产品为单运行时属主模型，无多用户体系，"仅本人可见/管理员"按既有 M13 同口径落地（自建数据归本运行时、审核操作受开关保护）。
- 前端技能广场目前是 `SwarmStudio.tsx` 内第三个 tab（`tab-skills`），渲染组件 `frontend/src/components/swarm/SkillSquare.tsx`；试运行历史走 `GET /swarm/skill-trials`（支持 target/from/to/skill_name 精确过滤）。
- 管理员 zip 导入 `/swarm/skills/import` 与一键同步 `/swarm/skills/sync` 已存在（`skill_packages.py`，含 zip 安全解压、金融相关性与要素校验）。
- 左侧菜单在 `frontend/src/components/layout/Layout.tsx` 的 `NAV` 数组；路由在 `frontend/src/router.tsx`；i18n 共 9 个语言文件。

## 2. 总体设计

### 2.1 后端新增「自建技能」领域（镜像 CustomRole）

新增 `agent/src/swarm/custom_skills.py`：

- `CustomSkill`（pydantic）：`id, name, purpose, methodology, inputs, outputs, approved, approved_at, derived_from, created_at, updated_at`。
  - `purpose`=业务用途简介（≤200 字）；`methodology`=方法论与操作说明全文（必填，≤20000 字）；`inputs`=输入要求；`outputs`=输出约定。
  - `name` 全局唯一（≤80 字，重名含内置/管理员装配技能一律拦截）。
- `CustomSkillStore`（记录目录 `~/.vibe-trading/swarm/skills/<id>.json`，原子写）：
  - `list/get/create/update/delete/approve/unapprove/name_exists`，校验与 `RoleStore` 同构；`create(template_ref=None)` 仅允许以**当前已通过**的技能为模板（组装技能经 `SkillApprovalStore` 判定；自建技能经本 store 判定），模板失效拦截；派生独立、登记 `derived_from`（模板展示名）；编辑保持 `approved`。
  - **实体化（materialize）**：每次 create/update 后将技能写为 `~/.vibe-trading/skills/user/custom-<id>/SKILL.md`：
    ```
    ---
    name: <name>
    description: <purpose>
    category: custom
    ---
    <methodology>

    ## 输入要求
    <inputs>

    ## 输出约定
    <outputs>
    ```
    delete/unapprove 时按规则处理目录：delete 物理删除目录；unapprove **保留目录**（本人仍可试运行，只是不进入全员可选清单——见下）。
  - 个人 zip 导入：复用 `skill_packages._safe_extract_zip`、`_package_dirs`、`_validate_package_dir` 的校验（SKILL.md/要素/金融相关性/zip 安全），通过后逐包生成 `CustomSkill`（name/description 取 frontmatter，methodology 取正文，inputs/outputs 置空，`derived_from=None`）并实体化；整包 all-or-nothing；重名整体拒绝并列原因。不写入 sync manifest，管理员同步不会触碰 `custom-` 前缀目录。

### 2.2 审批两条路径并存

- **全局装配技能**（内置 + 管理员导入/同步）：维持现状——任一试运行成功由 `runtime._finalize` 自动 `mark_approved`。
- **自建技能**：试运行成功**不**自动审批，仅取得前置资格；`runtime._finalize` 在自动审批前先判断 `CustomSkillStore` 是否存在同名自建技能，是则跳过。审批由管理员接口手动完成，前置条件 = 存在至少一条该技能名的成功 `skill_trial`（复用 `skill_trials.trial_succeeded`，镜像 `_role_has_qualified_run`）。
- 统一可选目录：`skill_catalog.list_approved_skill_names()` 改为 =（全局 approved ∩ assembled）∪（自建 approved ∩ 已实体化 assembled）。角色配置与画布技能清单自动跟随，无需改消费方。

### 2.3 目录接口扩展

- `GET /swarm/skills/catalog` 每个条目增加：`ref`（组装技能 `"assembled:<name>"`，自建技能 = 其 id）、`kind`（`bundled`/`user`/`custom`）、`derived_from`（自建可空）；自建条目的 `approved` 以 `CustomSkill` 记录为准（不看 approvals.json）。
- 新增 `GET /swarm/skills/{ref}/detail`：返回五要素 + kind/ref/approved/derived_from/created_at/updated_at；组装技能 inputs/outputs 返回空串（SKILL.md 无此两项，前端显示「—」）。
- 新增路由（均挂既有 `require_auth`）：
  - `POST /swarm/skills/custom`（body: name/purpose/methodology/inputs/outputs + 可选 template_ref）
  - `PUT /swarm/skills/custom/{id}`
  - `DELETE /swarm/skills/custom/{id}`
  - `POST /swarm/skills/custom/{id}/approve`（管理员；409 无合格试运行）
  - `POST /swarm/skills/custom/{id}/unapprove`（管理员）
  - `POST /swarm/skills/import-personal`（multipart zip，全员；返回 installed 列表）
- `GET /swarm/skill-trials` 增加 `scope: mine|all`（与 role-runs 同口径，all 需管理员开关；单属主模型下数据相同，仅权限语义对齐）。
- 管理员 `/swarm/skills/import`、`/swarm/skills/sync` 保持不变。

### 2.4 试运行

- 复用现有 `POST /swarm/skill-trials` 与 `build_skill_trial_run`：自建技能已实体化进 user 目录，`SkillsLoader` 立即可见，无需执行链路改造。
- 未通过自建技能允许本人试运行（实体化后即 assembled）；其成功不改变 approved。

### 2.5 失效引用

- 技能被 unapprove/删除后：从可选清单消失（approved 计算自然排除）。
- 已保存角色（`CustomRole.skills`）与自定义团队（custom_teams JSON）中的技能失效提示：沿用既有「载入时校验 + 高亮拦截」机制，在校验处把技能可选集合来源换成 2.2 的统一目录（现有实现已基于 `list_approved_skill_names` 类口径，补测覆盖即可；若画布节点校验另有入口则一并接入）。
- 历史快照与试运行记录不动（run 自带完整图）。

## 3. 前端设计

### 3.1 新页面 `frontend/src/pages/SkillPlaza.tsx`（路由 `/skills`）

结构镜像 `RoleSquare.tsx`（list/detail/run三视图 + 页签）：

- 顶部一级页签：`技能广场` / `我的评估`。
- 「技能广场」列表视图：
  - 两个分组卡片（复用 `RoleGroupSection` 模式，组内关键字检索）：`内置技能` = kind bundled+user；`自建技能` = kind custom（未通过显示「未通过·我创建」标记）。
  - 头部按钮：`＋ 创建技能`、`⬆ 导入 zip 技能包`（file 选择后直接调个人导入接口；预留入口真实可用）。
  - 管理员专区（capabilities.admin_enabled 才渲染）：管理员 zip 导入 + 一键同步（搬自旧 SkillSquare）。
- 详情视图（三页签 `技能档案 / 试运行 / 试运行历史`）：
  - 档案：五要素只读展示；自建派生显示「派生来源」；组装技能只读。
  - 试运行：标的 + 研究问题表单 → `createSkillTrial` → RunView（同 RoleSquare run 视图）。
  - 试运行历史：`listSkillTrials({skillName})`，本人记录；管理员审核时可切换 scope=all 查看全部（页面提供仅管理员可见的「查看全部人员记录」开关）。
  - 头部操作：
    - 自建技能创建者：`编辑技能`（切换 SkillForm）、`删除技能`（confirm 二次确认）；
    - 任意已通过技能：`另存为新建技能`（进入创建态并预填，模板下拉仅列已通过技能，与角色派生同交互）；
    - 管理员对自建：`放开通过`（无合格记录时按钮置灰带提示，接口 409 信息兜底）/`取消通过`。
- 「我的评估」：跨技能表格（技能名、标的、研究问题、发起时间、终态、查看），过滤条 = 技能名输入 + 标的关键字 + 起止日期；技能名按包含匹配（前端对已加载记录过滤或后端新增 q 参数——采用前端过滤 + skill_name 精确接口兜底，避免后端扩参；默认 limit=100）。
- `SkillForm` 字段：模板下拉（创建态）、名称（必填 ≤80）、用途简介（≤200）、方法论与操作说明（textarea 必填 ≤20000）、输入要求（textarea）、输出约定（textarea）。

### 3.2 编排页瘦身

- `SwarmStudio.tsx` 删除第三个 tab（`tab-skills` 按钮、`tab === "skills"` 分支、`Bookmark` 导入、`SkillSquare` 导入与 `runOrigin === "skills"` 相关回跳逻辑）；仅留「团队编排 / 我的评估历史」。
- 删除 `frontend/src/components/swarm/SkillSquare.tsx` 及其测试；其管理区能力迁入 SkillPlaza。
- 画布角色「使用技能」勾选仍调 `getSkillCatalog`（条目新增字段不破坏现有选择逻辑，按 approved 过滤）。

### 3.3 菜单 / 路由 / API 客户端 / i18n

- `Layout.tsx` NAV 在 `/swarm` 与 `/roles` 之后插入 `{ to: "/skills", icon: Sparkles, label: t('layout.skillPlaza') }`。
- `router.tsx` 注册 `/skills` 懒加载 `SkillPlaza`。
- `lib/api.ts` 新增类型 `SkillProfile`、`CustomSkillRequest`、`CustomSkillSummary`；扩展 `SkillCatalogEntry`（ref/kind/derived_from）；新增方法：`getSkillDetail(ref)`、`createCustomSkill`、`updateCustomSkill`、`deleteCustomSkill`、`approveCustomSkill`、`unapproveCustomSkill`、`importPersonalSkillPackage(file)`；`listSkillTrials` 增加 `scope`。
- 9 个语言文件：新增 `layout.skillPlaza` 与 `skillPlaza.*` 命名空间（title/subtitle/tabs/groups/form/detail/run/history/myEvaluations/admin/import 等全套文案）；移除/保留 `swarmStudio.tabs.skills` 与 `swarmStudio.skills.*`：仅保留仍被画布/RunView 引用的 key，编排页专用文案随旧组件删除。各语种除 zh-CN/en 外按现有英文文案兜底翻译（与 M13 改动同质量口径）。

## 4. 测试计划

### 4.1 后端 pytest（新增 `agent/tests/test_swarm_custom_skills.py`、`test_swarm_custom_skill_routes.py`）

- store：创建（空白/派生）、五要素校验、重名拦截（含对组装技能名）、模板必须已通过、模板失效拦截、编辑保持 approved、删除清实体文件、approved/unapprove 生命周期。
- 实体化：创建/更新后 `SkillsLoader` 立即可加载且正文含三要素；删除后消失；unapprove 后目录仍在、仍可试运行但不在 approved 目录。
- 个人 zip 导入：合法金融包 → 未通过自建技能；非金融/缺要素/坏 zip/路径穿越拒绝；重名拒绝；不写 sync manifest。
- 审批门：无成功试运行 approve → 409；有成功记录 → 通过；自建技能试运行成功**不**自动写 approvals.json；全局技能成功仍自动通过。
- catalog/detail/ref 解析、approved 统一目录含已通过自建、不含未通过自建。
- 路由鉴权：approve/unapprove/管理员 import 在开关关闭时 403；个人导入全员可用。
- 回归：`test_swarm_skill_catalog_approvals.py`、`test_swarm_skill_trials.py`、角色/画布相关测试全绿（必要时更新断言以适配 catalog 新字段）。

### 4.2 前端 vitest

- 新增 `SkillPlaza.test.tsx`：分组渲染与组内搜索、详情三页签、创建/派生表单校验与提交、编辑/删除确认、试运行发起与历史加载、管理员按钮显隐与 approve/unapprove、我的评估过滤、个人 zip 导入调用。
- 更新 `SwarmStudio` 相关测试：断言仅剩两个 tab、`tab-skills` 不存在。
- 删除 `SkillSquare.test.tsx`。
- 全量 `make test-fast`、`npm run build`、`tsc`、`ruff`/layer gate 通过。

## 5. 不做的事（范围边界）

- 不引入多用户账号体系；「仅本人/全员可见」按既有单属主 + 管理员开关口径落地。
- 不做技能版本管理、技能在线市场、技能评分。
- 不改变团队评估、角色运行的执行引擎；不改动全局技能审批 JSON 的既有结构。
- 不新增环境变量（复用 `VIBE_TRADING_ENABLE_SKILL_ADMIN` 既有开关）。
