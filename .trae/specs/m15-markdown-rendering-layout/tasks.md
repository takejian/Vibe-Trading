# M15 分析结论 Markdown 规范化 + 布局移位折叠 — 实施计划

## Task 1: 抽取共享 MarkdownContent 渲染组件
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 新建 `frontend/src/components/common/MarkdownContent.tsx`，将 `chat/MessageBubble.tsx` 中的 `MarkdownContent`、`MarkdownErrorBoundary`、remark/rehype 插件链、`markdownComponents`（表格滚动包装、外链安全属性）、`proseClassName`、`MarkdownContentProps` 原样迁移（流式时关闭重插件的行为保留）。
  - 更新全部引用到 common（`MessageBubble.tsx`、`pages/Agent.tsx`、chat 数学测试），消除 chat 耦合。
  - 不新增依赖；package.json 无改动。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-3
- **Test Requirements**:
  - `rule` TR-1.1: 共享组件渲染真实 GFM 表格时输出 thead/th/td、对齐样式（react-markdown v9 输出 inline text-align）、外层 `overflow-x-auto`；标题/列表/加粗/行内代码语义齐全。证据：`components/common/__tests__/MarkdownContent.test.tsx` 4 用例全过。
  - `rule` TR-1.2: 残缺表格不抛错且其余元素正常；渲染异常时错误边界回退纯文本（边界行为随迁移保留，既有 chat 测试守护）。证据：同文件降级用例 + MessageBubble.test.tsx。
  - `rule` TR-1.3: MessageBubble/MessageBubble.math 既有测试零改动断言全过。证据：chat 套件 127 测试全绿。
- **Completion Evidence**:
  - 新文件 `frontend/src/components/common/MarkdownContent.tsx`；MessageBubble.tsx 从 291 行瘦身（插件链/边界迁出），Agent.tsx 引用改为 common；`git diff --stat frontend/package.json` 为空。
  - `npx vitest run src/components/common src/components/chat` → 22 files / 127 tests passed。

## Task 2: RunView 布局重排（全宽画布 + 结论框上移 + 折叠）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 删除 `flex lg:flex-row` 双栏；FlowCanvas+图例全宽独占一行。
  - node-detail-panel 改为 final-decision-panel 紧邻前序的全宽可折叠 section；头部为整行 `<button aria-expanded data-testid="node-panel-toggle">`（角色名+状态+展开/收起文案+Chevron 图标）；body 区 `data-testid="node-panel-body"`。
  - `panelCollapsed` 本地状态默认 false；`handleSelectNode` 选节点时自动展开。
  - 角色结论保留 `max-h-[40vh]` 内滚；角色结论与最终决策均改用共享 `MarkdownContent`；删除裸 ReactMarkdown/remarkGfm。
- **Acceptance Criteria Addressed**: AC-4, AC-5, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-2.1: DOM 顺序 panel→decision 相邻、aside 消失、两处 prose 渲染。证据：`components/swarm/__tests__/RunView.test.tsx` 5 用例全过。
  - `rule` TR-2.2: 折叠 aria-expanded/body 卸载、展开恢复、折叠态选节点自动展开。证据：同文件交互用例。
  - `rubric` TR-2.3: 维度=结构清晰度与表格可读性；自评 **5/5**。证据：浏览器 6 步验证（5 过 +1 工具受限），截图 `/tmp/trae/screenshots/step1-default-layout.png`、`step2-risk-officer-selected.png`、`step3-panel-collapsed.png` 等；表格边框/表头底色/右对齐列/内边距/超宽滚动均符合，折叠后最终决策上移；窄屏因布局已为单列 + overflow-x-auto 具备能力（浏览器工具无法 resize，代码与全宽布局佐证）。
- **Completion Evidence**:
  - RunView.tsx L277-405 新布局；RunView.test.tsx 新增；swarm/SwarmStudio/SkillPlaza/RoleSquare 相关 57 测试全绿。

## Task 3: 9 语言 i18n 文案
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**:
  - `swarmStudio.run` 新增 `analysisTitle`/`expand`/`collapse`；zh-CN/en 完整翻译，ar/de/es/id/ja/ko/pt-BR 按同口径本地化。
- **Acceptance Criteria Addressed**: AC-8
- **Test Requirements**:
  - `rule` TR-3.1: key-parity 与全量 vitest 通过，9 文件均含新 key。证据：全量 vitest 757 全绿（含 i18n parity 套件）。
- **Completion Evidence**:
  - 9 个 locale 文件 L1944-1946 各新增 3 key。

## Task 4: 全量门禁与独立评审准备
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, Task 2, Task 3
- **Description**:
  - 全量 vitest、fe-build（tsc+vite）、make lint；AC 自检；交付独立评审。
- **Acceptance Criteria Addressed**: AC-1~AC-8
- **Test Requirements**:
  - `rule` TR-4.1: 三命令退出码 0。证据：vitest 82 files/757 passed；`make fe-build` ✓ built；`make lint` ALL HARD GATES PASSED。
  - `rule` TR-4.2: 三消费方（SwarmStudio/SkillPlaza/RoleSquare）无回归。证据：全量 vitest 全绿。
- **Completion Evidence**:
  - 见上；临时预览入口 m15-preview.html/src/m15-preview.tsx 已删除，dev 服务器已停；package.json/lockfile 无改动。
