# PRD：模拟持仓（Paper Portfolio）

| 项 | 内容 |
| --- | --- |
| 版本 | v1.0（草案，待评审） |
| 日期 | 2026-10-14 |
| 范围 | 前端 Web UI + FastAPI 后端 + 本地 DuckDB，仅 A 股 |
| 关联模块 | 关注列表（watchlist）、缠论分析（chanlun_analysis）、行情（东财）、真实持仓（portfolio，只读不动） |

---

## 1. Executive Summary

### 1.1 Problem Statement

用户在关注列表中基于缠论分析做出买入判断后，系统内没有任何地方跟踪“如果当时真的买了”的后续表现：真实持仓页（`/portfolio`）对接券商账户、只读且强耦合 live 交易，无法承载观察性、验证性的虚拟建仓需求。买入决策的事后验证（缠论打分是否有效、买点是否准确）完全依赖人工记忆。

### 1.2 Proposed Solution

在菜单栏新增独立的**模拟持仓**（Paper Portfolio，路由 `/paper`），与真实券商持仓完全隔离：关注列表每行增加“买入”按钮，买入时以服务端实时价成交，自动归档买入日期、价格、费用及当时的**缠论打分快照**；持仓股票在 A 股交易时段内每 2 小时刷新现价并重算买入后收益率；支持 T+1 卖出、费用模拟，并提供账户总览、个股收益、已平仓交易历史、净值曲线四类统计。原有“持仓”菜单入口隐藏，但其前端路由与全部后端代码保持不变。

### 1.3 Success Criteria

1. 关注列表点击“买入”成交后，持仓页在 **2 秒内**可见该持仓，成交价与服务端取价一致（前端不可指定价格）。
2. 交易时段（交易日 9:30–11:30、13:00–15:00）内，持仓现价按每 2 小时锚点刷新，定时任务触发到价格落库延迟 **≤ 90 秒**，各锚点刷新成功率 **≥ 99%**（东财源故障有重试与陈旧标记）。
3. 费用扣减、现金、成本价、已实现/未实现盈亏、收益率全部通过**固定样本单对账测试，误差为 0**（pytest 单测，含分批买入、部分卖出、T+1 拦截用例）。
4. 账户总览恒等式在任何操作后成立：`总资产 = 现金 + Σ(持仓数量 × 现价)`（误差 < 0.01 元）。
5. 主流程（关注 → 买入 → 持仓跟踪 → T+1 卖出 → 查看统计/净值）端到端可用，无需命令行或手工改库。

---

## 2. User Experience & Functionality

### 2.1 User Personas

- **主要用户：个人量化研究者（本地单用户）**。使用缠论分析筛选关注标的，需要低成本验证买点质量与打分有效性，不承担真实资金风险。

### 2.2 菜单与入口变更

- **隐藏**：主导航中的“持仓”项（`frontend/src/components/layout/Layout.tsx:22-37` 中 `/portfolio` 一项从 NAV 数组移除/注释）。
  - `/portfolio` 前端路由保留（直接输入 URL 仍可访问）；`/api/portfolio` 及 `agent/src/api/portfolio_routes.py`、`agent/src/portfolio/store.py` **零改动**。
- **新增**：主导航项“模拟持仓”，路由 `/paper`，图标建议与真实持仓区分（如 ChartLine / PiggyBank）。

### 2.3 User Stories 与验收标准

#### Story 1：从关注列表买入

> 作为用户，我希望在关注列表中直接点“买入”、输入股数后模拟成交，这样我可以把缠论买点判断立即沉淀为一笔可跟踪的模拟持仓。

**验收标准：**

- 关注列表（`/watch`）每一行增加“买入”按钮，点击弹出买入对话框。
- 对话框展示：股票名称/代码、**服务端返回的价格**及报价时间（交易时段为实时最新价；非交易时段为上一交易日收盘价并标注“收盘价”及所属交易日）、当日涨跌、可用虚拟资金、买入股数输入框（默认 100 股）。
- 对话框展示该股票**最新一次缠论分析打分**：总分 `score`（-5 ~ 5）、置信度 `confidence`、分析日期，取自 `chanlun_analysis` 表最新一条；从未分析过则展示“暂无缠论打分”，**不阻断买入**（打分字段存空）。
- 股数校验：A 股 100 股整数倍、≥ 100；实时试算成交金额、佣金、印花税（买入为 0）、过户费与预计占用资金。
- 确认买入后由**服务端重新取价**成交（不接受前端传入价格）；成交瞬间写入：日期时间、成交价、数量、各项费用、缠论打分快照（score / confidence / run_id / dim7 文案）。
- 现金不足、行情取价失败（实时价与收盘价均取不到）、标的已不在关注列表等情况给出明确错误文案，不生成订单。
- **非交易时段允许买入**（模拟盘）：夜间、周末、节假日一律按**上一交易日收盘价**成交；对话框、成交单明确标注“收盘价成交”及价格所属交易日。

#### Story 2：持仓跟踪与 2 小时周期收益率

> 作为用户，我希望持仓股在交易时段每 2 小时自动更新价格并看到买入后的收益率，这样我能持续观察买点的表现。

**验收标准：**

- 持仓表格列：股票名称/代码、持仓数量、成本价（含费摊薄）、现价、现价时间、市值、浮动盈亏（元）、**买入后收益率 %**、买入时缠论打分、数据状态（实时/陈旧）。
- 定时刷新锚点（A 股交易日）：以各交易时段开盘为起点，每 **2 小时**刷新一次——**11:30**（9:30 开盘 +120 分钟，即上午收盘价）、**15:00**（13:00 午后开盘 +120 分钟，即收盘定格价）；允许 ±5 分钟调度抖动。午间休市（11:30–13:00）计时暂停、不刷新，午后从 13:00 重新起算。每个交易日共 2 个快照点。
- 是否交易日以本地 DuckDB `trading_calendar`（market='a_share', is_open）为准；日历数据缺失/过旧时回退工作日判断并在日志告警（复用 `resolve_market_dates` 的三级回退思路）。
- 每次刷新批量调用现有行情接口（`watchlist.market.fetch_quote_snapshots`，一次传全部持仓代码），写入价格快照与账户净值快照。
- 页面打开时立即拉取一次；处于交易时段时前端每 2 小时轮询一次兜底，页面关闭期间的刷新由**服务端后台任务**保证（净值曲线不依赖页面常开）。
- 行情失败：重试 2 次；仍失败则保留上一价格并将该行标记为“价格陈旧（最后更新 HH:MM）”，收益率不跳变、不错误归零。
- 非交易时段页面展示最近收盘价，不轮询，标注“已收盘 · 买卖按此收盘价成交”。
- 同一股票分批买入：持仓合并展示，成本价按**移动加权平均（含买入费用）**计算；T+1 可卖数量按买入批次分别计算。

#### Story 3：T+1 卖出

> 作为用户，我可以在买入后的下一个交易日卖出持仓、系统模拟真实费用并回款，以完成一笔模拟交易闭环。

**验收标准：**

- 持仓行提供“卖出”按钮，弹窗展示服务端价格（盘中实时价 / 盘后收盘价）、可卖数量（**T+1：批次登记交易日当日不可卖，下一交易日释放**）、输入卖出数量（100 整数倍）、实时试算佣金、印花税 0.05%、过户费与预计回款。
- 非交易时段（含夜间、周末、节假日）**允许卖出**，按上一交易日收盘价成交；批次 T+1 的判断日为成交价格所属交易日——例如周一夜间按周一收盘价买入，登记 bought_on=周一，周二可卖；周六按周五收盘价买入，登记 bought_on=周五，下周一可卖。
- 卖出成交由服务端重新取价；卖出对应批次成本按 **FIFO（先进先出）** 从买入批次扣减，计算该笔已实现盈亏（含双边费用）。
- 卖出数量不得超过可卖数量；当日买入部分在“可卖数量”中明确显示为 0 并标注“今日买入，T+1 可卖”。
- 卖出回款（扣费用后）即时增加现金余额；全部卖完的持仓从持仓表移除并进入已平仓历史。
- 任何时间均可提交卖出；价格口径与错误处理与买入一致（盘中实时、盘后收盘）。

#### Story 4：账户总览

> 作为用户，我希望一眼看到模拟账户整体的盈亏状况。

**验收标准：**

- 顶部总览卡片：初始资金（**100,000 元**，账户创建时写入）、可用现金、持仓市值、总资产、累计盈亏（元）、累计收益率 %、当日盈亏（元，相对上一交易日收盘净值）。
- 收益率符号与颜色区分（红涨绿跌遵循 A 股习惯）；金额保留两位小数，收益率保留两位百分比。
- 提供“重置账户”操作（二次确认）：清空所有持仓/订单/快照，现金恢复 100,000 元。初始资金额度在配置中可调（见 4.5），UI 不暴露修改入口。

#### Story 5：已平仓交易历史与统计

> 作为用户，我希望回顾每笔卖出的结果并看到胜率等汇总指标，以评估自己的交易判断。

**验收标准：**

- 交易记录页同时列出全部**成交流水**（买入、卖出，含费用明细）和**已平仓交易视图**（每次卖出对应扣减批次形成的平仓记录：代码、买卖日期、持有天数、买入成本、卖出净收入、已实现盈亏、收益率、买入时缠论打分）。
- 汇总区：已平仓笔数、胜率（收益率 > 0 的占比）、平均已实现盈亏、平均收益率、平均持有天数、累计费用。
- 支持按股票代码过滤、按时间倒序分页。

#### Story 6：净值曲线

> 作为用户，我希望看到账户净值随时间的走势，而不只是当前数字。

**验收标准：**

- 折线图展示账户净值（总资产）与初始资金基准线（100,000），X 轴为快照时间，数据点来自每 2 小时锚点刷新时落库的净值快照（每个交易日 2 个点：11:30、15:00）；支持区间切换（全部 / 近 20 个交易日 / 近 5 个交易日）。
- 图上可切换显示累计收益率 %。
- 图表库与前端现有 K 线/权重图保持一致，不新增重型依赖。

### 2.4 Non-Goals（本期明确不做）

- **不改动**真实券商持仓的任何后端代码与路由；仅隐藏其菜单入口。
- 不接入任何真实下单/券商通道，不产生真实交易。
- 不支持美股、港股及其他市场；不支持外汇、加密、期权、两融。
- 不做自动交易、条件单、止损止盈单、盯盘提醒推送。
- 不模拟分红、送股、配股、停牌、退市与除权除息对持仓的调整（v1.1 评估）。
- 不做多账户、多用户、账户间转账；本地单用户。
- 不做 tick 级/分钟级行情，盘中仅每 2 小时快照。
- 不新增 AI 模型；缠论打分为既有分析流程的结果消费方。

---

## 3. AI System Requirements

### 3.1 既有 AI 能力的消费（无新增模型）

- 缠论分析由既有 chanlun-bi-analysis pipeline 产出并归档至 `chanlun_analysis`（`agent/src/watchlist/db.py:84-103`，写入函数 `insert_chanlun_record`）。
- 买入成交时，服务端按 `symbol` 取 `analyzed_at` 最新一条记录，将以下字段**快照**进成交单：`run_id`、`score`（-5~5）、`confidence`（0~1）、`dim7_chanlun_score`（文案）、`analyzed_at`。
  - 必须快照而非外键引用：历史分析记录理论上不可变，但快照可保证成交单自洽，且支持未来在交易记录中对照“买入时打分 vs 实际收益”。
- 复用现有接口 `GET /watch/{symbol}/chanlun`（`agent/src/api/watchlist_routes.py:496-523`）的查询逻辑读取最新打分，供买入对话框展示。

### 3.2 Evaluation Strategy

- 不涉及生成式输出质量评估。打分有效性验证属于分析侧既有闭环（`chanlun_outcome` 表）。
- v2.0 可做：以模拟持仓成交单为样本，统计不同 `score` 分组的平均买入后收益，量化缠论打分的预测力（只读分析，不改本功能）。

---

## 4. Technical Specifications

### 4.1 Architecture Overview

```
关注列表 /watch                     模拟持仓 /paper (新)
 Watchlist.tsx                       Paper.tsx（持仓/流水/统计/净值 Tab）
   │ 行内 [买入] 按钮                   │ 轮询(交易时段/1h) + 手动刷新
   ▼                                  ▼
 BuyDialog（股数/费用试算/打分展示）   lib/api.ts 新增 /api/paper/* 封装
   │                                  │
   └──────────────┬───────────────────┘
                  ▼
        api_server.py（仅注册新路由，不改旧逻辑）
                  │
        src/api/paper_routes.py（新增, /api/paper/*）
                  │
        src/paper/（新增业务包）
          ├─ service.py   买入/卖出/取价/费用/盈亏事务
          ├─ prices.py    批量行情刷新（复用 watchlist.market）
          ├─ scheduler.py 交易时段每 2 小时后台任务（lifespan 挂载）
          ├─ calendar.py  交易日/交易时段判断（复用 trading_calendar）
          └─ db.py        建表 DDL + DAO（独立连接管理）
                  │
                  ▼
        DuckDB 市场库（get_market_db_path，与 watchlist 同库不同表）
        paper_account / paper_order / paper_lot
        paper_close / paper_quote_snapshot / paper_nav_snapshot
```

**隔离原则**：新功能全部落在新包 `src/paper/` 与新路由模块；对既有代码的触碰仅限三处——导航数组、路由表、`api_server.py` 增加一行路由注册（lifespan 后台任务通过注册函数内的 `app.state` 接入，不修改 preflight 语义）。

### 4.2 数据流

1. **买入**：前端 `POST /api/paper/buy {symbol, qty}` → 服务端校验关注归属/资金（**不限制交易时段**）→ 按口径取价（交易时段实时最新价；否则上一交易日收盘价）→ 查最新缠论分析 → 计算费用 → 单事务内：扣现金、写 `paper_order`（含价格口径标记）、写 `paper_lot`（bought_on 登记为价格所属交易日）。
2. **定时刷新**：scheduler 每分钟唤醒检查（交易日 && 到达下一锚点 && 该锚点当日未执行）→ 对所有持仓 symbol 批量取价 → 写 `paper_quote_snapshot`、重算市值、写 `paper_nav_snapshot`。
3. **卖出**：校验 T+1 可卖数量（按批次 bought_on 与当前价格所属交易日判断）→ 按口径取价（盘中实时 / 盘后收盘）→ FIFO 扣减 lot、计算已实现盈亏 → 写卖单（含价格口径标记）与 `paper_close` 平仓记录、回增现金。
4. **查询**：持仓/总览/流水/统计/净值均为只读聚合查询；现价取该 symbol 最新快照。

### 4.3 数据模型（DuckDB 新表，`CREATE TABLE IF NOT EXISTS` 幂等建表）

```sql
-- 账户单行表（id 固定为 1）
CREATE TABLE paper_account (
    id               INTEGER PRIMARY KEY DEFAULT 1,
    initial_capital  DOUBLE NOT NULL,      -- 100000.00
    cash_balance     DOUBLE NOT NULL,      -- 可用现金
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP,
    CONSTRAINT singleton CHECK (id = 1)
);

-- 成交流水（买入/卖出各一行）
CREATE TABLE paper_order (
    id               VARCHAR PRIMARY KEY,  -- uuid
    side             VARCHAR NOT NULL,     -- 'buy' | 'sell'
    symbol           VARCHAR NOT NULL,
    name             VARCHAR,
    qty              BIGINT NOT NULL,      -- 100 整数倍
    price            DOUBLE NOT NULL,      -- 服务端成交价
    amount           DOUBLE NOT NULL,      -- qty * price
    commission       DOUBLE NOT NULL,      -- 佣金
    stamp_tax        DOUBLE NOT NULL,      -- 印花税(卖出)
    transfer_fee     DOUBLE NOT NULL,      -- 过户费
    price_session    VARCHAR NOT NULL,     -- 'live'(盘中实时) | 'close'(收盘价)
    price_trade_date DATE NOT NULL,         -- 成交价格所属交易日
    -- 买入时缠论打分快照（卖出单继承其扣减批次的买入打分，便于统计）
    chanlun_run_id      VARCHAR,
    chanlun_score       INTEGER,           -- -5 ~ 5，可空
    chanlun_confidence  DOUBLE,
    chanlun_score_text  VARCHAR,           -- dim7 文案
    chanlun_analyzed_at TIMESTAMP,
    traded_at        TIMESTAMP NOT NULL
);

-- 买入批次（T+1 与 FIFO 成本扣减的最小单位）
CREATE TABLE paper_lot (
    id               VARCHAR PRIMARY KEY,
    buy_order_id     VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    qty_remaining    BIGINT NOT NULL,      -- 被卖出后递减，到 0 即平
    price            DOUBLE NOT NULL,
    buy_fees         DOUBLE NOT NULL,      -- 该批次分摊买入费用
    bought_on        DATE NOT NULL,        -- 买入交易日
    created_at       TIMESTAMP NOT NULL
);

-- 平仓记录（每次卖出扣减批次生成一行；部分卖出=多行）
CREATE TABLE paper_close (
    id               VARCHAR PRIMARY KEY,
    sell_order_id    VARCHAR NOT NULL,
    buy_order_id     VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    qty              BIGINT NOT NULL,
    buy_cost         DOUBLE NOT NULL,      -- 扣减批次的买入成本(含费)
    sell_proceeds    DOUBLE NOT NULL,      -- 卖出净收入(扣费)
    realized_pnl     DOUBLE NOT NULL,
    return_pct       DOUBLE NOT NULL,
    holding_days     INTEGER NOT NULL,
    chanlun_score    INTEGER,
    created_at       TIMESTAMP NOT NULL
);

-- 盘中价格快照
CREATE TABLE paper_quote_snapshot (
    symbol     VARCHAR NOT NULL,
    price      DOUBLE NOT NULL,
    snapped_at TIMESTAMP NOT NULL,
    source     VARCHAR,
    PRIMARY KEY (symbol, snapped_at)
);

-- 账户净值快照（每 2 小时锚点一行
CREATE TABLE paper_nav_snapshot (
    snapped_at    TIMESTAMP PRIMARY KEY,
    cash          DOUBLE NOT NULL,
    market_value  DOUBLE NOT NULL,
    total_asset   DOUBLE NOT NULL,
    nav           DOUBLE NOT NULL          -- total_asset / initial_capital
);
```

- 金额在服务层以 `Decimal` 计算、四舍五入到分后落库，禁止浮点直接累加。
- 所有写操作在同一 DuckDB 连接的单事务内完成；连接沿用 `watchlist_connection()` 的短连接模式，避免后台任务与 API 请求并发写冲突。

### 4.4 费用与盈亏规则（默认参数，集中配置）

| 费项 | 默认值 | 收取方 |
| --- | --- | --- |
| 佣金 | 成交金额 × 0.025%，最低 5 元 | 买、卖双边 |
| 印花税 | 成交金额 × 0.05% | 仅卖出 |
| 过户费 | 成交金额 × 0.001% | 买、卖双边 |

- 买入占用资金 = `amount + commission + transfer_fee`
- 卖出净回款 = `amount - commission - stamp_tax - transfer_fee`
- 摊薄成本价（同标的多批买入）= `Σ(批次剩余买入成本含费) / Σ剩余数量`
- 浮动盈亏 = `qty × 现价 − Σ剩余买入成本含费`；买入后收益率 = `浮盈 / Σ剩余买入成本含费`
- 已实现盈亏 = 卖出净回款 − 对应扣减批次的买入成本（含买入费用）
- 当日盈亏 = 当前总资产 − 上一交易日最后一条净值快照的总资产

### 4.5 配置项（走统一 env schema）

在 `agent/src/config/env_schema.py` 的既有模式下新增（读取 `os.environ` 只能出现在 config 层，受 `ci_env_var_gate` 约束）：

- `VIBE_PAPER_INITIAL_CASH`（默认 100000）
- `VIBE_PAPER_COMMISSION_RATE`（0.00025）、`VIBE_PAPER_COMMISSION_MIN`（5）
- `VIBE_PAPER_STAMP_TAX_RATE`（0.0005）、`VIBE_PAPER_TRANSFER_FEE_RATE`（0.00001）
- `VIBE_PAPER_REFRESH_ENABLED`（默认 true；false 时仅前端打开页面时按需取价）

### 4.6 API（新路由 `src/api/paper_routes.py`，前缀 `/api/paper`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/account` | 账户总览（现金/市值/总资产/累计与当日盈亏） |
| GET | `/positions` | 当前持仓聚合（含成本价、现价、收益率、缠论打分、可卖数量、陈旧标记） |
| POST | `/buy` | body `{symbol, qty}`；服务端取价成交，返回成交单 |
| POST | `/sell` | body `{symbol, qty}`；T+1/FIFO 校验后成交 |
| GET | `/orders` | 成交流水，支持 `symbol`、`side`、分页 |
| GET | `/closes` | 已平仓明细 + 汇总统计（胜率/平均盈亏/平均持有天数/累计费用） |
| GET | `/nav?range=all\|20d\|5d` | 净值快照序列 |
| GET | `/buy-preview?symbol=&qty=` | 买入前价格（盘中实时/盘后收盘，带口径标记）+ 费用试算 + 最新缠论打分 |
| POST | `/refresh` | 手动触发一次全持仓行情刷新（同步返回最新持仓） |
| POST | `/reset` | 重置账户（二次确认由前端保证） |

- 认证/监听面：与现有 watchlist 路由相同的注册方式；不新增对外监听面，继续 loopback 默认绑定。
- 错误约定复用现有 API 的错误响应结构；4xx 覆盖：资金不足、数量非法、无可卖数量（T+1）、行情不可用（实时价与收盘价均取不到）、未关注标的。买卖接口**不返回“非交易时段”错误**，响应中带 `price_session`（live/close）与 `price_trade_date` 供前端标注。

### 4.7 后台调度

- 在 `api_server.py` 的 `_lifespan`（`agent/api_server.py:153-170`）启动一个 `asyncio` 后台任务（路由注册函数内挂 `app.state`，关闭时取消），不引入 APScheduler 等新依赖。
- 调度循环每 60 秒检查一次；锚点 11:30（上午 2 小时点）/ 15:00（下午 2 小时点，兼作收盘定格），通过“当日已执行锚点”记录保证重启后不重复刷新。
- 服务在锚点之后才启动（如 13:00 启动）：不补造盘中历史价格，15:00 正常刷；首日建仓时立即写一条建仓 NAV 快照，曲线起点完整。
- 服务停止期间不产生快照（净值曲线如实反映服务器在线时间，UI 对缺口做断线处理而非插值）。

### 4.8 前端

- 导航与路由：`Layout.tsx` 移除 `/portfolio` 项、新增 `/paper` 项；`router.tsx` 新增 Paper 页面路由，**保留** `/portfolio` 路由。
- 新页面 `pages/Paper.tsx`（Tab：持仓 / 流水 / 统计 / 净值），复用关注页的表格、对话框与请求封装模式（`frontend/src/lib/api.ts` 新增 paper 一组方法）。
- `Watchlist.tsx` 行操作区新增“买入”按钮与 `BuyDialog` 组件（买入完成后 toast 提示并可跳转 `/paper`）。
- 轮询：页面可见且为交易时段时 `setInterval` 每 2 小时刷新（与后端锚点错位 1 分钟拉取），切到后台/关闭停止；沿用项目无 react-query 的现状，不引入新数据层。
- i18n 文案随现有中英文案机制一并补充；红涨绿跌配色与现有页面一致。

### 4.9 Security & Privacy

- 纯本地功能：不引入新外发数据通道，行情仍走既有东财客户端；缠论打分与持仓仅存本地 DuckDB。
- 买入/卖出价格一律服务端实时获取，前端仅传 `{symbol, qty}`，防止伪造价格/收益。
- 不触碰任何 live/order 门禁与凭证代码；不新增 shell/MCP 工具。

### 4.10 测试策略

- 单元测试（`agent/tests/`，pytest，行情全部 mock、禁网）：
  - 费用计算：佣金最低 5 元边界、印花税仅卖出、过户费；
  - 买入：资金不足、非 100 整数倍、无缠论打分、实时与收盘行情均取不到；
  - 价格口径：盘中按实时价成交；夜间/周末/节假日按上一交易日收盘价成交且正确标记 price_session、登记 price_trade_date；
  - 分批买入移动加权成本；
  - T+1：批次登记交易日当日可卖为 0、下一交易日释放；周一夜间收盘价买入周二可卖、周六收盘价买入下周一可卖；
  - 卖出 FIFO 部分成交、已实现盈亏与 `paper_close` 对账；
  - 总览恒等式、当日盈亏；
  - 调度：交易日历判断、锚点去重、休市/节假日不刷新、失败重试与陈旧标记。
- API 层测试参照 `agent/tests/test_portfolio_routes.py` 的既有模式。
- 前端：关键组件（BuyDialog 费用试算、持仓收益率渲染、T+1 禁用态）补充 vitest。
- 对账样本：固定一组 3 只股票、跨 2 个交易日的买卖序列，期望现金/成本/盈亏/收益率逐字段断言。

---

## 5. Risks & Roadmap

### 5.1 Technical Risks

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 东财接口限频/短时失败 | 整点价格缺失 | 批量单请求（一次传全部代码）、2 次重试、陈旧价标记；不伪造价格 |
| DuckDB 后台任务与 API 并发写 | 锁冲突/写失败 | 短连接 + 写事务串行化；捕获写锁异常退避重试 |
| `trading_calendar` 数据过期（长假） | 交易日误判 | 复用 `resolve_market_dates` 的三级回退（日历→daily_bar→工作日），日志显式告警来源 |
| 服务非常驻（用户只用前端时） | 盘中快照缺口 | 前端交易时段轮询兜底；曲线对缺口断线展示，不插值造假 |
| 行情价格口径（最新价 vs 收盘） | 盘后误用陈旧实时价 | 统一取价函数按当前时段返回 live/close 口径并落库 price_session/price_trade_date；对话框、成交单、持仓行明确展示口径，收益率全部基于实际成交价计算 |
| 用户直接访问旧 `/portfolio` 产生困惑 | 两个“持仓”概念混淆 | 旧页面标题不改；新菜单与页面命名统一为“模拟持仓”，路由 `/paper` |

### 5.2 Phased Rollout

**MVP（第一批，可用闭环）**

- 菜单调整（隐藏旧入口、新增模拟持仓）；建表与账户初始化（10 万）
- 关注列表买入按钮 + 买入对话框（实时价、费用试算、缠论打分快照）
- 持仓列表：成本价、现价、浮盈、买入后收益率
- 服务端交易时段每 2 小时刷新 + 前端轮询兜底 + 手动刷新
- T+1 卖出（FIFO、费用、回款）
- 账户总览卡片 + 重置账户
- 后端单测与对账样本

**v1.1（统计与体验补全）**

- 成交流水、已平仓视图、胜率等汇总统计
- 净值曲线（快照图表、区间切换）
- 缠论打分在持仓/平仓记录中的完整展示（打分文案 tooltip）
- 前端 vitest、非交易时段/陈旧状态的空态与文案打磨

**v2.0（增值方向，需另立 PRD）**

- 分红送股/除权除息处理；停牌股票的特殊状态
- 缠论打分与模拟收益的分组分析（打分有效性量化）
- 多模拟账户、初始资金 UI 配置；基于净值的最大回撤/夏普等指标
- 卖出时对照最新缠论打分（vs 买入快照）的决策提示
