# 黄金政策周期监测模块 — 实现计划

## Repository Research

### 架构现状

| 层面 | 现状 | 新模块如何接入 |
|------|------|----------------|
| **前端路由** | `router.tsx` 用 `lazy` + `createBrowserRouter` 注册页面 | 新增 `GoldMonitor` page + `/gold` 路由 |
| **侧边栏** | `Layout.tsx` 中 `NAV` 数组集中定义菜单项（icon + to + label） | 数组中新增黄金菜单项，位于模拟持仓下方 |
| **后端 API 注册** | `api_server.py` 中通过 `register_*_routes(app)` 函数按模块注册 | 新增 `register_gold_routes(app)` 并在 api_server 中 import 调用 |
| **数据存储** | DuckDB，统一路径 `get_market_db_path()`，各模块用各自前缀表名 | 复用同一 DuckDB，表名前缀 `gold_` |
| **定时任务** | `paper/scheduler.py` 用 `asyncio.create_task` + FastAPI lifespan 事件启停 | 在 gold 模块中新建 scheduler，同样通过 lifespan 注册 |
| **LLM 调用** | `providers/llm.py` + `tools/fred_macro_tool.py` 有调用模式 | 新建 gold_service 内部调用 LLM 获取宏观数据（FRED API 兜底） |
| **前端 API 类型** | `lib/api.ts` 集中定义 interface + `api` 对象方法 | 在 api.ts 尾部追加 GoldMonitor 相关 interface 和方法 |

### 已分析的参考模块

- **paper（模拟持仓）**：`agent/src/paper/` 目录下 `db.py` + `service.py` + `scheduler.py` 的三层拆分，前端 `pages/Paper.tsx` 的 tabs + 卡片 + 表格布局
- **macro（宏观分析）**：`agent/src/api/macro_routes.py` 用 pydantic BaseModel 定义请求体，依赖注入 `require_auth` 装饰路由
- **watchlist（观察列表）**：`agent/src/watchlist/db.py` 的 DuckDB 短连接模式

### BDD 关键约束（来自 `/home/ai/Vibe-Trading/docs/BDD_黄金政策周期监测.md`）

- 7 个指标：金价(月均)、联邦基金利率、10Y名义利率、10Y BEI、10Y TIPS实际利率(=名义−BEI)、金价环比涨跌、政策利率月度变动、实际利率月度变动
- 历史数据（1996-10 至 2026-09）从用户 Excel 一次性导入
- 新政策周期自动判定（连续2月利率变动 > 0.05 pct 点切换），但进入"待审核"状态，用户确认后生效
- 手动刷新：LLM 调用预设 prompt → 一致性校验 → 差异弹窗 → 用户确认入库
- 每月1号自动刷新上月数据（失败时用户下次打开页面主动提示）
- 2003年前 TIPS/BEI 数据缺失，标记 N/A + 注释

---

## Files and Modules

### 后端：新建 `agent/src/gold_monitor/` 模块

| 文件 | 职责 |
|------|------|
| `agent/src/gold_monitor/__init__.py` | 模块入口，导出 DDL 和公共常量 |
| `agent/src/gold_monitor/db.py` | DuckDB 建表（`gold_monthly`、`gold_policy_cycle`）、CRUD、Excel 导入逻辑 |
| `agent/src/gold_monitor/service.py` | 业务逻辑层：当前状态查询、政策周期自动判定、一致性校验、LLM 调用获取新数据 |
| `agent/src/gold_monitor/scheduler.py` | 每月1号定时刷新任务（asyncio 循环，paper/scheduler 同模式） |
| `agent/src/gold_monitor/prompts.py` | LLM 调用用的系统/用户提示词模板 |
| `agent/src/gold_monitor/exceptions.py` | 模块自定义异常 |

### 后端：新建 API 路由

| 文件 | 职责 |
|------|------|
| `agent/src/api/gold_routes.py` | `/api/gold/*` REST 端点注册 |

### 后端：修改现有文件

| 文件 | 修改 |
|------|------|
| `agent/api_server.py` | 在路由注册区新增 `from src.api.gold_routes import register_gold_routes; register_gold_routes(app)`；在 lifespan 启动/停止时启动/停止 gold scheduler |
| `agent/tests/` | 新增 `test_gold_monitor.py` 覆盖 DB schema、周期判定、一致性校验 |

### 前端：新建页面组件

| 文件 | 职责 |
|------|------|
| `frontend/src/pages/GoldMonitor.tsx` | 黄金主页面：tab 切换 + 当前状态 + 历史周期 |
| `frontend/src/components/gold/StatusCards.tsx` | 7 张指标卡片（数值 + 迷你折线图） |
| `frontend/src/components/gold/CycleList.tsx` | 历史政策周期可展开列表 |
| `frontend/src/components/gold/MonthlyTable.tsx` | 周期展开后的月度明细表格 |
| `frontend/src/components/gold/ReviewDialog.tsx` | 新周期审核弹窗 + 数据差异确认弹窗 |

### 前端：修改现有文件

| 文件 | 修改 |
|------|------|
| `frontend/src/router.tsx` | 新增 lazy import + `/gold` 路由 |
| `frontend/src/components/layout/Layout.tsx` | NAV 数组新增黄金菜单项（chart-candlestick icon） |
| `frontend/src/lib/api.ts` | 追加 GoldMonitor 相关 interface 定义 + api 对象方法 |
| `frontend/src/i18n/locales/zh-CN.json` | 追加 gold 相关中文翻译（layout.gold + gold.*） |

---

## Database Schema

```sql
-- 月度指标表（主键月份）
CREATE TABLE IF NOT EXISTS gold_monthly (
    month           VARCHAR(7) PRIMARY KEY,          -- YYYY-MM
    gold_price      DOUBLE,                          -- 美元/盎司，月均
    ffr             DOUBLE,                          -- 联邦基金有效利率 %
    yield_nominal   DOUBLE,                          -- 10年期美债名义利率 %
    bei             DOUBLE,                          -- 10年期盈亏平衡通胀率 %（可 NULL）
    tips_real       DOUBLE,                          -- 10年期TIPS实际利率 %（= yield_nominal - bei；可 NULL）
    gold_change_pct DOUBLE,                          -- 金价环比涨跌 %（可 NULL，首月 NULL）
    ffr_change      DOUBLE,                          -- 政策利率月度变动 pct 点（可 NULL）
    real_change     DOUBLE,                          -- 实际利率月度变动 pct 点（可 NULL）
    updated_at      TIMESTAMP NOT NULL,
    source          VARCHAR(32) NOT NULL DEFAULT 'excel'  -- excel / llm / manual
);

-- 政策周期表
CREATE TABLE IF NOT EXISTS gold_policy_cycle (
    cycle_id        INTEGER PRIMARY KEY,
    cycle_name      VARCHAR(128) NOT NULL,           -- 如 "2024-09~至今 新一轮降息周期"
    start_month     VARCHAR(7) NOT NULL,
    end_month       VARCHAR(7),                      -- NULL 表示进行中
    cycle_type      VARCHAR(16) NOT NULL,            -- hiking / cutting / plateau
    source          VARCHAR(16) NOT NULL,            -- excel / auto
    status          VARCHAR(16) NOT NULL,             -- active / pending_review
    gold_start      DOUBLE,                          -- 期初金价
    gold_end        DOUBLE,                          -- 期末金价（进行中时 = 最新月）
    gold_change_pct DOUBLE,                          -- 该周期金价涨跌幅
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL
);

-- 刷新日志表（可追溯性）
CREATE TABLE IF NOT EXISTS gold_refresh_log (
    log_id          INTEGER PRIMARY KEY,
    refreshed_month VARCHAR(7) NOT NULL,
    action          VARCHAR(16) NOT NULL,             -- insert / update / rejected / failed
    diff_summary    VARCHAR(512),                     -- 差异摘要
    success         BOOLEAN NOT NULL,
    error_msg       VARCHAR(512),
    source          VARCHAR(16) NOT NULL,             -- llm / scheduler / manual
    refreshed_at    TIMESTAMP NOT NULL
);
```

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/gold/current` | 获取当前状态：最新月份全部指标 + 所属政策周期 + 近12月历史序列 |
| GET | `/api/gold/monthly?limit=N` | 分页获取历史月度数据（默认全部 or 按 limit） |
| GET | `/api/gold/cycles` | 获取全部政策周期列表（含 summary：起止月、金价变动等） |
| GET | `/api/gold/cycles/{cycle_id}/months` | 获取某周期内的全部月度明细 |
| POST | `/api/gold/refresh` | 触发 LLM 刷新：返回差异对比 JSON，含 pending_diff 标记 |
| POST | `/api/gold/confirm` | 用户确认差异覆盖（传入 month + 接受哪些字段） |
| POST | `/api/gold/cycle/{cycle_id}/approve` | 用户审核确认新周期 |
| POST | `/api/gold/import-excel` | 首次部署时导入 Excel 历史数据（手动触发一次） |
| GET | `/api/gold/refresh-needed` | 检查是否有"该自动刷新但未刷新"的上月（定时任务失败检测） |

---

## Implementation Steps

### Step 1 — 后端数据库层 + Excel 导入
- 创建 `agent/src/gold_monitor/__init__.py`, `db.py`, `exceptions.py`
- 写 DDL 建表函数，使用 `duckdb.connect(get_market_db_path())` 短连接
- 写 Excel 一次性导入函数：读取用户 Excel 的"月度数据" sheet 写入 `gold_monthly`，"政策周期对比" sheet 写入 `gold_policy_cycle`（注意跳过标题行，取有效数据起始行）
- 自动计算 `gold_change_pct`, `ffr_change`, `tips_real`, `real_change`

### Step 2 — 后端服务层（核心业务逻辑）
- 创建 `service.py`：
  - `get_current_status()` — 查最新月全部指标 + 所属周期 + 近12月序列
  - `detect_new_cycle()` — 按规则 R4 自动判定新周期（需要知道当前最新月 + 历史最后周期）
  - `refresh_via_llm()` — 调用 LLM 获取上月完整数据，返回标准化 dict
  - `validate_diff()` — 一致性校验（规则 R5）
  - `import_history_from_excel()` — 封装 db 层导入
- 创建 `prompts.py`：LLM 调用模板（要求输出 JSON 格式，含 7 个指标 + BEI）

### Step 3 — 后端 API 路由 + 注册
- 创建 `agent/src/api/gold_routes.py`，9 个端点按上表定义
- 在 `agent/api_server.py` 中 import 并注册；scheduler 在 lifespan 启动
- 参考 `paper_routes.py` 用 `require_auth` 保护所有端点

### Step 4 — 后端定时任务
- 创建 `scheduler.py`，每月1号触发 `service.refresh_via_llm()`
- 若当天已刷新过（检查 gold_refresh_log），跳过避免重复
- 异常不中断主进程，失败写入 gold_refresh_log 供前端检测

### Step 5 — 前端页面骨架
- 在 `router.tsx` 加 `/gold` 路由，`Layout.tsx` NAV 数组加黄金菜单项
- 创建 `GoldMonitor.tsx` 主页面：tab 切换（当前状态 / 历史）+ 初始 loading + api 调用
- 在 `lib/api.ts` 追加 interface 和 api 对象方法

### Step 6 — 前端当前状态 Tab
- 实现 `StatusCards.tsx`：7 张卡片，每张含 label + value + 涨跌色 + sparkline
- Sparkline 用 echarts mini（项目已有 echarts 依赖，见 `lib/echarts.ts`）
- 顶部政策周期标签区 + 手动刷新区 + 失败提示条

### Step 7 — 前端历史 Tab + 审核弹窗
- 实现 `CycleList.tsx`：政策周期列表（箭头展开），点击展开调用 `/api/gold/cycles/{id}/months`
- 实现 `MonthlyTable.tsx`：可水平滚动表格，底部 N/A 注释
- 实现 `ReviewDialog.tsx`：审核新周期 + 数据差异确认（可复用项目已有 ConfirmDialog 模式）
- 周期审核通过后刷新 cycles 列表

### Step 8 — 数据初始化 + 端到端验证
- 创建一次性脚本或调用 `/api/gold/import-excel` 导入用户提供的 Excel
- 手动测试：当前状态展示、历史展开、手动刷新（模拟 LLM 成功和失败场景）
- 手动测试：模拟刷新差异 → 弹窗 → 用户确认覆盖
- 手动测试：模拟新周期自动识别 → 审核弹窗 → 确认生效

### Step 9 — i18n + 清理
- 追加 zh-CN 和 en 翻译键值
- 清理临时脚本，确保无开发残留代码提交

---

## Dependencies and Considerations

- **DuckDB 写入性能**：`gold_monthly` 仅 360+ 行，`gold_policy_cycle` 仅 20+ 行，完全无需分区或索引
- **Excel 导入一次性**：考虑直接用 `python3 -c "import pandas; ..."` 在部署时手动跑 import，而不是做上传 endpoint（降低复杂度）
- **LLM 调用超时兜底**：`refresh_via_llm` 超过 30s 视为失败，抛自定义异常让前端展示失败提示
- **BEI 缺失时 tips_real 计算**：2003 年前月份 bei 为 NULL，tips_real 也为 NULL，前端展示 N/A
- **周期自动判定的数据依赖**：至少需要近 3 个月 FFR 数据才能判定，启动时若无足够历史则不自动判定
- **前端 echarts sparkline**：项目已有 echarts 依赖，MiniEquityChart.tsx 可参考其迷你图实现方式
- **FastAPI lifespan 事件**：paper 模块在 api_server.py 的 lifespan 中启停 scheduler，gold 模块沿用同模式

---

## Validation

- **Python 单元测试**：`make test-fast` 跑新增测试，覆盖 db schema 初始化、周期判定规则 R4 的 3 种场景、一致性校验 R5
- **后端 API 连通**：`curl http://localhost:8899/api/gold/current` 确认返回 200 + 正确 schema
- **前端构建**：`make fe-build` 无 TypeScript 错误 + 无 lint error
- **端到端手动验证**：启动 server，前端 → 侧边栏 → 黄金 → 当前状态 tab 正常展示 7 张卡片 + 政策周期标签；历史 tab 可展开；手动刷新按钮可用

---

## Risks

- **LLM 调用不稳定/数据幻觉**：降级处理 —— 超过 1 次失败则回退 FRED API（项目已有 `fred_macro_tool.py`），失败写 log 提示用户手动刷新
- **月度自动刷新在 app 关闭期间不执行**：每月1号在 server 运行时触发；用户下次打开页面时 `GET /api/gold/refresh-needed` 检测到上月未刷新则主动提示
- **DuckDB 锁冲突**：短连接模式（connect → 操作 → close）已在 paper 和 watchlist 模块验证过，无风险
- **i18n 翻译覆盖不全**：先做 zh-CN，en 用同样的 key 占位即可（项目已有 fallback 机制）
- **Excel 列名变动**：用 pandas 读 Excel 时显式指定列名映射（中文列名 → 英文字段），不依赖列顺序
