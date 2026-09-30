# M15 分析结论 Markdown 规范化渲染 + 结论框移位与折叠 — 产品需求规格

## Overview

- **Summary**：团队评估运行视图（`RunView`，被「智能体团队编排」「角色广场」「技能广场」三处共用）中，各角色分析结论与最终决策当前使用裸 `ReactMarkdown` 渲染——无排版样式、表格无边框无对齐、层次不清；且角色结论显示框以侧栏形式排在编排画布旁，挤占画布空间，也无法折叠。本次统一 Markdown 渲染方案、规范化表格排版，并将结论框移至「最终抉择」区域上方、支持手动折叠/展开。
- **Purpose**：让 LLM 输出的商业文档式分析结论（多级标题、段落、列表、加粗、表格、公式、代码）结构清晰、行列对齐、一目了然；同时把画布空间还给编排流程图，用可折叠面板提升空间利用率与内容聚焦。
- **Target Users**：查看团队评估进行中状态与历史快照的全部投资者（含只读快照回看场景）。

## Goals

- 采用市场主流且项目内已验证的 Markdown 渲染技术组合，统一聊天与评估视图的渲染效果。
- 所有 Markdown 表格规范化排版：表头明确、边框完整、单元格留白、行列对齐、超宽可横向滚动。
- 结论显示框从编排画布旁移到「最终抉择」区域正上方，全宽展示；编排画布全宽独占一行。
- 结论框提供手动折叠/展开能力，选择画布节点时自动呈现对应角色结论。

## Non-Goals

- 不新增任何第三方依赖（所需库均已在 `package.json` 中）。
- 不改聊天页（Agent/MessageBubble）既有渲染外观与交互，仅做组件归位。
- 不改 `RunDetail.tsx` 的代码查看器（仅渲染 python 代码块，非商业文档场景）。
- 不做折叠状态的跨刷新持久化（不写 localStorage）。
- 不涉及后端改动；不新增环境变量。
- 不调整「最终抉择」面板自身的展开/收起逻辑（保持现状：完成后默认展示）。

## Background & Context

- 现有成熟技术栈（聊天页已用）：`react-markdown@9` + `remark-gfm@4`（表格/任务列表/删除线）+ `remark-math@6` + `rehype-katex@7` + `rehype-highlight@7`，排版用 `@tailwindcss/typography@0.5` 的 prose 体系，已在 `tailwind.config.ts` 注册。
- 共享渲染器 `MarkdownContent`（含数学分隔符归一化、渲染错误边界、表格横向滚动包装、外链安全属性）目前物理位于 `components/chat/MessageBubble.tsx`，被 `MessageBubble` 与 `pages/Agent.tsx` 引用。
- `RunView.tsx` 当前布局（L269-372）：`flex lg:flex-row` 一行两栏——左 `FlowCanvas`（flex-1）+ 右 `<aside data-testid="node-detail-panel" class="lg:w-96">`；其下才是 `<section data-testid="final-decision-panel">`。两处 Markdown 均为 `<ReactMarkdown remarkPlugins={[remarkGfm]}>` 裸渲染，无 prose 类名，故表格只有浏览器默认样式。
- BDD 5.11 原型原为侧栏并排；BDD 5.12（L2384-2399）明确快照详情结论须结构化呈现（标题层级、列表、加粗、表格），「残缺不成表的段落降级为纯文本原样展示，其余内容不受影响」。
- react-markdown v9 默认不渲染原始 HTML（未启用 rehype-raw），LLM 内容天然无 XSS 注入面，无需额外 sanitize。

## Functional Requirements

- **FR-1 统一渲染器**：将 `MarkdownContent` 抽取为与聊天无关的共享组件（`components/common/MarkdownContent.tsx`），渲染管线与排版类名与聊天现状一致；`MessageBubble`、`Agent.tsx` 改为从共享位置引用，聊天外观零变化；`RunView` 的角色结论与最终决策正文统一使用该组件。
- **FR-2 文档级结构**：标题（h1-h6）、段落、有序/无序列表、加粗/斜体、引用、分割线、行内/块级代码（含代码高亮）、GFM 任务列表、删除线、链接（新标签页+noopener）、数学公式均按统一 prose 样式呈现。
- **FR-3 表格规范化**：GFM 管道表渲染为带边框表格；表头有底色且字重明确；单元格有水平/垂直留白；表头默认左对齐；列对齐语法（`:---` 左、`---:` 右、`:--:` 居中）正确反映到对齐；表格超宽时在容器内横向滚动而不挤压页面。
- **FR-4 降级与健壮性**：残缺/不成表的 Markdown 段落降级为普通文本原样展示，不报错且不影响同篇其他元素渲染；渲染异常时错误边界回退为保留换行的纯文本（沿用现有边界行为）。
- **FR-5 布局重排**：`RunView` 中编排流程图（含状态图例）全宽独占一行；原角色结论框（node-detail-panel）移动为「最终抉择」面板的直接上方区块、全宽；两个面板视觉层次为「角色分析结论 → 最终决策」自上而下；窄屏下同样纵向堆叠。
- **FR-6 折叠/展开**：结论框头部提供折叠/展开开关（按钮含 chevron 图标、可点击标题区、`aria-expanded` 与可访问名称）；折叠后仅保留头部（角色名+状态+开关），结论正文、错误、进度备注不渲染；再次点击展开恢复。初始为展开状态。
- **FR-7 节点联动**：点击画布任一节点，结论框标题更新为该角色名与状态、正文切换为该角色结论；若当前处于折叠状态，选择节点动作自动展开面板（点击节点的意图即查看结论）；用户随后仍可手动折叠，在切换到其他节点前保持折叠。未选择节点时面板显示「点击任一角色查看分析」提示（展开态）。
- **FR-8 多语言**：新增文案（结论框标题、折叠/展开可访问名称）9 个语言文件齐全，无 raw key。

## Non-Functional Requirements

- **NFR-1 兼容性**：渲染组合为社区主流、React 19/Vite 下已运行的成熟方案；不引入新依赖、不增大首屏 bundle（组件为已打包代码的归位）。
- **NFR-2 回归安全**：聊天流式/非流式渲染、数学公式、表格、外链行为保持现状（由既有 MessageBubble 测试守护）。
- **NFR-3 工程门禁**：`npx vitest run` 全绿、`make fe-build`（tsc）无错、`make lint` 通过。
- **NFR-4 视觉一致**：沿用既有 design token（border/card/muted/foreground、深浅色模式），不引入自定义 CSS 文件。

## Constraints

- **Technical**：React 19 + TypeScript + Tailwind + shadcn 风格 token；测试用 vitest + testing-library；不得为测试改动生产组件的可观察行为。
- **Business**：历史快照（readOnly）与实时评估共用同一 RunView，布局/渲染对两种模式一致。
- **Dependencies**：仅使用 package.json 既有依赖。

## Assumptions

- 「显示框」指当前画布右侧的角色分析结论面板（node-detail-panel），而非「最终抉择」面板本身；后者位置与自动展开逻辑不变。
- 折叠状态仅保存在组件内存中：切换节点自动展开、切换 run/卸载后重置为默认展开。
- 最终决策正文较长时保留现有 `max-h-[50vh]` 内部滚动；角色结论保留 `max-h-[40vh]` 内部滚动，折叠不受影响。

## Acceptance Criteria

### AC-1: 共享 Markdown 渲染器归位并被三处复用
- **Type**: `rule`
- **Given**：共享组件 `components/common/MarkdownContent.tsx` 存在
- **When**：检查 MessageBubble、pages/Agent.tsx、RunView 的引用
- **Then**：三者均从共享位置引用同一渲染器；聊天相关渲染代码（插件链/prose 类名/错误边界/数学归一化）行为保持；package.json 依赖列表无变化
- **Pass Condition**：代码审查 + 既有 MessageBubble/MessageBubble.math 测试全过 + `git diff package.json` 为空
- **Evidence**：源码引用、vitest 结果

### AC-2: GFM 表格规范化排版
- **Type**: `rule`
- **Given**：一篇含标准 GFM 表格（表头、多行、含左/右/居中对齐列、宽度超出容器的长内容列）的 Markdown
- **When**：经共享渲染器（RunView 最终决策/角色结论场景）渲染
- **Then**：输出含 `table/thead/th/td`；表头有底色与字重样式；表格具备边框与单元格 padding；三列对齐 class/style 正确；外层存在 `overflow-x-auto` 滚动容器
- **Pass Condition**：组件测试断言上述 DOM 结构与类名
- **Evidence**：新增共享渲染器测试（真实 react-markdown，不 mock）

### AC-3: 残缺表格降级与渲染异常兜底
- **Type**: `rule`
- **Given**：① 只含表头分隔线残缺、不成表的 Markdown；② 触发渲染子组件异常的内容
- **When**：渲染
- **Then**：① 残缺内容以普通段落/文本呈现，其余标题列表等元素正常；② 错误边界回退为 `whitespace-pre-wrap` 纯文本，不抛出到页面
- **Pass Condition**：组件测试两条均通过（沿用 MessageBubble.math.test 同口径）
- **Evidence**：vitest

### AC-4: 结论框移至最终抉择上方且画布全宽
- **Type**: `rule`
- **Given**：RunView 加载任一团队评估
- **When**：检查布局 DOM
- **Then**：画布容器与状态图例独占一行（无 w-96 侧栏并排）；`node-detail-panel` 为全宽区块且是 `final-decision-panel` 的紧邻前序兄弟；两者均在画布行之后
- **Pass Condition**：RunView 测试断言 DOM 顺序与不再存在 lg:flex-row 双栏结构（类名/父子关系断言）
- **Evidence**：新增/更新 RunView 测试

### AC-5: 结论框手动折叠/展开与节点选择自动展开
- **Type**: `rule`
- **Given**：已选中一个有结论的节点
- **When**：点击折叠开关→再点击展开；折叠态下点击另一个节点
- **Then**：折叠后 `aria-expanded=false` 且结论正文不在文档中；展开后恢复；折叠态选择新节点自动展开并显示新节点角色名与结论
- **Pass Condition**：RunView 测试三条交互断言
- **Evidence**：vitest

### AC-6: 角色结论与最终决策统一文档级渲染
- **Type**: `rule`
- **Given**：含标题、列表、加粗、表格、行内代码的任务 summary 与 final_report
- **When**：RunView 渲染两处正文
- **Then**：两处 DOM 均经过共享渲染器（出现 prose 容器与对应语义标签），而非裸 ReactMarkdown
- **Pass Condition**：测试断言两处容器含 prose 类名且表格/标题语义存在
- **Evidence**：vitest

### AC-7: 结论排版视觉质量
- **Type**: `rubric`
- **Dimension**：结构清晰度与表格可读性
- **Scale**: 1-5
- **Anchors**：1 = 表格无边框/错位、标题正文无层次；3 = 元素齐全但间距或对齐一般；5 = 表头明确、行列对齐、留白舒适、层级分明、超宽表可横向滚动、深浅色均清晰
- **Pass Threshold**: >= 4
- **Evidence**：实现者浏览器/截图自检记录 + 独立评审复核

### AC-8: 多语言与工程门禁
- **Type**: `rule`
- **Given**：新增 i18n key
- **When**：运行 key 一致性测试、全量 vitest、tsc/vite build、lint
- **Then**：9 语言文件均含新 key（i18n parity 测试过）；748+ 前端测试全绿；fe-build 成功；make lint 通过
- **Pass Condition**：四条命令输出全绿
- **Evidence**：命令输出

## Open Questions

- 无（关键取舍见 Assumptions；审批时可调整）。
