# M16 关注（自选标的）模块 — 实现评审记录（review.md）

> 评审日期：2026-10-01。实现分支工作区（未提交）。本文档先由实现方填写自测/走查证据，
> 再由独立 fresh-context 评审人只读复核；结论与问题清单追加在文末。

## 1. 交付物清单

### 后端（agent/）
- `src/config/paths.py`：新增 `get_watchlist_dir()` / `get_market_db_path()`（遵循 `VIBE_TRADING_HOME`）。
- `src/watchlist/`（L2 新包，已登记 layer-map，lint-deps 计数 32→33）：
  - `models.py` / `store.py`：私有自选清单 JSON（画像目录隔离）、A股代码规范化、去重、逐行删除。
  - `market.py`：**严禁 LLM 的直连数据边界**——东财 suggest 搜索、push2 ulist 批量行情、stock/get 公司资料；全部 fetcher 可注入。
  - `db.py`：4 张表 DDL（instrument_master / valuation_daily / watchlist_objective_data / chanlun_analysis）与 upsert/查询 CRUD。
  - `role_catalog_filter.py`：确定性三分类（fundamental/technical/general）+ 缠论角色标记；entries 数据注入，不 import swarm。
  - `chanlun_parser.py`：固定中英 7 维度解析，score∈[-5,+5] 整数、confidence 0–1（含 1.5 不被截断的负向前瞻），失败落 structured=false 原文。
  - `analysis.py`：start_analysis / start_objective_fetch / list_analyses / persist_run_artifacts（按 run_id 幂等懒归档）。
- `src/api/watchlist_routes.py`（L4）：13 个端点挂载于 `api_server.py`；symbol 含点号不走宿主 path 白名单，路由内规范化。
- 测试：`test_watchlist_{store,market,db,role_filter,analysis,routes}.py` + `test_chanlun_parser.py`（72 个 watchlist 相关用例被收集）。
- `scripts/local_db/init_local_db.py`：DB 路径改用 `get_market_db_path()`（db-init 同样遵循 VIBE_TRADING_HOME）。

### 前端（frontend/）
- `lib/api.ts`：14 个 watch API 方法 + 完整类型；SSE 复用 swarmSseUrl。
- 9 语言 locales 各注入 watch 命名空间键（键集合强一致，含本轮新增 `watch.an.viewRun`）。
- `layout/Layout.tsx`：一级菜单【关注】（Star 图标，Skills 之后）；`router.tsx`：`/watch`、`/watch/:symbol` lazy 注册。
- `pages/Watchlist.tsx`：三态排序（null 恒排尾）、勾选纯视觉无批量动作、防抖搜索、409 回显、alertdialog 二次确认、骨架/空态/quote_error 黄条、AI 批量对比仅占位。
- `pages/WatchDetail.tsx`：5 Tab（tablist）；概览 8 字段 + 两直连刷新按钮（独立 busy/成败反馈，不覆盖旧数据）；ObjectivePanel 四分区 RawTable + 补充抓取 + 归档 Markdown。
- `components/watch/AnalysisTab.tsx`：必选单选、串行 409 提示、RunView 嵌入、历史按 role 分组倒序、进行中行"查看运行"按钮。
- `components/watch/ChanlunHistory.tsx`：固定 7 维中英顺序、日期筛选、正红负绿、structured=false 原文渲染。
- 测试：Watchlist 10 + WatchDetail 9 + AnalysisTab 6 + ChanlunHistory 5 + viteProxy 新增 1。

## 2. 门禁结果（2026-10-01）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 分层/质量/safety grep | `make lint` | ALL HARD GATES PASSED |
| 后端单元 | `make test-fast` | 1690 passed, 10 skipped |
| 前端单元 | `npx vitest run` | 793 passed (86 files)（Task16 后复跑） |
| 前端构建 | `npm run build`（fe-build） | 成功（仅既有 chunk-size 提示） |
| 前端类型 | `npx tsc -b` | exit 0 |

> Task 16 修复后复跑（2026-10-01 晚）：`make lint` 全绿；`make test-fast` 1690 passed / 10 skipped；
> watchlist 7 个受评测试文件 89 passed（评审基线 83，Task16 净增 6）；`-k "watchlist or chanlun"` 全仓子集 107 passed / 6 skipped；
> 前端 793 passed (86 files)、tsc -b 0、build 成功。

## 3. 端到端走查证据（真实服务 + 真实东财 + 真实 GLM）

走查方式：后端 `make serve`（127.0.0.1:8899，临时 `VIBE_TRADING_HOME=/tmp/m16-home`、显式走查 key），
前端 `scripts/dev`（127.0.0.1:5899），浏览器逐页操作；截图存于走查机 `/tmp/trae/screenshots/m16-*.png`。

| AC | 走查/自动化证据 | 结论 |
| --- | --- | --- |
| AC-1 导航/路由 | 导航出现 Star【关注】（Skills 后）；/watch 与 /watch/:symbol 渲染；vite 双角色代理契约测试 | PASS |
| AC-2 搜索添加 | 搜"茅台"→贵州茅台 600519.SH；列表真实行情：现价 1,258.62、PE 17.67、PB 6.26、总市值 1.57 万亿、行业白酒Ⅱ | PASS |
| AC-3 去重/取消关注 | 409 文案回显有单测；浏览器实测 Unwatch→Cancel 行保留→Confirm 行消失 | PASS |
| AC-4 列表排序/勾选/空态 | 浏览器实测 Price 升降序；勾选无任何批量按钮；空态/骨架测试 10 个 | PASS |
| AC-5 概览两刷新 | 行情刷新绿色成功；公司资料刷新→上市 2001-08-27、总股本 1,250,081,601、白酒Ⅱ（**走查中修复，见 §4.2**） | PASS |
| AC-6 客观原始数据 | 四分区 RawTable 渲染，空显"暂无数据"；fundamental Tab 仅财务分区 | PASS |
| AC-7 补充抓取归档 | 真实 GLM run `swarm-…-0753d7fb`（14 轮、completed、4823 字报告）归档并在客观 Tab 展开为 Markdown | PASS |
| AC-8 角色三分类/缠论 | /watch/agents 实测 technical 7（含 1 缠论标记）、fundamental 17、general 96；浏览器见"缠论"徽章 | PASS |
| AC-9 发起分析 | 必选单选、诉求留空成功发起 run（classic_ta，`…-a02b4ee9`） | PASS |
| AC-10 409 防重 | curl 二次同角色→409 `该智能体对这一标的的分析正在进行中`；浏览器黄条"该智能体已有分析正在进行，请等待完成" | PASS |
| AC-11 历史留存/回看 | 完成报告展开为 **完整 final_report 正文**（非 280 字 excerpt，Task16-B2 修复，浏览器复验含"风险提示"全文）；已完成行新增"查看报告"只读入口直达 RunView；**取关后历史仍可按 symbol 查询**（I4：三历史端点去除关注态强制，test_history_survives_unfollow 覆盖） | PASS |
| AC-12 缠论 7 维入库 | **真实缠论 run** `swarm-20261001-093930-ed18659a`（12 轮、5791 字）懒归档：structured=true，score=-1、confidence=0.55、7 维全部非空；首跑暴露中文数字标题解析缺口并修复（见 §4.5），现有 12 个解析器单测（含该真实报告形状回归） | PASS（真实 run + 单测） |
| AC-13 缠论历史/筛选 | 空态展示；2026-09-01~09-30 Filter 不报错；5 个组件测试 | PASS（空态实测，有数据态由单测覆盖） |
| AC-14 失败不破坏旧数据 | 公司资料接口曾返回 502，页面保留旧值并提示重试；异常映射 502 不写库 | PASS |
| AC-15 批量对比占位 | 仅提示不发请求（Watchlist 测试断言无网络调用） | PASS |
| AC-16 9 语言 | 9 文件键集合一致（i18n parity 测试 36 项） | PASS |
| AC-17 分层/env 门禁 | watchlist L2 不 import L3/L4（catalog 数据注入、runtime lazy）；无 os.getenv 越界；lint 全绿 | PASS |
| AC-U1 交互视觉 | 布局/状态色/徽章/弹窗/反馈完整；走查发现 RunView 入口可发现性问题并修复（§4.3） | PASS（自评，待独立复核） |
| AC-U2 测试质量 | 后端 7 个受评文件 89 passed（基线 83，Task16 净增 6 个针对性用例，另有若干既有测试按新契约重写）；前端全量 793 passed (86 files) 含新增 I3/I5/N7/N8/B2 用例；真实 payload 形状 fetcher 测试补齐网络盲区 | PASS |

## 4. 走查发现的问题与修复（均已完成并回归）

### 4.1 vite 代理漏配 /watch（阻断性）
- 现象：开发服务器下 /watch/search 被 SPA fallback 吞成 index.html，搜索永久"搜索中…"。
- 修复：`frontend/vite.config.ts` 将 `/watch` 以 `apiProxyWithHtmlFallback` 加入代理（JSON 调用转后端、text/html 导航回退 SPA，与 /correlation、/options 同模式）；新增 viteProxy 契约测试。

### 4.2 公司资料刷新在真实环境必现失败（阻断性）
- 现象：akshare `stock_individual_info_em` 用裸 requests（无浏览器 UA）打 push2.eastmoney.com，被远端直接断连（RemoteDisconnected）；单测因注入 fake fetcher 而完全漏网。
- 修复：`market.py` 默认 profile fetcher 改走项目自带 `backtest.loaders.eastmoney_client.get_json`（带 UA/节流，与行情同一 host）直连 `stock/get`，字段 f58/f127/f189/f84 映射到既有中文行契约；新增 2 个默认 fetcher 端到端单测（真实 payload 形状 + 空 data 502），消除该盲区。
- 真实复验：上市日期/总股本/行业均正确落库。

### 4.3 进行中分析进入 RunView 的入口可发现性差（体验）
- 现象：历史行状态徽章与右侧入口按钮文案同为"进行中/Analysis running…"，走查时被误认为状态标签而点击行标题（展开出"暂无数据"）。
- 修复：入口改为描边按钮文案"查看运行 / View run"（9 语言新增 `watch.an.viewRun`），按钮右对齐；组件测试同步更新。

### 4.4 独立评审 FAIL → Task 16 修复（2 阻塞 + 5 重要 + 10 建议）

首轮 fresh-context 独立评审结论 FAIL，问题已物化进 tasks.md Task 16，修复全部完成：

| 编号 | 级别 | 问题 | 修复与证据 |
| --- | --- | --- | --- |
| B1 | 阻塞 | `store.update_meta` 刷新行情会覆盖清单内**其他行**（循环缺 symbol 守卫） | store.py 循环加 `if entry.symbol != symbol: continue`；回归测试 `test_update_meta_only_touches_the_matching_entry` |
| B2 | 阻塞 | 历史仅存 280 字 excerpt，AC-11"完整结论"未满足；已完成行进 RunView 无入口 | 后端 list_analyses DTO 增 `final_report` 全文；前端展开区渲染完整 Markdown（全文优先、excerpt 兜底）；所有状态行均有入口（进行中"查看运行"、已完成"查看报告"→只读 RunView）；测试断言全文且 excerpt 不出现 |
| I1 | 重要 | 搜索候选行业恒空（AC-2 自评失实） | search 路由用 `fetch_quote_snapshots` 一次批量补行业，失败仅 warning 降级；测试断言 `industry == "白酒"` |
| I2 | 重要 | "缠论"徽章硬编码中文 | 新增 i18n 键 `watch.an.chanlunBadge`（9 语言），测试按 en 断言 "Chanlun" |
| I3 | 重要 | 详情页非 404 错误（401/502）渲染空白壳无重试 | 增 `loadError` 态：原因提示 + 刷新按钮真正重拉（`watch-detail-load-error`）；测试覆盖 502→重试恢复，404 引导仍保留 |
| I4 | 重要 | 取关后三历史端点仍强制关注态（与 AC-3 字面冲突） | objective/analyses/chanlun GET 去除 `_entry_or_404`，保留 symbol 规范化；profile/objective-fetch 仍要求关注；`test_not_watched_gating` + `test_history_survives_unfollow` 覆盖 |
| I5 | 重要 | 发起补充抓取后无"进行中"提示；切回客观 Tab 不重拉 | 发起后显示琥珀色 `watch.obj.fetchRunning` 状态条（含 run id）；进入客观/基本面 Tab 每次自动重拉归档；测试断言每次进入都重新 GET |
| N1 | 建议 | 9 语言 5 个死键 | 删除 `watch.an.financialTitle/purpose/running`、`watch.ch.inProgress`、`watch.rec.payload`（删除前 grep 确认零 t() 引用；动态 `tabs.*`/`status.*` 保留），9 语言 parity 脚本校验通过 |
| N2 | 建议 | GET /watch/list 逐行读改写 N 次 | 新增 `apply_quote_snapshots` 单次读改写合并；`test_apply_quote_snapshots_single_write` 断言只写 1 次 |
| N3 | 建议 | instrument source 误标 akshare | 改 `eastmoney`，测试同步 |
| N4 | 建议 | symbol 后缀过宽，900xxx 沪 B / 200xxx 深 B 可混入 | `_suffix_for_code` 收紧为 6/0/3/4/8 头 + 920 段，拒绝 900/200；测试加 920819.BJ/200002/900901 |
| N6 | 建议 | 报告内 symbol 匹配无子串边界（1600519.SH5 误匹配） | `_SYMBOL_RE` 加前后环视，统一大写比较；`test_symbol_matching_uses_word_boundaries` |
| N7 | 建议 | 基本面 Tab 露出补充抓取输入区 | ObjectivePanel 基本面变体只渲染财务分区（抓取卡/归档区仅客观 Tab）；测试断言控件缺席、"No data"仅 1 处 |
| N8 | 建议 | 取消关注失败无反馈且对话框关闭 | catch 后对话框保留并显示 `remove-error` 警告，可重试；测试覆盖失败→重试成功 |
| N10 | 建议 | JSON 清单损坏时无日志静默 | store.py 加 logger，坏行/坏 JSON `logger.warning` |

### 4.5 真实缠论 run 暴露并修复的解析器缺口（AC-12）

真实 run（§AC-12）首跑落了 `structured=false`：parser 只接受阿拉伯数字标题，而模型实际产出为
`## 一、结构解读（分级别）` … `## 七、缠论评分与结论` 的中文数字标题，且第 2 节标题为"活跃中枢"而非关键词"支点"，
第 1 节内部还有 `### 1./### 2./### 3.` 的级别子标题（不得误消费为顶层节）。
修复：`_HEADING_RE` 兼容中文数字一..七与 ）．等分隔符；第 2 节关键词加"中枢/zhongshu"；顺序匹配天然跳过内部子标题。
新增真实报告形状回归测试 `test_real_world_cn_numeral_headings_with_inner_subsections`（score −1、confidence 0.55、7 维归属正确）。
删除旧 structured=false 行并用修复后代码重新懒归档：structured=true、7 维齐全；浏览器技术面 Tab 复验分数/置信度/维度全文均可见。

## 5. 已知限制 / 非目标（与 spec Non-Goals 一致）

- **N5（建议，不修）**：历史时间戳直接渲染 ISO 字符串（`created_at` 带时区偏移），未做浏览器本地化；数据正确，仅显示格式。
- **N9（建议，不修）**：同 symbol+role 并发 409 依赖"进行中记录"检查（check-then-insert），多 worker 极端并发下非数据库原子约束；当前单进程 serve 串行事件循环下与 spec 的 409 语义一致。
- N7 附带项：objective 归档 `request_note` 存的是注入角色模板后的完整问题文本（analysis.py:427），保留现状以便回溯实际 prompt，不改。
- 走查曾用临时 runtime home（/tmp/m16-home）；真实复验使用用户默认 `~/.vibe-trading`（茅台已在其默认清单，DuckDB 结构化缠论行已落库）。
- AI 批量对比按 spec 仅占位，无任何请求。
- 仅 A 股；清单个人私有，不做共享/同步。
- AC-17 文案说明：spec 表述为"watchlist 不新增反向依赖"，落地时在 `harness/config/layer-map.json` **注册了新 L2 包**（scripts/lint-deps 计数 33），该注册是新增正向分层声明而非反向边；watchlist 仍不 import swarm(L3)/api(L4)（catalog 数据注入、runtime L4 内 lazy import），lint-deps 0 error。

## 6. 独立评审结论

- 首轮独立评审（fresh-context，只读）：**FAIL**（2 阻塞 B1/B2 + 5 重要 I1-I5 + 10 建议 N1-N10）。
- Task 16 修复：阻塞/重要项全部修复并有针对性自动化测试；建议项除 N5/N9（见 §5，经评估接受为已知限制）外全部修复。
- 修复后回归：见 §2 门禁复跑结果；真实数据复验见 §4.5 与 AC-11/AC-12。
- **第二轮 fresh-context 独立复审结论：PASS**（2026-10-01 晚；复跑后端 7 文件 89 passed、前端目标范围 67 passed、tsc/ruff/lint-deps 0 error、9 语言 96 键 parity）。
- 复审提出的 6 条均为建议级。其中第 1、2 条在收到结论后立即收口：
  1. 已完成行"查看报告"现向 RunView 传 `readOnly`（快照模式，不建 SSE、无取消控件），进行中行/新发起 run 仍为 live 模式；AnalysisTab 测试断言 READONLY/LIVE。
  2. 补充抓取琥珀色"进行中"条在重拉发现该 run 已归档（fetches 含其 run_id）后自动清除；新增 I5 归档清除测试。
  收口后全量前端 794 passed、tsc 0。
- 第 3-6 条（置信度正则理论误取、鉴权测试防回归强度、B1 routes 层用例措辞、角色下架后历史可见性）登记为后续 backlog，不影响本任务关闭；N5/N9 维持已知限制（复审认可）。
