"""MySQL connectivity and schema bootstrap for the macro analysis module.

Connections are short-lived (open per operation, closed in ``finally``) and
all credentials come from the typed config layer — never from ``os.getenv``
here.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import pymysql
from pymysql.cursors import DictCursor

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)

#: DDL for the user-provided judgment table — kept byte-for-byte compatible
#: with the supplied MySQL DDL (columns, comments and idx_economy_date).
JUDGMENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS `macro_cycle_judgment` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `economy` varchar(50) NOT NULL COMMENT '经济体名称',
  `statistics_date` varchar(20) NOT NULL COMMENT '数据截止月份',
  `current_cycle` text COMMENT '【主题：当前周期】最终周期阶段判定',
  `judgment_result` text COMMENT '【主题：判定结果】整体周期结论',
  `dimension_check` text COMMENT '【主题：维度校验】四维核心维度判定结果',
  `meso_verify` text COMMENT '【主题：中观验证】中观周期共振校验结论',
  `history_cycle_anchor` text COMMENT '【主题：历史周期锚定】历史周期匹配结果',
  `judgment_confidence` varchar(100) DEFAULT NULL COMMENT '【主题：判定置信度】置信度评级',
  `core_support` text COMMENT '【主题：核心支撑】核心支撑指标与逻辑',
  `core_risk` text COMMENT '【主题：核心风险】核心风险与背离点',
  `extended_remark` text COMMENT '扩展备注：所有不确定、待补充内容统一存入此字段',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_economy_date` (`economy`,`statistics_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='宏观经济周期判定结果表';
"""

#: Editable prompt definitions; ``orchestration_config`` reserves the future
#: "AI tool orchestration flow" capability without another schema change.
PROMPT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS `macro_analysis_prompt` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `code` varchar(20) NOT NULL COMMENT '提示词编码：a/b/c',
  `name` varchar(100) NOT NULL COMMENT '提示词名称',
  `prompt_text` mediumtext COMMENT '提示词正文（仅管理员可编辑）',
  `enabled` tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否可用：1可用 0预留',
  `sort_order` int NOT NULL DEFAULT 0 COMMENT '展示顺序',
  `orchestration_config` text DEFAULT NULL COMMENT 'AI工具编排调用流程定义(JSON)，预留扩展',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='宏观分析提示词定义表';
"""


class MacroDataAccessError(RuntimeError):
    """Raised when the macro MySQL store cannot be reached or queried.

    The message is deliberately free of credentials; callers may surface it
    directly to API clients.
    """


def _connection_kwargs() -> dict[str, Any]:
    cfg = get_env_config().macro
    return {
        "host": cfg.macro_db_host,
        "port": cfg.macro_db_port,
        "user": cfg.macro_db_user,
        "password": cfg.macro_db_password,
        "database": cfg.macro_db_name,
        "charset": "utf8mb4",
        "connect_timeout": 5,
        "autocommit": False,
        "cursorclass": DictCursor,
    }


@contextmanager
def macro_connection() -> Iterator[pymysql.connections.Connection]:
    """Yield a short-lived MySQL connection for the macro schema.

    Raises:
        MacroDataAccessError: on any connection failure (credentials scrubbed).
    """
    try:
        conn = pymysql.connect(**_connection_kwargs())
    except Exception as exc:  # pymysql.MySQLError plus socket-level errors
        raise MacroDataAccessError(
            "无法连接宏观分析数据库，请检查 MACRO_DB_* 配置与数据库状态。"
        ) from exc
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # best-effort close
            logger.debug("macro MySQL connection close failed", exc_info=True)


def initialize_schema(seeds: Optional[list[dict[str, Any]]] = None) -> None:
    """Create both macro tables when missing and seed the prompt rows.

    Idempotent: safe to call on every service construction. Seeding uses
    ``INSERT IGNORE`` so administrator edits and re-runs never overwrite the
    stored prompt body.
    """
    from src.macro.prompts import SEED_PROMPTS

    rows = seeds if seeds is not None else list(SEED_PROMPTS)
    try:
        with macro_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(JUDGMENT_TABLE_DDL)
                cur.execute(PROMPT_TABLE_DDL)
                cur.executemany(
                    "INSERT IGNORE INTO macro_analysis_prompt "
                    "(code, name, prompt_text, enabled, sort_order) "
                    "VALUES (%(code)s, %(name)s, %(prompt_text)s, %(enabled)s, %(sort_order)s)",
                    rows,
                )
            conn.commit()
    except MacroDataAccessError:
        raise
    except Exception as exc:
        raise MacroDataAccessError("宏观分析数据库初始化失败。") from exc
