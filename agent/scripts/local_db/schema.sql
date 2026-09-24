-- Vibe-Trading 本地行情库 DDL（DuckDB）
--
-- 设计原则：
--   1. daily_bar 只存 raw（不复权）原始价；复权需求用 adj_factor 现算
--      （raw * adj_factor），避免 tencent 加法平移 qfq / eastmoney qfq
--      口径不一致污染回测。
--   2. 所有表均带 source，保证每个数值可溯源。
--   3. 财务/股本类表带 ann_date（披露日），回测取数一律按 ann_date 做
--      point-in-time，避免未来函数；港股 F10 不提供披露日时允许为 NULL。
--   4. 主键配合 INSERT OR REPLACE 实现幂等增量灌数，可重复执行。
--
-- 执行方式：由 init_local_db.py 自动执行，也可手动：
--   duckdb ~/.vibe-trading/data/market.duckdb < schema.sql

-- 1. 证券主数据 ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS instrument_master (
    symbol       VARCHAR PRIMARY KEY,   -- 工程规范代码：01810.HK / 600519.SH / AAPL.US
    name         VARCHAR,              -- 中文简称
    name_en      VARCHAR,
    market       VARCHAR,              -- hk_equity / a_share / us_equity / forex / index
    currency     VARCHAR,              -- 报价币种 HKD / CNY / USD
    exchange     VARCHAR,              -- HKEX / SSE / SZSE / NYSE ...
    list_date    DATE,
    delist_date  DATE,
    lot_size     BIGINT,               -- 每手股数（港股重要）
    sector       VARCHAR,
    industry     VARCHAR,
    is_active    BOOLEAN DEFAULT true,
    source       VARCHAR,
    updated_at   TIMESTAMP DEFAULT current_timestamp
);

-- 2. 交易日历 ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trading_calendar (
    market    VARCHAR,
    cal_date  DATE,
    is_open   BOOLEAN,
    PRIMARY KEY (market, cal_date)
);

-- 3. 日线行情（仅 raw 原始价；local loader 的取数契约表） ----------------
CREATE TABLE IF NOT EXISTS daily_bar (
    symbol         VARCHAR,
    trade_date     DATE,
    open           DOUBLE,
    high           DOUBLE,
    low            DOUBLE,
    close          DOUBLE,
    volume         DOUBLE,   -- 单位见 volume_unit：A股=lots(手)，港/美股=shares(股)
    amount         DOUBLE,   -- 成交额（报价币种）
    volume_unit    VARCHAR,  -- lots / shares
    price_caliber  VARCHAR DEFAULT 'raw',  -- raw / qfq / hfq；本库初始化只写 raw
    source         VARCHAR,  -- tencent / eastmoney
    updated_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, trade_date)
);

-- 4. 复权因子 ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS adj_factor (
    symbol      VARCHAR,
    trade_date  DATE,
    adj_factor  DOUBLE,      -- 累计复权因子；复权价 = raw * adj_factor
    source      VARCHAR,
    updated_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, trade_date)
);

-- 5. 外汇参考汇率 --------------------------------------------------------
CREATE TABLE IF NOT EXISTS fx_rate (
    base        VARCHAR,     -- 例如 HKD / USD
    quote       VARCHAR,     -- 例如 CNY / HKD
    rate_date   DATE,
    rate        DOUBLE,      -- 1 base = rate quote
    rate_type   VARCHAR,     -- reference（参考汇率）/ trading（交易汇率）
    source      VARCHAR,     -- frankfurter_ecb
    fetched_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (base, quote, rate_date, rate_type)
);

-- 6. 股本（已发行/流通，point-in-time） ----------------------------------
CREATE TABLE IF NOT EXISTS shares_outstanding (
    symbol         VARCHAR,
    report_date    DATE,     -- 报告期
    ann_date       DATE,     -- 披露日（PIT 用；港股 F10 不提供时为 NULL）
    shares_issued  BIGINT,   -- 已发行股本（非法定股本）
    shares_float   BIGINT,   -- 流通股本（港股取 F10 的 HK_COMMON_SHARES）
    share_class    VARCHAR DEFAULT 'common',
    change_reason  VARCHAR,
    currency       VARCHAR,
    source         VARCHAR,
    updated_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, report_date, share_class)
);

-- 7. 财务报表（IS/BS/CF 长表） -------------------------------------------
CREATE TABLE IF NOT EXISTS financial_statement (
    symbol       VARCHAR,
    report_date  DATE,
    ann_date     DATE,
    statement    VARCHAR,    -- IS 利润表 / BS 资产负债表 / CF 现金流量表
    field        VARCHAR,    -- revenue / net_income / total_equity / cfo ...
    value        DOUBLE,
    currency     VARCHAR,
    period_type  VARCHAR,    -- annual / quarter / ttm
    source       VARCHAR,
    updated_at   TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, report_date, statement, field)
);

-- 8. 公司行动（分红/拆股/配股） -----------------------------------------
CREATE TABLE IF NOT EXISTS corporate_action (
    symbol        VARCHAR,
    ex_date       DATE,
    event_type    VARCHAR,   -- dividend / split / rights
    cash_div      DOUBLE,
    split_ratio   DOUBLE,
    rights_ratio  DOUBLE,
    currency      VARCHAR,
    source        VARCHAR,
    updated_at    TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, ex_date, event_type)
);

-- 9. 估值参考快照（供应商口径，仅用于交叉验证，不作为主算口径） ----------
CREATE TABLE IF NOT EXISTS valuation_daily (
    symbol           VARCHAR,
    trade_date       DATE,    -- 供应商快照日；F10 初始化为报告期日（见 note）
    pe_ttm           DOUBLE,
    pb               DOUBLE,
    total_market_cap DOUBLE,
    currency         VARCHAR,
    note             VARCHAR,  -- 口径说明，如 period_end_reference
    source           VARCHAR,
    updated_at       TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, trade_date, source)
);

-- 10. 灌数日志 -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_log (
    run_at   TIMESTAMP DEFAULT current_timestamp,
    task     VARCHAR,
    symbol   VARCHAR,
    status   VARCHAR,   -- ok / skipped / error
    rows     BIGINT,
    message  VARCHAR
);
