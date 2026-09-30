# M14 实施任务清单

> 顺序即依赖顺序；每项含交付物与验证方式。执行前须经用户确认 spec.md。

## 阶段 A — 后端领域模型与存储

- [x] A1. `config/paths.py` 新增 `get_custom_skills_dir()` → `runtime_root/swarm/skills`
- [x] A2. 新建 `agent/src/swarm/custom_skills.py`
  - `CustomSkill` 模型（id/name/purpose/methodology/inputs/outputs/approved/approved_at/derived_from/created_at/updated_at）
  - `CustomSkillStore`：原子写 JSON 记录 + 实体化 `skills/user/custom-<id>/SKILL.md`（create/update/delete 同步目录）
  - 五要素校验、全局重名（含 `assembled_skill_names` 与全部自建名）、长度上限（80/200/20000）
  - 模板解析（仅当前已通过：组装技能查 SkillApprovalStore、自建查本 store）、`derived_from` 留痕、派生独立
  - approve/unapprove（不实体删除目录）、qualified-run 判定辅助
  - 个人 zip 导入（复用 skill_packages 安全解压与校验，all-or-nothing，重名拒绝，不写 manifest）
- [x] A3. 单测 `test_swarm_custom_skills.py`：覆盖 A2 全部规则与实体化

## 阶段 B — 目录/审批集成

- [x] B1. `skill_catalog.py`：catalog 条目增补 ref/kind/derived_from，custom 以记录 approved 为准；`list_approved_skill_names` 并入已通过自建
- [x] B2. `runtime.py._finalize`：自建技能试运行成功不自动 mark_approved（全局技能维持）
- [x] B3. 扩展/新增单测：审批双轨、统一可选目录、catalog 新字段

## 阶段 C — API 路由

- [x] C1. `swarm_routes.py` 新增：custom CRUD、approve/unapprove（管理员+合格前置 409）、import-personal（全员 zip）、skill detail
- [x] C2. `GET /swarm/skill-trials` 增加 scope=mine|all（all 需管理员，同 role-runs）
- [x] C3. catalog 路由输出新字段；确认失效引用校验消费统一 approved 目录
- [x] C4. 路由测试 `test_swarm_custom_skill_routes.py`（含 403/409/400/404 矩阵）

## 阶段 D — 前端页面

- [x] D1. `lib/api.ts`：类型与接口方法（SkillProfile/CustomSkillRequest、catalog 扩展、7 个新方法、scope）
- [x] D2. 新建 `pages/SkillPlaza.tsx`：双一级页签；分组+组内搜索；详情三页签；SkillForm（创建/编辑/派生预填）；删除二次确认；管理员审核按钮；管理员专区；我的评估过滤表
- [x] D3. `Layout.tsx` 增加 `/skills` 菜单项（Sparkles 图标 + layout.skillPlaza）
- [x] D4. `router.tsx` 注册 `/skills`
- [x] D5. `SwarmStudio.tsx` 移除技能 tab 与 SkillSquare/runOrigin 相关死代码
- [x] D6. 删除 `components/swarm/SkillSquare.tsx` 与 `SkillSquare.test.tsx`
- [x] D7. 新增 `pages/__tests__/SkillPlaza.test.tsx`；更新 SwarmStudio 测试断言两 tab

## 阶段 E — 多语言

- [x] E1. 9 个 locale 增加 `layout.skillPlaza` 与 `skillPlaza.*`；清理随 SkillSquare 删除而失效的 key；zh-CN/en 完整，其余语种同 M13 口径

## 阶段 F — 全量验证与评审准备

- [x] F1. `make lint`（layer gate + ruff + safety scanners）
- [x] F2. `make test-fast`（含新增后端用例与前端 vitest）
- [x] F3. `make fe-build`（tsc + vite）
- [x] F4. 按 check_list.md 逐条对照 BDD 3.11/4.11/5.13 自检
- [x] F5. 更新 memory（项目记忆：M14 关键决策与文件落点）
