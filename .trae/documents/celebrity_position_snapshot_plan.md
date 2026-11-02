# 投资名人持仓：覆盖式 + 变动快照 + 占比 实施计划

## Repository Research

当前「投资名人持仓 & 言论跟踪」模块中，`celebrity_position` 表是**追加模式**（`append_positions`），前端展示「标的 / 变动方向 / 来源 / 更新时间 / 置信度」，无持仓占比字段。提示词 `latest_dynamics.current_positions` 也只要求 target/source/update_time/confidence。

本次核心变更：
1. **当前持仓改为覆盖式**：刷新时先删除该投资人旧持仓，再写入新持仓（前 15 条）。
2. **变动才存快照**：刷新后对比新旧持仓，若有变动（标的集合或占比变化），则把旧持仓整体写入快照表，用**日期**作标签；无变动则快照不动。
3. **历史回灌**：历史持仓写入快照表，不覆盖当前持仓；历史观点仍追加。
4. **展示前 15 标的 + 持仓占比**：当前持仓表格新增「持仓占比」列，标题注明「前 15 大重仓」。

涉及文件：
- `docs/BDD_投资名人持仓言论跟踪.md`
- `agent/src/celebrity/db.py`（DDL、`overwrite_positions`、快照表 CRUD、`list_positions` 限 15）
- `agent/src/celebrity/prompts.py`（`latest_dynamics` 加 `percentage`/前 15；`history_backfill` 加 `percentage`/快照）
- `agent/src/celebrity/service.py`（`refresh_investor` 走覆盖+快照；`backfill_history` 写快照表）
- `frontend/src/lib/api.ts`（`CelebrityPosition` 加 `percentage`）
- `frontend/src/components/celebrity/InvestorCard.tsx`（持仓表：标的 / 持仓占比 / 来源 / 更新时间 / 置信度）

## Implementation Steps

### Step 1 — 修改 BDD 文档（先做）

更新 `docs/BDD_投资名人持仓言论跟踪.md`：
- US-02「展示当前持仓列表」：改为前 15 标的，字段「标的名称、持仓占比、来源备注、更新时间、置信度」（删除「变动方向」）。
- US-03「点击刷新成功」：当前持仓直接覆盖；若仓位有变动则保存一份带日期标签的快照，无变动则快照不动；观点/调仓仍追加。
- US-04「定时刷新」：同步覆盖+快照规则。
- US-09「回灌历史」：历史持仓写入**持仓快照表**，不覆盖当前持仓；历史观点仍追加。
- 3.1 / 3.6 数据管理规则：新增「当前持仓覆盖 + 变动快照」规则；快照以日期为标签。
- 五、数据管理规则：写入策略拆分（持仓覆盖+快照；观点/调仓追加）。
- 附录 A.1 最新动态提示词：`current_positions` 增加 `percentage`（持仓占比，字符串如 "12.5%"），要求返回前 15 大重仓股，删除 `direction`。
- 附录 A.5 历史回灌提示词：`history_positions` 增加 `percentage`，明确写入快照表。
- 术语表：新增「持仓快照」「持仓占比」释义。
- ASCII 原型 4.2 当前持仓表头改为「标的 / 持仓占比 / 来源 / 更新时间 / 置信度」。

### Step 2 — 后端 `agent/src/celebrity/db.py`

- DDL：`celebrity_position` 增加 `percentage VARCHAR`；新增 `celebrity_position_snapshot` 表：
  ```
  CREATE TABLE IF NOT EXISTS celebrity_position_snapshot (
      id             UUID PRIMARY KEY DEFAULT uuid(),
      investor_id    INTEGER NOT NULL,
      snapshot_date  VARCHAR(16) NOT NULL,   -- 日期标签 YYYY-MM-DD
      target         VARCHAR(256) NOT NULL,
      percentage     VARCHAR(32),
      source         VARCHAR(256),
      confidence     VARCHAR(16),
      created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
  );
  ```
- 新增 `overwrite_positions(conn, investor_id, positions, snapshot_date)`：
  1. 读取旧持仓（`list_positions`）。
  2. 对比新旧持仓：以 `target` 集合 + `percentage` 为差异判定（任一不同即视为变动）。
  3. 若变动且旧持仓非空：将旧持仓逐条插入 `celebrity_position_snapshot`，`snapshot_date` 用传入日期。
  4. `DELETE FROM celebrity_position WHERE investor_id = ?`。
  5. 插入新持仓前 15 条（`percentage` 一并写入），返回插入数。
- `append_positions` 保留（供历史回灌写快照时复用其清洗逻辑，或新增 `append_position_snapshots`）。新增 `append_position_snapshots(conn, investor_id, snapshots, snapshot_date)` 写快照表。
- `list_positions` 保持不变（service 层取前 15，或在 db 层 `LIMIT 15`）。
- 新增 `list_position_snapshots(conn, investor_id)` 供后续历史查看（按 `snapshot_date DESC` 分组）。
- `delete_investor` 增加删除 `celebrity_position_snapshot`。

### Step 3 — 后端 `agent/src/celebrity/prompts.py`

- `latest_dynamics`：`current_positions` 字段改为 `target / percentage / source / update_time / confidence`；`percentage` 为持仓占比字符串（如 "12.5%"，未知则空串）；明确要求返回**前 15 大重仓股**。
- `history_backfill`：`history_positions` 增加 `percentage` 字段；说明这些是历史快照数据，写入持仓快照表。

### Step 4 — 后端 `agent/src/celebrity/service.py`

- `refresh_investor`：
  - 持仓走 `db.overwrite_positions(conn, investor_id, positions, snapshot_date)`，`snapshot_date` 用今天日期（`datetime.now().strftime("%Y-%m-%d")`）。
  - 观点/调仓仍 `append_opinions` / `append_adjusts`。
  - 返回 `inserted` 中 `positions` 为覆盖写入数；新增 `snapshot_saved` 布尔字段（是否保存了快照）。
- `backfill_history`：
  - 历史持仓走 `db.append_position_snapshots(conn, investor_id, history_positions, snapshot_date)`（每条记录用其 `time` 作为 `snapshot_date`，无 `time` 则用今天）。
  - 历史观点仍 `append_opinions`。
  - **不触碰当前持仓表**。

### Step 5 — 前端 `frontend/src/lib/api.ts`

- `CelebrityPosition` 接口增加 `percentage: string | null`。
- `CelebrityRefreshResult` 增加可选 `snapshot_saved?: boolean`。

### Step 6 — 前端 `frontend/src/components/celebrity/InvestorCard.tsx`

- 当前持仓表头改为 `["标的", "持仓占比", "来源", "更新时间", "置信度"]`。
- 标题旁注明「前 15 大重仓」。
- 行内渲染 `p.percentage || "—"`，删除 `p.direction` 列。

### Step 7 — 验证

- 后端：编写/运行 service 层测试（用临时 DuckDB 覆盖 `get_market_db_path`），验证：
  - 首次刷新写入持仓。
  - 第二次相同持仓刷新不产生快照。
  - 第二次不同持仓刷新产生一条快照且当前持仓被覆盖。
  - 历史回灌写入快照表、不影响当前持仓。
- 前端：`npx tsc --noEmit` + `npm run build`。

## Dependencies and Considerations

- **DuckDB 短连接 + `initialize_schema`**：所有函数内部调用 `initialize_schema`，新增表/列会自动创建；`percentage` 列用 `ALTER TABLE` 或在 DDL 中处理。由于表已存在于部分环境，需用 `CREATE TABLE IF NOT EXISTS` 外再加列迁移（DuckDB 不支持 `ADD COLUMN IF NOT EXISTS` 旧版本，可 try/except 包裹 `ALTER TABLE ... ADD COLUMN`）。
- **快照标签日期**：刷新用当天日期；回灌用记录自身 `time`。同日多次刷新仅在变动时追加快照（允许同日多份，或按 `snapshot_date` 去重覆盖——选择「追加」，因为同一天多次调仓也应保留历史）。
- **差异判定**：比较 `target` 集合 + `percentage`。若旧持仓为空而新非空 → 变动（但旧为空无需快照）；若旧非空且与新不同 → 快照保存旧持仓。
- **前 15 限制**：`overwrite_positions` 内部对传入 positions 切片 `[:15]`；提示词也要求返回前 15。
- **`direction` 字段**：表中保留 `direction` 列（不删除，避免迁移风险），但不再写入/展示。
- 不新增 API 路由（快照历史查看暂不暴露前端，db 层提供 `list_position_snapshots` 备用）。

## Validation

- 后端 service 层 pytest（临时 DB）：覆盖逻辑 + 快照触发 + 回灌隔离。
- 前端 `tsc --noEmit` + `npm run build`。
- 手动检查 BDD 文档与代码字段一致。

## Risks

- **DuckDB 列迁移**：若环境已有 `celebrity_position` 表无 `percentage` 列，`INSERT` 会失败。处理：`initialize_schema` 中 try/except `ALTER TABLE celebrity_position ADD COLUMN percentage VARCHAR`。
- **快照表膨胀**：每周刷新一次，变动才存，量级可控。
- **LLM 返回 percentage 格式不统一**：存为字符串，前端原样展示，不做解析。
