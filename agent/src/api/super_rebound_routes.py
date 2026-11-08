"""HTTP routes for the super-rebound (超跌反弹) finance module.

Mounted by ``agent/api_server.py`` via ``register_super_rebound_routes(app)``.
All endpoints are behind ``require_auth``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from src.api.security import require_auth
from src.super_rebound import service

logger = logging.getLogger(__name__)


def register_super_rebound_routes(app: FastAPI) -> None:
    """Mount all /api/super-rebound/* routes behind require_auth."""

    @app.get("/api/super-rebound/finance/margin-ratio", dependencies=[Depends(require_auth)])
    def rebound_margin_ratio() -> dict[str, Any]:
        result = service.get_margin_ratio_latest()
        if result.get("error") == "no_data":
            raise HTTPException(status_code=404, detail=result.get("message", "No data"))
        return result

    @app.get("/api/super-rebound/finance/etf-monitor", dependencies=[Depends(require_auth)])
    def rebound_etf_monitor(
        start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """ETF 净流入头部汇总（份额口径，上交所官方数据源）。"""
        return service.get_etf_flow_overview(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-monitor-detail", dependencies=[Depends(require_auth)])
    def rebound_etf_monitor_detail(
        start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """ETF 净流入每日明细 + 累计（份额口径）。"""
        return service.get_etf_flow_detail(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-flow-overview", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_overview(
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.get_etf_flow_overview(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-flow-detail", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_detail(
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.get_etf_flow_detail(start_date, end_date)

    @app.post("/api/super-rebound/finance/etf-flow-collect", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_collect() -> dict[str, Any]:
        """手动触发 ETF 净流入采集（上交所官方接口，最新交易日）。"""
        try:
            return service.refresh_etf_flow()
        except Exception as exc:
            logger.exception("etf flow collect failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/super-rebound/finance/etf-flow-backfill", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_backfill(
        start_date: str = Query(..., description="起始 YYYY-MM-DD"),
        end_date: str = Query(..., description="结束 YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """上交所 ETF 历史份额回灌（官方 scale 接口，按交易日循环）。"""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            return service.backfill_etf_history(start, end)
        except Exception as exc:
            logger.exception("etf flow backfill failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/super-rebound/finance/refresh-needed", dependencies=[Depends(require_auth)])
    def rebound_refresh_needed() -> dict[str, Any]:
        return service.refresh_needed()

    @app.post("/api/super-rebound/finance/refresh", dependencies=[Depends(require_auth)])
    def rebound_refresh() -> dict[str, Any]:
        try:
            return service.refresh_data()
        except Exception as exc:
            logger.exception("super-rebound refresh failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # --- Indicator (超跌指标) routes — TODO stubs ---
    # These endpoints are declared but return placeholder data.
    # Full implementation requires:
    #   - Per-dimension data fetching (ERP, 估值分位, RSI, BIAS, MACD, etc.)
    #   - Dimension score computation + weighted aggregate
    #   - Missing-dimension normalisation
    #   - External data source integration (AKShare / BaoStock / custom APIs)
    @app.get("/api/super-rebound/indicator/score", dependencies=[Depends(require_auth)])
    def rebound_indicator_score(
        index_code: str = Query(default="沪深300", description="沪深300/上证A500/上证50/中证500/中证1000/创业板/科创50"),
    ) -> dict[str, Any]:
        # TODO: implement real scoring
        return {
            "index_code": index_code,
            "total_score": None,
            "signal": "pending",
            "message": "超跌指标评分后端接口待实现（TODO），当前返回空数据",
            "dimensions": [
                {"name": "赔率层", "weight": 30, "score": None, "status": "pending"},
                {"name": "技术超卖", "weight": 20, "score": None, "status": "pending"},
                {"name": "资金承接", "weight": 25, "score": None, "status": "pending"},
                {"name": "情绪广度", "weight": 15, "score": None, "status": "pending"},
                {"name": "外部流动性/政策", "weight": 10, "score": None, "status": "pending"},
            ],
            "todo": [
                "ERP 数据获取与高位区间判断",
                "估值分位历史数据计算（PE/PB 分位）",
                "阶段回撤计算",
                "RSI(14) 计算",
                "BIAS 乖离计算",
                "MACD 底背离检测",
                "自动引用资金面数据（两融 < 250%, ETF > 1000亿）",
                "涨跌扩散度、成交量 PCR",
                "SHIBOR/DR007 资金利率",
                "外部风险事件信号",
            ],
        }

    @app.get("/api/super-rebound/indicator/dimensions", dependencies=[Depends(require_auth)])
    def rebound_indicator_dimensions(
        index_code: str = Query(default="沪深300"),
    ) -> dict[str, Any]:
        # TODO: implement real dimension details
        return {
            "index_code": index_code,
            "dimensions": [
                {
                    "name": "赔率层",
                    "weight": 30,
                    "indicators": [
                        {"name": "ERP", "criterion": "ERP > 5", "value": None, "score": None},
                        {"name": "估值分位", "criterion": "估值分位 > 80%", "value": None, "score": None},
                        {"name": "阶段回撤", "criterion": "回撤 > 15%", "value": None, "score": None},
                    ],
                },
                {
                    "name": "技术超卖",
                    "weight": 20,
                    "indicators": [
                        {"name": "RSI(14)", "criterion": "RSI < 30", "value": None, "score": None},
                        {"name": "负乖离", "criterion": "明显负乖离", "value": None, "score": None},
                        {"name": "MACD 底背离", "criterion": "底背离出现", "value": None, "score": None},
                    ],
                },
                {
                    "name": "资金承接",
                    "weight": 25,
                    "indicators": [
                        {"name": "两融维持担保比例", "criterion": "< 250%", "value": None, "score": None, "auto_from_finance": True},
                        {"name": "ETF 持续流入", "criterion": "> 1000亿", "value": None, "score": None, "auto_from_finance": True},
                    ],
                },
                {
                    "name": "情绪广度",
                    "weight": 15,
                    "indicators": [
                        {"name": "上涨家数占比", "criterion": "长期 < 20%", "value": None, "score": None},
                        {"name": "成交量 PCR", "criterion": "> 1", "value": None, "score": None},
                    ],
                },
                {
                    "name": "外部流动性/政策",
                    "weight": 10,
                    "indicators": [
                        {"name": "资金利率", "criterion": "SHIBOR/DR007 高位", "value": None, "score": None},
                        {"name": "外部风险事件", "criterion": "美股大跌/地缘冲突", "value": None, "score": None},
                    ],
                },
            ],
            "todo": "指标数据获取与计算逻辑待实现",
        }
