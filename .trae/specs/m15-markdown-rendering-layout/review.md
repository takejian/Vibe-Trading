# M15 分析结论 Markdown 规范化 + 布局移位折叠 — 独立评审

- [x] CP-R1: 共享渲染器归位与复用
  - **Type**: `rule`
  - **Covers**: AC-1, AC-6
  - **Evidence**: R1 PASS（三处共同引用 common/MarkdownContent；逐 token 比对零行为漂移；package.json 零改动）

- [x] CP-R2: GFM 表格规范化与降级健壮性
  - **Type**: `rule`
  - **Covers**: AC-2, AC-3
  - **Evidence**: R1 PASS；错误边界抛错路径用例在 R1 后补齐（MarkdownContent.test.tsx，758 全绿）

- [x] CP-R3: RunView 布局重排（全宽画布 + 结论框位于最终抉择上方）
  - **Type**: `rule`
  - **Covers**: AC-4
  - **Evidence**: R1 PASS（panel.nextElementSibling===decision；aside/双栏类删除；SSE/notes/error/取消等既有功能保留）

- [x] CP-R4: 折叠/展开与节点选择自动展开
  - **Type**: `rule`
  - **Covers**: AC-5
  - **Evidence**: R1 PASS；R1 后头部结构改为 h3 标题 + 独立 button（无嵌套交互元素），aria/交互测试更新通过

- [x] CP-R5: i18n 完整且工程门禁全绿
  - **Type**: `rule`
  - **Covers**: AC-8
  - **Evidence**: R1 PASS（9 语言 3 key、JSON 合法无重复 key、parity 双向测试）；id 术语统一为 Perluas/Ciutkan

- [x] CP-U1: 结论排版视觉质量
  - **Type**: `rubric`
  - **Covers**: AC-7
  - **Scale**: 1-5
  - **Anchors**: 1 = 表格无边框/错位、标题正文无层次；3 = 元素齐全但间距或对齐一般；5 = 表头明确、行列对齐、留白舒适、层级分明、超宽表可横向滚动、深浅色均清晰
  - **Pass Threshold**: >= 4
  - **Evidence**: R1 评分 **5/5**（5 张浏览器截图核实：全网格线、表头灰底、数值列右对齐、内边距、折叠上移、节点联动）；深色/窄屏为静态 token/单列布局佐证（F-04 保留 info）

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 独立评审代理复跑 vitest（757）、fe-build、lint；9 locale JSON/重复 key 脚本校验；与 HEAD 逐行比对迁移代码；Read 5 张截图。0 actionable，4 advisory/info：
  - F-01（advisory）错误边界抛错路径无自动化用例 → **已修**：新增 `falls back to plain text when a render child throws`（MarkdownContent.test.tsx），导出 MarkdownErrorBoundary 直接注入抛错子组件断言 `.whitespace-pre-wrap` 回退。
  - F-02（advisory）id 语 expand/collapse 与顶层术语不一致 → **已修**：run 区改为 Perluas/Ciutkan 与顶层一致。
  - F-03（advisory）角色名由 h3 降为 button 内 span，失去标题大纲 → **已修**：头部改为 h3（含角色名+状态）+ 独立折叠 button 的无嵌套结构；RunView 测试改回 heading 角色断言。
  - F-04（info）深色/窄屏无截图 → 保留：dark:prose-invert 与 design token 已在 chat 验证、布局为天然单列 + overflow-x-auto；不阻断。
  - F-05（info）swarm 路由按需加载 MarkdownContent chunk（gzip ~93kB）→ 预期取舍，无动作。
- **Post-review 门禁**: 全量 vitest 758 passed（82 files）；fe-build ✓；lint ALL HARD GATES PASSED。
