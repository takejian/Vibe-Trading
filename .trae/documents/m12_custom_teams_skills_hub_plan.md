# M12 扩展：自定义团队 + 角色技能目录 + 技能广场/试运行准入 + 技能包导入同步 + 历史筛选与结构化结论 — 实施计划

> 需求来源：`docs/BDD.md` V1.2（M12 新增场景，3.9/4.9/5.10/5.12/5.13/6/7 章）。本计划经 18 轮决策卡澄清，结论以 BDD 文档为准。

## Repository Research（现状结论）

1. **Swarm 运行与持久化**
   - Run 聚合根 `SwarmRun`（[models.py](file:///home/ai/Vibe-Trading/agent/src/swarm/models.py#L260-L319)）持久化为 `<runtime_root>/swarm/runs/{run_id}/run.json`（[store.py](file:///home/ai/Vibe-Trading/agent/src/swarm/store.py)，根目录来自 `config/paths.py:get_swarm_runs_dir()`）。已有可选字段 `customized/research_target/research_question`。
   - `SwarmRuntime.start_run(preset_name, user_vars, ..., resume_from=None, custom_spec=None)`（[runtime.py](file:///home/ai/Vibe-Trading/agent/src/swarm/runtime.py#L288-L374)），custom 与 resume 互斥；后台线程跑 `_run_loop`，结束时写终态，`final_report` 自动取末层首个有 summary 的 task。
   - `build_run_from_custom_spec()`（[custom_spec.py](file:///home/ai/Vibe-Trading/agent/src/swarm/custom_spec.py)）已做节点/边/DAG/timeout/tools 白名单校验；**新节点 skills 目前写死 `[]`，原节点沿用 preset skills，请求体不能传 skills**。
   - 路由集中在 [swarm_routes.py](file:///home/ai/Vibe-Trading/agent/src/api/swarm_routes.py)：preset 列表/detail、runs CRUD、SSE、cancel/retry；全部挂 `require_auth`。

2. **用户身份模型**：系统是 loopback 单用户本地应用（API_AUTH_KEY 是访问密钥而非多租户身份），运行资料天然按本机用户隔离。BDD 的"仅本人可见"沿用现有 `~/.vibe-trading` 归属口径即可，无需新建用户体系。

3. **技能机制**
   - 技能包 = 一个含 `SKILL.md`（frontmatter：`name/description/category` + 正文）的目录；`SkillsLoader`（[skills.py](file:///home/ai/Vibe-Trading/agent/src/agent/skills.py#L97-L189)）加载 bundled `agent/src/skills/` 与用户目录 `~/.vibe-trading/skills/user/`（用户同名覆盖 bundled）。注意用户目录常量硬编码 `Path.home()`，未走 config runtime root。
   - swarm worker 以 `agent_spec.skills` 作 `skill_allowlist` 构造 registry 并过滤 system prompt（[worker.py](file:///home/ai/Vibe-Trading/agent/src/swarm/worker.py#L575-L590)、[tools/__init__.py](file:///home/ai/Vibe-Trading/agent/src/tools/__init__.py#L310-L360)）；空 skills = 不限制。
   - `get_preset_detail()`（[presets.py](file:///home/ai/Vibe-Trading/agent/src/swarm/presets.py#L286)）已返回每 agent 的 skills，但未返回技能并集目录。
   - **不存在**技能"通过状态/试运行/导入/同步"概念，本计划新建。

4. **配置与依赖**
   - 特性开关模式：`env_schema.py` 的 `VIBE_TRADING_ENABLE_*`（如 `:454`）；CI 强制 `os.environ` 只能在 `src/config/` 读取。
   - `python-multipart>=0.0.18` 已在依赖中，FastAPI 文件上传可用。

5. **前端现状**
   - `SwarmStudio.tsx` 状态机 tab(studio/history) × view(gallery/edit/run)；组件在 `src/components/swarm/`（PresetGallery/FlowCanvas/NodeEditorPanel/LaunchBar/RunView/HistoryList）。
   - `RunView.tsx` 已用 `ReactMarkdown` 但**未挂 remark-gfm**（表格不渲染）；`remark-gfm` 已在 package.json。
   - i18n 10 locale 均有 `swarmStudio.*` 键树；测试 jsdom + 真实 i18n（英文断言）。

## 总体设计

- 自定义团队：`<runtime_root>/swarm/custom_teams/{team_id}.json`，内容 = 画布 draft（nodes/edges + 元数据 name/description/source_preset/时间戳）。
- 技能通过状态：`<runtime_root>/skills/approvals.json`，全局唯一映射 `{skill_name: {approved, approved_at, source_run_id}}`。
- 第三方技能包：导入/同步落到 `<runtime_root>/skills/user/<skill>/`（即 SkillsLoader 用户目录，导入后 worker 立即可用）；同步来源清单 `skills/sync-manifest.json`。
- 技能试运行：复用 swarm 运行时——构造单 agent 的 `SwarmRun`（`kind="skill_trial"`），同一 store/SSE/cancel/成果验收/快照设施；`/swarm/runs` 列表按 `kind` 分离团队评估与试运行历史。
- 管理员能力（导入/同步）由新开关 `VIBE_TRADING_ENABLE_SKILL_ADMIN` 门控，前端经 capabilities 接口决定是否展示管理区；同步源由 `VIBE_TRADING_SKILL_SYNC_SOURCE`（本地目录或 zip URL）配置，未配置返回 409。

## Files and Modules

### 后端
- `agent/src/config/paths.py`：新增 `get_custom_teams_dir()`、`get_skill_approvals_file()`、`get_user_skills_dir()`、`get_skill_sync_manifest_file()`。
- `agent/src/config/env_schema.py`：FeatureFlags 新增 `vibe_trading_enable_skill_admin: bool`（alias `VIBE_TRADING_ENABLE_SKILL_ADMIN`，默认 False）；新增 `vibe_trading_skill_sync_source: str`（alias `VIBE_TRADING_SKILL_SYNC_SOURCE`，默认 ""）。同步更新 `agent/.env.example`。
- `agent/src/agent/skills.py`：用户技能目录默认值改由 `config.paths.get_user_skills_dir()` 解析（保持 VIBE_TRADING_HOME 一致性）；新增列出全部技能元数据的轻量函数（复用 `_load_skill_dir`）。
- `agent/src/swarm/models.py`：`SwarmRun` 新增 `kind: str = "team"`（`team` | `skill_trial`）、`trial_skill: str | None = None`（均带默认值，旧 run.json 兼容）。
- `agent/src/swarm/custom_spec.py`：
  - 抽出纯图校验函数供自定义团队保存复用；
  - 节点接受 `skills: list[str]`，合法域 = preset 技能并集 ∪ 全局已通过技能；**未知/已退出技能硬报错（400）并指出节点与技能名**（BDD：失效引用阻断发起）；tools 静默剔除的信任边界不变；
  - 新节点可携带 skills（不再写死空）。
- `agent/src/swarm/custom_teams.py`（新建）：`CustomTeam` pydantic 模型 + `list_teams/get_team/save_team/update_team/delete_team/team_exists_by_name`；原子写 JSON；重名拦截；删除不触碰 runs。
- `agent/src/swarm/skill_approvals.py`（新建）：`SkillApprovalStore`——`is_approved/names_approved/mark_approved/load`，JSON 原子读写；全局共享。
- `agent/src/swarm/skill_catalog.py`（新建）：枚举全部已装配技能（bundled+user，名称/描述/category/来源）+ join 通过状态；金融关键词词典；技能并集工具函数。
- `agent/src/swarm/skill_packages.py`（新建）：zip 包安全校验（防路径穿越、仅接受顶层技能目录、必须含 SKILL.md 且 name/description/正文齐备）、金融相关性校验（name/description/category/正文命中金融词典，或 frontmatter `finance: true`）、装配入 user 目录；一键同步（本地目录或 zip URL → 下载临时 zip → 同一装配管线；按 sync-manifest 识别新增/更新/下架；**仅下架本次同步来源曾装的包**，不动 bundled 与手动导入；更新保留通过状态）。
- `agent/src/swarm/skill_trials.py`（新建）：`build_skill_trial_run(skill_name, target, question)`——单 agent/单 task：skills 白名单 `[skill_name]`；tools 取**全部内置 preset 已批准工具的并集**（运维预批准池，registry 会二次过滤实际可用项）；duty 指示其加载并运用该技能回答问题；`preset_name=f"skill:{skill_name}"`、`kind="skill_trial"`、`trial_skill=skill_name`、target/question 写入 user_vars 与研究字段。
- `agent/src/swarm/runtime.py`：`start_run(..., skill_trial: dict | None = None)`（与 custom_spec/resume 互斥）；`_run_loop` 终态落盘处加钩子：skill_trial 且整场 completed、末层 task completed 且 summary 非空 → `mark_approved(skill_name)`；失败/取消不写通过。
- `agent/src/api/swarm_routes.py`：
  - `/swarm/runs` GET 增加查询参数 `kind`(默认 team)、`target`(research_target 子串模糊)、`from_`/`to`（created_at 日期区间含端点）；列表/详情返回 `kind/trial_skill`；
  - 新增自定义团队路由：GET `/swarm/custom-teams`、POST、GET/PUT/DELETE `/{team_id}`（ValueError→400，重名→409，不存在→404）；
  - 新增技能广场路由：GET `/swarm/skills/catalog`、GET `/swarm/skills/capabilities`（`{admin_enabled}`）、POST `/swarm/skill-trials`、GET `/swarm/skill-trials`（复用 store，按 kind 过滤）；
  - 新增管理路由（开关关闭→403）：POST `/swarm/skills/import`（`UploadFile` zip）、POST `/swarm/skills/sync`（未配置源→409）；
  - 试运行 run 的 SSE/详情/取消直接复用既有 `/swarm/runs/{id}/*`。
- `agent/api_server.py`：注册新路由（沿用 `register_swarm_routes` 同一挂载点，新路由写在同文件内，免改注册签名）。

### 前端
- `src/lib/api.ts`：SwarmRun 类型加 `kind/trial_skill`；runs 列表支持 `{kind,target,from,to}`；新增 customTeams CRUD、getSkillCatalog/getSkillCapabilities/createSkillTrial/listSkillTrials/importSkillPackage(FormData)/syncSkills。
- `src/lib/swarmGraph.ts`：`FlowNodeDraft` 加 `skills: string[]`；`validateGraph` 增加"引用已退出可选清单技能"问题码（目录由调用方传入 preset 并集 + approved 集合）；`toCustomPayload` 带 skills；`draftFromPresetDetail` 带 skills。
- `src/components/swarm/`：
  - `PresetGallery.tsx`：内置 / 我的自定义团队两分区 + 空状态；自定义团队卡片进入 edit（携带 team id）。
  - `NodeEditorPanel.tsx`：新增"使用技能"勾选组（默认 preset 并集）+ "＋ 新增"弹层（全局已通过技能清单，可搜索勾选）。
  - 新建 `SaveTeamDialog.tsx`：名称必填、简介选填、重名错误展示；画布模式 builtin|custom，自定义模式显示 `保存更新 / 另存为新团队 / 删除（二次确认）`。
  - `HistoryList.tsx`：筛选栏（标的关键字 + 起止日期 + 查询/清空），走查询参数。
  - `RunView.tsx`：两处 `ReactMarkdown` 挂 `remarkPlugins={[remarkGfm]}`（表格/删除线等 GFM）；节点信息展示技能；试运行单节点视图复用。
  - 新建 `SkillSquare.tsx`：技能卡片（名称/描述/状态徽标）、试运行发起栏（标的+问题必填）、本技能试运行历史列表（时间/标的/问题/终态/查看→RunView 只读）、管理员区（capabilities.admin_enabled 时显示：上传 zip、一键同步、结果/拒绝原因提示）。
  - `SwarmStudio.tsx`：tab 扩为 studio/history/skills；gallery/edit 携带 team 来源与保存回调。
- i18n：10 locale 增补新键（en、zh-CN 完整文案；其余 8 语种填英文，沿用既定做法；不用 i18next 复数后缀）。

### 测试
- 后端新建/扩展：`tests/test_swarm_custom_teams.py`、`tests/test_swarm_skill_catalog_approvals.py`、`tests/test_swarm_skill_trials.py`、`tests/test_swarm_skill_packages.py`、扩展 `test_swarm_custom_spec.py`（skills 合法/未知阻断/新节点带 skills）、`test_swarm_route_contracts.py`（新路由、筛选参数、403/409/400/404 映射）。
- 前端：swarmGraph skills 校验用例；NodeEditorPanel 技能勾选/新增弹层；SaveTeamDialog 重名；HistoryList 筛选；SkillSquare 渲染与试运行 payload；RunView gfm 表格渲染。

## Implementation Steps（依赖顺序）

1. **P1 后端地基**：paths + env_schema/.env.example + skills.py 用户目录 config 化；models 加 kind/trial_skill。
2. **P2 自定义团队**：custom_teams 存储 + custom_spec 支持 skills 硬校验（接 approvals，P3 前先落 approvals store）→ 实际顺序：先做 skill_approvals/skill_catalog，再改 custom_spec。
3. **P3 技能广场后端**：approvals + catalog + skill_trials 构建器 + runtime 钩子（通过判定）。
4. **P4 技能包引入**：zip 安全/金融校验/装配 + 一键同步（manifest、增/更/下架语义）。
5. **P5 路由**：custom-teams CRUD、skills catalog/capabilities、skill-trials、import/sync、runs 筛选与字段；后端全套单测。
6. **P6 前端**：api.ts → swarmGraph → 编辑器技能区 + 自定义团队保存/管理 → 历史筛选 → RunView GFM → SkillSquare 页签 → SwarmStudio 接线 → i18n；前端测试。
7. **P7 门禁**：ruff、lint-deps、pytest -m unit、vitest、tsc+vite build、i18n parity。

## Dependencies and Considerations

- 层级约束：新模块全部放 `src/swarm/`（L3）；swarm→`src.agent.skills` 的同层引用 worker.py 已存在（WARNING，非新增逆向边）；路由 L4→swarm L3 合规；config 仅在 L0 读 env。不新增 grandfathered 之外的 reverse edge。
- tools 与 skills 两条信任边界独立：tools 仍只在 preset 白名单内、目录外静默剔除；skills 合法域 = preset 并集 ∪ 已通过清单，域外**显式报错阻断**（BDD 要求失效技能高亮+禁止发起）。
- 试运行成果合格判定沿用编队既有"未达标"纪律：run completed 且末层 task 有非空 summary 才算成功并写通过；失败不撤销既有通过。
- 自定义团队引用技能被下架：载入团队时前端给目录状态，发起时后端 400 双保险。
- 快照独立性：run.json 已内嵌完整 agents（含 skills）/tasks，团队删除或技能下架均不影响历史回看。
- 金融相关性为启发式判定：词典命中 metadata（name/description/category）或正文关键词，或 frontmatter 显式 `finance: true`；拒绝时逐项返回原因；管理开关默认关闭。
- 同步源为运维侧配置（目录/zip URL），未配置时接口 409、前端按钮提示；产品侧暂无官方市场地址，不臆造 URL。
- 单用户身份："仅本人可见"= 本机 runtime root 归属，与现行评估历史口径一致，不引入用户体系。
- 前端测试 shell 输出须重定向日志再读（venv：`.venv`，前端 vitest 用 node_modules/.bin）。

## Validation

- 后端：新增 pytest 文件全绿；`pytest -k swarm` 回归；`pytest -m unit` 全套；改动文件 ruff rc=0；`python scripts/lint-deps` 0 errors。
- 前端：新增 vitest 用例全绿；vitest 全套；`npm run build` rc=0；i18n parity 全过。
- 手工（可选，需真实 LLM 凭证，不在自动化门禁内）：`scripts/dev up` 走查 自定义团队另存→再编辑、技能勾选发起、技能广场试运行通过后入清单、历史筛选、快照表格渲染、zip 导入拒绝/通过。

## Risks

- **金融启发式误判**：词典+显式标记双通道、拒绝原因可见；管理开关默认关，运营可复查包内容。
- **zip 导入安全**：限单包大小/文件数、拒绝 `..`/绝对路径/符号链接、只落 user 技能目录、不执行包内任何代码（技能仅作文本加载，与现有加载模型一致）。
- **同步下架误伤**：只删除 sync-manifest 记录的来源包，bundled/手动导入绝不删除；下架前已有通过状态不影响 run 快照。
- **真实端到端未验**：试运行成功判定依赖真实 LLM 产出，自动化测试 mock worker 成果；真实凭证链路列为可选手工项，汇报时如实说明。
- **旧数据兼容**：SwarmRun 新字段全默认值；approvals/manifest/teams 文件缺失按空态初始化。
