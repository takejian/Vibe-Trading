# 超跌反弹菜单实施计划

## Repository Research

### 技术栈
- **前端**: React 19 + Vite + TypeScript + Tailwind CSS + lucide-react 图标库 + react-router
- **后端**: Python FastAPI + DuckDB（共享 market warehouse）
- **模式参考**: `gold_monitor` 模块（db.py + service.py + api routes，通过 `register_*_routes(app)` 挂载到 api_server）

### 关键文件位置
| 位置 | 文件 | 说明 |
|---|---|---|
| 前端菜单 | `frontend/src/components/layout/Layout.tsx` L22-L40 | `NAV` 数组定义左侧菜单，包含 `{to: "/runtime", icon: Activity, label: t('layout.runtime')}` |
| 前端路由 | `frontend/src/router.tsx` L84-L116 | `createBrowserRouter` 注册所有路由 |
| 前端i18n | `frontend/src/i18n/locales/zh-CN.json` | `layout.runtime` = "交易监控" |
| 后端路由注册 | `agent/api_server.py` L154-L288 | `register_*_routes(app)` 挂载 |
| 后端API模式 | `agent/src/api/gold_routes.py` | FastAPI routes + require_auth |
| 后端DB模式 | `agent/src/gold_monitor/db.py` | DuckDB short-lived connection + DDL + CRUD |
| 后端Service模式 | `agent/src/gold_monitor/service.py` | 业务逻辑层 |
| 市场DB路径 | `agent/src/config/paths.py` | `get_market_db_path()` 返回共享 DuckDB 路径 |
| API 安全 | `agent/src/api/security.py` | `require_auth` 依赖 |

### 目标网页数据结构（已抓取）
目标 `https://astock-monitor-04758.app.workbuddy.host/?sharecode=N2WCQXUGR7` 页面包含两大板块：
1. **两融维持担保比例**：最新值、近6年分位、近十年分位、较区间高点落差、区间高/低值、样本数
2. **国家队ETF买入监测**：17只宽基ETF按日期的成交额放大法明细表格（含基准期、累计行、最新交易日高亮）

---

## Files and Modules

### 需要修改的文件

| 文件 | 变更说明 |
|---|---|
| `frontend/src/components/layout/Layout.tsx` | NAV 数组：移除 `/runtime`（交易监控），新增 `/super-rebound` 超跌反弹菜单 |
| `frontend/src/router.tsx` | 新增路由 lazy load + `/super-rebound` 和 `/super-rebound/indicator` |
| `frontend/src/i18n/locales/zh-CN.json` | 新增 `layout.superRebound`、`superRebound.financeTab`、`superRebound.indicatorTab` 等文案 |
| `agent/api_server.py` | 新增 `register_super_rebound_routes(app)` 调用 |

### 需要新建的文件

#### 后端（参考 gold_monitor 模式）
| 文件 | 说明 |
|---|---|
| `agent/src/super_rebound/__init__.py` | 包初始化 |
| `agent/src/super_rebound/db.py` | DuckDB DDL + CRUD（2张表：margin_ratio_history、etf_monitor_daily） |
| `agent/src/super_rebound/scraper.py` | 目标网页抓取器（requests + BeautifulSoup 解析 HTML） |
| `agent/src/super_rebound/service.py` | 业务逻辑层（数据组装、分位计算、统计聚合） |
| `agent/src/api/super_rebound_routes.py` | FastAPI 路由（`/api/super-rebound/*`） |

#### 前端页面
| 文件 | 说明 |
|---|---|
| `frontend/src/pages/SuperRebound.tsx` | 超跌反弹主页面（Tab 切换容器：资金面 / 超跌指标） |
| `frontend/src/pages/super-rebound/FinancePanel.tsx` | 资金面 Tab（复刻目标网页） |
| `frontend/src/pages/super-rebound/IndicatorPanel.tsx` | 超跌指标 Tab（骨架 + TODO 占位） |

#### 前端 lib
| 文件 | 说明 |
|---|---|
| `frontend/src/lib/superRebound.ts` | 前端 API 客户端（封装 fetch `/api/super-rebound/*`） |

---

## Implementation Steps

### Step 1: 后端 - 创建 super_rebound 数据模块

**1.1 建表 (db.py)**

在共享 DuckDB 中创建 2 张表：

```sql
-- 两融维持担保比例历史
CREATE TABLE IF NOT EXISTS rebound_margin_ratio (
    trade_date     DATE PRIMARY KEY,
    margin_ratio   DOUBLE NOT NULL,       -- 维持担保比例(%)
    range_high     DOUBLE,                 -- 区间高点(%)
    range_low      DOUBLE,                 -- 区间低点(%)
    source         VARCHAR(32) NOT NULL DEFAULT 'scraper',
    updated_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- 国家队ETF买入监测明细（按每只ETF每日）
CREATE TABLE IF NOT EXISTS rebound_etf_monitor (
    trade_date     DATE NOT NULL,
    etf_code       VARCHAR(32) NOT NULL,   -- 如 '中证A500ETF国泰'
    index_group    VARCHAR(16) NOT NULL,   -- 指数分组：A500/上证50/沪深300/中证500/中证1000/创业板/科创50
    turnover_bn    DOUBLE NOT NULL DEFAULT 0,  -- 当日净买入(亿元)
    baseline_bn    DOUBLE,                 -- 基准期日均成交额(亿元)
    source         VARCHAR(32) NOT NULL DEFAULT 'scraper',
    updated_at     TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (trade_date, etf_code)
);
```

**1.2 数据抓取器 (scraper.py)**

- 用 `requests` GET 目标网页 URL
- 用 `BeautifulSoup` 解析 HTML：
  - 提取两融担保比例板块的数值（最新值、区间、样本数等）
  - 找到 ETF 监测表格（`<table>` 元素），逐行逐列解析出每只 ETF 每日成交额
  - 解析表格底部的累计行
- 计算逻辑：
  - 净买入 = max(0, 当日成交额 − 基准期日均成交额)
  - 基准期取目标网页显示的基准日期范围
- 返回结构化 dict

**1.3 Service 层 (service.py)**

- `fetch_and_store()`: 调用 scraper → 清洗 → upsert DuckDB
- `get_margin_ratio_latest()`: 最新值 + 近6年分位 + 近10年分位 + 区间统计
  - 分位计算：`(count(row where row <= latest) / total) * 100`
- `get_margin_ratio_history(start_date, end_date)`: 历史序列
- `get_etf_monitor_summary(start_date, end_date)`: ETF 监测统计（累计/最新/单日最高/最新最强/累计最多）
- `get_etf_monitor_detail(start_date, end_date)`: 完整明细表格数据（含分组小计）
- `refresh_data()`: 手动刷新入口（scrape + store + 返回统计摘要）

**1.4 API 路由 (api/super_rebound_routes.py)**

```
GET  /api/super-rebound/finance/margin-ratio     → 两融担保比例最新 + 统计
GET  /api/super-rebound/finance/etf-monitor      → ETF 监测 (query: start_date, end_date)
GET  /api/super-rebound/finance/refresh-needed   → 检查是否需要更新
POST /api/super-rebound/finance/refresh           → 手动触发刷新
TODO /api/super-rebound/indicator/score           → 超跌指标综合评分（待实现）
TODO /api/super-rebound/indicator/dimensions      → 各维度得分明细（待实现）
```

所有端点 behind `require_auth`，模式参考 gold_routes.py。

---

### Step 2: 前端 - 菜单与路由调整

**2.1 Layout.tsx 修改**

NAV 数组变更：
- 删除 `{ to: "/runtime", icon: Activity, label: t('layout.runtime') }` （注释掉，保留行可恢复）
- 新增 `{ to: "/super-rebound", icon: TrendingDown, label: t('layout.superRebound') }`
- 在 import 中新增 `TrendingDown` from lucide-react

**2.2 router.tsx 修改**

- 新增 lazy load: `SuperRebound = lazy(() => import("@/pages/SuperRebound")...)`
- 新增路由: `{ path: "/super-rebound", element: wrap(SuperRebound) }`

**2.3 zh-CN.json 修改**

新增文案：
```json
"layout": {
  "superRebound": "超跌反弹",
  ...
},
"superRebound": {
  "financeTab": "资金面",
  "indicatorTab": "超跌指标",
  "refresh": "刷新",
  "marginTitle": "A股两融全市场平均维持担保比例",
  "latest": "最新",
  "sixYearPercentile": "近6年分位",
  "tenYearPercentile": "近十年分位",
  "vsRangeHigh": "较区间高点",
  "rangeHigh": "区间高",
  "rangeLow": "区间低",
  "sampleCount": "样本",
  "etfTitle": "国家队ETF买入金额监测",
  "totalBought": "累计买入",
  "latestDay": "最新交易日",
  "singleDayHigh": "单日最高",
  "latestStrongest": "最新最强",
  "cumulativeMost": "累计最多",
  "monitorDays": "监测天数",
  "baselinePeriod": "基准期",
  "dateFilter": "日期筛选",
  "apply": "应用",
  "updatedAt": "更新时间"
}
```

---

### Step 3: 前端 - 资金面 Tab 页面

**3.1 SuperRebound.tsx（主容器）**

- Tab 切换器（资金面 / 超跌指标），使用内联 state 切换
- 默认 activeTab = 'finance'

**3.2 FinancePanel.tsx（资金面板）**

复刻目标网页布局：
```
┌───────────────────────────────────────────┐
│  [刷新按钮]  更新时间: 2026-11-05 15:11   │
├───────────────────────────────────────────┤
│ A股两融全市场平均维持担保比例               │
│ 区间 2020-11-05 ~ 2026-11-04  样本 1454个 │
│ ┌────────┬────────┬────────┬────────┐    │
│ │ 259.34%│ 18.2%  │ 21.8%  │-14.55% │    │
│ │ 最新   │近6年分位│近十年分位│较区间高│    │
│ └────────┴────────┴────────┴────────┘    │
│ ┌────────┬────────┬────────┐              │
│ │303.51% │222.00% │  1454  │              │
│ │区间高  │区间低  │ 样本   │              │
│ └────────┴────────┴────────┘              │
│ 维持担保比例 = 担保物总价值 ÷ 融资融券债务 │
│ 240% 为常用警戒参考线                      │
├───────────────────────────────────────────┤
│ 国家队ETF买入金额监测 · 成交额放大法        │
│ 累计买入 7696亿 | 最新 547亿 | 单日最高    │
│ 最新最强 中证A500 138亿 | 累计最多 沪深300 │
│ 监测天数 24 | 基准期 9/1~9/24              │
│ [日期筛选: _____ ~ _____] [应用]           │
│ ┌─────┬────┬────┬────┬────┬────┬────┐    │
│ │日期 │A500│上证│沪深│中证│中证│总买│    │
│ │     │    │ 50 │300 │500 │1000│入 │    │
│ │...  │    │    │    │    │    │    │    │
│ │11-05│... │... │... │... │... │... │高亮│
│ │累计 │    │    │    │    │    │    │    │
│ └─────┴────┴────┴────┴────┴────┴────┘    │
│ 单位：亿元 | 净买入 = max(0, 当日 − 基准)  │
└───────────────────────────────────────────┘
```

技术要点：
- 指标卡：grid 布局 + Tailwind card 样式 + lucide 图标
- ETF 表格：`<table>` 或 grid，最新交易日整行高亮（`bg-primary/10`），累计行独立样式
- 日期筛选：原生 `<input type="date">` + 应用按钮
- 刷新：调用 `POST /api/super-rebound/finance/refresh` + 重新 GET 数据
- 加载态：skeleton 占位 + error 边界
- 无数据态：友好提示 + 引导刷新

**3.3 IndicatorPanel.tsx（超跌指标面板 - 骨架版）**

- 指数下拉框（沪深300/上证A500/上证50/中证500/中证1000/创业板/科创50）
- 综合得分 + 信号灯（🔴🟡🟢）占位展示
- 五维度明细表格骨架
- 底部 "TODO" 说明：超跌指标计算后端接口待实现

---

### Step 4: 后端接口预留 TODO

超跌指标 tab 的后端接口当前标记 TODO，不阻塞资金面 tab 交付。后续迭代需要：
- 各维度原始数据获取（ERP、估值分位、RSI 等需调用不同数据源）
- 维度得分计算逻辑
- 加权综合评分
- 数据缺失归一化处理

---

## Dependencies and Considerations

### 依赖
- 后端需要 `requests`（HTTP 请求）和 `beautifulsoup4`（HTML 解析）来抓取目标网页。需确认 `pyproject.toml` 是否已包含；如未包含需添加。
- 后端 `src/config/paths.py` 的 `get_market_db_path()` 返回共享 DuckDB 路径。

### 注意事项
1. **目标网页可访问性**：目标 `workbuddy.host` 可能有反爬限制或需要 sharecode。如果抓取失败，需要降级方案（人工导入 Excel 或 mock 数据）
2. **DuckDB 是单文件数据库**，多进程写入有锁。参考 gold_monitor 的 short-lived connection 模式
3. **交易监控路由保留**：隐藏菜单但保留 `/runtime` 路由和页面组件代码，可通过配置恢复
4. **分位计算的正确性**：`(count(x <= v) / N) * 100` 注意边界情况和 tie handling
5. **ETF 名称映射**：目标网页中 17 只 ETF 名称需与数据库存储名称保持一致

---

## Validation

- [ ] 后端 `GET /api/super-rebound/finance/margin-ratio` 返回正确的最新值和分位
- [ ] 后端 `GET /api/super-rebound/finance/etf-monitor` 返回带分组小计和累计行的明细
- [ ] 后端 `POST /api/super-rebound/finance/refresh` 能正确抓取目标网页并写入 DuckDB
- [ ] 后端 `python -m pytest agent/tests/` 无回归
- [ ] 前端 `npm run build` 编译通过
- [ ] 左侧菜单无"交易监控"，有"超跌反弹"
- [ ] 资金面 tab 页面视觉还原度 ≥ 目标网页 90%
- [ ] 日期筛选功能正常工作
- [ ] 刷新按钮可触发数据更新

---

## Risks

| 风险 | 处理 |
|---|---|
| 目标网页反爬或结构变更导致 scraper 失败 | 降级：提供 mock 数据 + 手动 Excel 导入接口（参考 gold_monitor 的 `import_excel` 模式） |
| DuckDB 并发写入锁冲突 | 所有连接使用 short-lived context manager，与 gold_monitor 一致 |
| ETF 名称中英文/格式不统一 | 在 scraper 层做 normalize 映射，数据库存储标准化名称 |
| 后端接口延迟或超时 | 前端加载态 + 错误边界 + 手动重试 |
| "交易监控" 隐藏后用户无法访问 | 保留路由和组件代码，只需恢复 NAV 数组即可 |
| 超跌指标 tab 数据缺失 | 骨架版展示 + 清晰 TODO 说明，不阻塞资金面 tab 交付 |
