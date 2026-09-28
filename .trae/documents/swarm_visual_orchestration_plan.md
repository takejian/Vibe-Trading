# M12 编队流程可视化编排 — 实现计划

> 需求来源：`docs/BDD.md` V1.1 新增 M12 模块（3.9 / 4.9 / 5.10–5.12 / 6.x / 第 7 章术语）。
> 目标：在网页上展示全部内置团队预设 → 流程图临时调整角色与协作关系（实时校验）→ 填标的与研究问题一键发起 → 流程图实时联动 → 评估快照进入"我的评估历史"（仅本人、长期留存）。

## 0. 现状关键事实（调研结论）

- 后端：`SwarmRuntime.start_run(preset_name, user_vars, ...)` 只接受**预设名**，由 `build_run_from_preset()` 从 YAML 构建 `SwarmRun`（agent/task 1:1）；`validate_dag`/`topological_layers` 已存在于 `swarm/task_store.py`。
- HTTP：`GET /swarm/presets` 仅返回摘要；`POST /swarm/runs`、`GET /swarm/runs`、`GET /swarm/runs/{id}`、SSE `/swarm/runs/{id}/events`、cancel/retry 已具备（`agent/src/api/swarm_routes.py`）。
- Worker 注入上游结论的**唯一通道**是 system_prompt 中的 `{upstream_context}` 占位符（`worker.py:312`）；用户消息用 `task.prompt_template.format_map(user_vars)` 渲染，缺失变量有兜底文案。
- `final_report` 自动取最后一层第一个有总结的 task（`runtime.py:646-652`）——末层节点即"最终决策角色"。
- run.json 已完整持久化 agents/tasks/final_report/user_vars —— **快照无需新存储**，自定义编排天然随 run 留存。
- 前端：React 19 + Vite + TS；导航 `components/layout/Layout.tsx`、路由 `router.tsx`；API 封装 `lib/api.ts`（含 `swarmSseUrl` 带票据）；SSE 可参照 AlphaZoo 的原生 EventSource 模式；i18n 有**严格键 parity 测试**，10 个 locale 文件必须同步加键。
- 本地单用户应用，数据隔离在 `~/.vibe-trading`（可经 VIBE_TRADING_HOME 改），"仅本人可见"由现有运行根目录隔离天然满足。

## 1. 范围界定

**做**：预设浏览、模板起步的临时编排（增删节点、改职责/能力勾选/时长、改连线）、实时校验、发起、实时状态联动、节点侧栏、最终决策默认展开、取消、历史快照回看。

**不做**（BDD 明确排除或未要求）：个人/共享方案另存、空白画布自建、skills/model/迭代次数编辑、跨用户共享、修改内置 YAML。

---

## 2. 后端改动（agent/）

### 2.1 `swarm/models.py`：SwarmRun 增加 3 个可选字段

```python
customized: bool = False          # 是否为网页自定义编排发起
research_target: str | None = None   # 评估标的（快照/历史列表用）
research_question: str | None = None # 研究问题
```

均为带默认值可选字段，旧 run.json 兼容；不在任何位置读取环境变量（遵守 env gate）。

### 2.2 新模块 `swarm/custom_spec.py`：自定义编排的构建与校验（核心）

入参契约：

```python
# spec 由前端提交
{
  "nodes": [
    {"id": "bull_advocate",        # 原预设节点沿用原 agent id；新节点自定义 id
     "role": "多头研究员",
     "duty": "system_prompt 文本（职责说明，必填）",
     "tools": ["get_market_data", ...],   # 必须 ⊆ 该预设能力目录
     "timeout_seconds": 1800,
     "source_task_id": "task-bull",       # 原预设节点带此字段，用于保留 prompt_template；新节点无
     "is_new": False}
  ],
  "edges": [{"upstream": "bull_advocate", "downstream": "risk_officer"}],
  "target": "600519.SH",
  "question": "当前市场环境下做多还是做空"
}
```

函数：
- `validate_custom_spec(preset_data: dict, spec: dict) -> NormalizedSpec`
- `build_run_from_custom_spec(preset_name: str, spec: dict, user_vars: dict) -> SwarmRun`

**业务校验（违反即 ValueError → HTTP 400，错误信息分类、可展示）**：
1. 节点 ≥ 1；node id 去重并按安全片段净化（禁 `/ \ ..` 空串，规则同 agent_artifact_dir）。
2. role、duty 去空白后非空；timeout 必须为 1–1800 的正整数。
3. tools 逐项必须 ∈ **预设能力目录**（预设全部 agent tools 的并集，去重排序）；越界项剔除（沿用 M8"未预批准能力装配时剔除"纪律），不因此报错；原节点 skills 原样保留，新节点 skills=[]。
4. edges：端点必须存在；禁自环；重复边去重。
5. DAG 无环（复用 `validate_dag`）。
6. ≥1 个起点（入度 0）；节点总数 >1 时，与任何边都不相连的节点判"孤立"。
7. 单节点图合法（既是起点也是终点）。

**构建规则**：
- 每个 node 生成一个 SwarmAgentSpec + 一个 SwarmTask（task id 统一 `task-{slug(node_id)}`，内部维护 node→task 映射解析 edges）。
- 原节点：system_prompt 取提交的 duty（即用户可编辑职责）、tools 取勾选项、timeout 取编辑值、skills 与 max_iterations 沿用原值；prompt_template 用 `source_task_id` 对应的原模板。
- 新节点：默认 max_iterations=25；prompt_template 用通用模板（`Fulfill your assigned role for {target} and address the research question.`）。
- 所有有入边的节点：system_prompt 末尾若缺 `{upstream_context}` 则自动追加（保证上游结论可注入，worker 不改动）。
- input_from 自动生成：每条入边 `{安全键(up_id): upstream_task_id}`，键名 `[^a-z0-9_]→_`、去重。
- 每个 task 的 prompt_template 末尾**逐字追加**研究问题一行（`Research question: <question>`，question 非空时），保证全队回应同一问题；user_vars 同时写入规范键 `target`、`question`（与预设自有声明变量合并，缺失变量如 market 仍走 worker 兜底文案）。
- run.preset_name = 来源预设名；customized=True；research_target/question 落字段。
- run id 生成沿用现有格式；返回 status=pending 的 SwarmRun。

### 2.3 `swarm/presets.py`：新增 `get_preset_detail(name)`

返回画布所需完整定义（现有 `inspect_preset` 不含 system_prompt/timeout/prompt_template，不满足编辑需求）：
- name/title/description/variables
- agents[]：id, role, system_prompt, tools, skills, timeout_seconds, max_iterations
- tasks[]：id, agent_id, depends_on, input_from, prompt_template
- tool_catalog：并集去重排序
- layers：复用 topological_layers 给出分层（画布同层布局用）
异常：FileNotFoundError / ValueError 透传由路由转 404/400。

### 2.4 `swarm/runtime.py`：start_run 增加可选参数

签名追加 `custom_spec: dict | None = None`：
- 为 None：走原 `build_run_from_preset` 路径，行为字节级不变。
- 非 None：走 `build_run_from_custom_spec`，随后同样设置 provider/model 元数据、`validate_dag`、create_run、起线程；grounding 预取因 user_vars 含 target 自动生效。
- resume_from 与 custom_spec 互斥（retry 路径不传 custom；恢复沿用原 run 的 agents/tasks，已由现有 resume 逻辑保证）。

### 2.5 `api/swarm_routes.py`

1. 新增 `GET /swarm/presets/{name}/detail`（require_auth）：返回 get_preset_detail；404/400 映射。
2. `POST /swarm/runs` body 增加可选 `custom: object`；透传 `custom_spec=payload.get("custom")`；ValueError → 400（沿用现有异常映射）。
3. `GET /swarm/runs` 列表项增补：`customized`、`research_target`、`research_question`、`final_report_excerpt`（final_report 前 280 字符；无则 null）。
4. `GET /swarm/runs/{id}` 返回增补 customized/research_target/research_question（agents/tasks/final_report 已有，快照视图够用）。

### 2.6 后端测试（agent/tests/，pytest 风格对齐现有 swarm 测试）

新增 `test_swarm_custom_spec.py`：
- 基于 investment_committee 的 happy path：构建出 4 agents/4 tasks、边→depends_on/input_from 正确、末层为 decision、customized/target/question 落位；
- 环 / 孤立 / 悬空端点 / 自环 / 无起点 / duty 空白 / timeout=0 / id 非法 各自 ValueError；
- 越界 tool 被剔除、目录内保留；原节点 skills 保留、新节点 skills 空；
- `{upstream_context}` 自动追加（已有占位符不重复加）；question 追加到模板；单节点图合法。
扩展 `test_swarm_route_contracts.py`：detail 端点 200/404；custom 发起 400（造环）；列表项新字段存在。
不发起真实 LLM（与现有 swarm 单测一致，仅构建/契约层）。

---

## 3. 前端改动（frontend/）

### 3.1 纯逻辑与类型（先做、可单测）

`lib/swarmGraph.ts`（新）：
- 类型：`FlowNodeDraft`（id/role/duty/tools/timeout/sourceTaskId/isNew）、`FlowEdge`、`GraphIssue`（级别 + 关联 nodeId/edgeId + 文案键）。
- `computeLayers(nodes, edges)`：Kahn 分层（同层数组），有环时返回环信息。
- `validateGraph(nodes, edges)`：与后端同口径产出问题列表——cycle（含参与节点）、orphan、dangling、no-start、duplicate-edge/self-loop、duty-empty、timeout-not-positive。
- `isLaunchable(issues)`、`toCustomPayload(nodes, edges, target, question)`。

`lib/api.ts`：
- 新增类型 `SwarmPresetDetail`、`SwarmRunSummary` 扩字段（customized/target/question/final_report_excerpt）；
- `getSwarmPresetDetail(name)`；
- `createSwarmRun` 扩参：`(preset_name, user_vars, custom?)`。

### 3.2 页面与组件

新增路由 `/swarm`，导航在"宏观分析"之后加入"智能体团队"（icon 用 lucide `Users`，i18n 键 `layout.swarmStudio`）。

- `pages/SwarmStudio.tsx`：容器，4 个视图状态：gallery → edit → run → history（顶部切换：编排 / 我的评估历史）。
- `components/swarm/PresetGallery.tsx`：拉 `/swarm/presets`，卡片展示全部预设（名称/场景简介/角色数），选中拉 detail 进入画布。
- `components/swarm/FlowCanvas.tsx`：
  - 按 computeLayers 分层渲染（自上而下：行=层，列=同层节点），SVG 画边（上游→下游）；
  - 节点卡片显示角色名、能力数、时长；状态色由外部传入（编辑态显示校验高亮；运行态显示等待/分析中/完成/失败/受阻）；
  - 点击节点 → 右侧 NodeEditorPanel。
- `components/swarm/NodeEditorPanel.tsx`：角色名、职责说明（必填）、能力勾选（**只能勾 detail.tool_catalog 内项**；原节点默认勾原 tools）、执行时长（正整数）、[删除节点]；边列表（每条可删除）+ "添加协作连线"（上/下游两个 select，禁自环/重复）。
- `components/swarm/LaunchBar.tsx`：评估标的、研究问题（必填）；校验问题汇总（红，高亮关联节点/边）；`[重置为预设原样]`、`[发起评估]`（不合法置灰）。
- `components/swarm/RunView.tsx`：
  - 发起后拿 run id，用 `api.swarmSseUrl(id)` 建原生 EventSource（参照 AlphaZoo 模式：done 关闭、ticket 已在 URL 内）；
  - 事件映射任务状态（pending/blocked=等待·受阻、in_progress=分析中、completed=已完成、failed/cancelled=失败），先 GET 详情做水位 hydration；
  - 同层同时高亮；点节点侧栏显示：进行中→当前职责/进展事件摘要；完成→task.summary；失败→error；
  - 末层（最终决策角色）完成后**默认展开** final_report 面板（做多/做空方向与理由，markdown 渲染复用 lib/markdown）；
  - `[取消评估]` 调 cancelSwarmRun。
- `components/swarm/HistoryList.tsx`：GET /swarm/runs 列表（发起时间、预设、标的、问题、终态 i18n、结论摘要）；打开记录 → 只读 RunView/FlowCanvas 快照（用 run.agents/tasks 重建图，状态定格终态，不可编辑）。

### 3.3 i18n

`en.json` 新增 `swarmStudio.*`（标题、三步、校验文案、状态、历史表头等）与 `layout.swarmStudio`；zh-CN 翻译；其余 8 个 locale 按 parity 测试要求**同步补齐全部键**（先填英文/同值，避免缺键）。文案中的插值保持 `{{var}}` 与 en 一致。

### 3.4 前端测试（vitest，对齐 `__tests__` 约定）

- `lib/__tests__/swarmGraph.test.ts`：分层、环/孤立/悬空/无起点/空职责/非法时长/单节点、launchable、payload 生成。
- `components/swarm/__tests__/FlowCanvas.test.tsx`：给定草稿渲染层数与高亮；非法时发起按钮置灰（mock api）。
- `pages/__tests__/SwarmStudio.test.tsx`：mock api，断言预设卡片全部渲染、选中后进画布、非法编排拦截（参照 Macro.test.tsx 的 mock 方式）。

---

## 4. 实施顺序（每阶段可独立验证）

1. **P1 后端核心**：models 字段 → custom_spec.py（构建+校验）→ 单测。
2. **P2 后端接口**：preset detail → runtime 分支 → 路由扩展 → 路由契约测试 → 跑定向 pytest。
3. **P3 前端基础**：swarmGraph.ts + 单测；api.ts 类型与接口。
4. **P4 前端界面**：gallery → canvas/node editor/launch → run view/SSE → history → 路由导航 → i18n。
5. **P5 组件测试与全量门禁**：vitest、`npm run build`、`make lint`、`make test-fast`；本地起服务手工走查投资委员会 600519.SH 全流程（校验拦截用例 + 发起/SSE 契约；真实 LLM 全链路按需手动跑一次）。

## 5. 验收对照（BDD 3.9 → 实现）

| BDD 场景 | 落点 |
| --- | --- |
| 全部预设展示 / 卡片要素 | GET /swarm/presets + PresetGallery |
| 流程图载入、节点要素 | GET presets/{name}/detail + FlowCanvas |
| 临时增删改、能力目录边界、仅本次生效 | custom_spec 校验剔除；不写 YAML；reset 重载原始 detail |
| 实时四类硬伤+要素拦截 | validateGraph（前端即时）+ validate_custom_spec（后端 400 双保险） |
| 标的/问题必填、示例协作顺序、四态、受阻、侧栏、最终决策默认展开、取消 | LaunchBar + RunView/SSE + 现有 runtime 依赖门禁与末层 final_report |
| 节点内步骤自主、协作顺序固定 | 不改 worker ReAct；DAG 调度照旧 |
| 快照留存/同视图回看/仅本人/长期 | run.json 既有持久化 + 列表/详情字段；运行根目录隔离；无自动清理 |

## 6. 风险与注意

- **i18n parity**：漏加任一 locale 键，前端测试即红——10 个文件必须同批改。
- **占位符**：自定义 system_prompt 必须由后端补 `{upstream_context}`，否则下游拿不到上游结论。
- **final_report 取值**：取末层首个有总结任务；前端以末层节点作为"最终决策角色"，与后端口径一致。
- **安全边界不放松**：tools 只能收窄到预设目录；不开放 shell 能力勾选（custom 请求沿用 include_shell_tools 的请求级判定，不从 payload 传入）。
- **lint 分层**：新代码只在 swarm(L3) 与 api(L4) 内依赖，禁止新增逆向边；不读 os.environ。
- 兼容：SwarmRun 新字段全可选；start_run 新参数默认 None；旧客户端/旧 run.json 不受影响。
