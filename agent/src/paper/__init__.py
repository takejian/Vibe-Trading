"""Simulated A-share paper portfolio (local, fully isolated from live trading).

Public surface:
* :mod:`src.paper.calendar` — A-share trading-day / session clock.
* :mod:`src.paper.db`       — DuckDB tables and DAO.
* :mod:`src.paper.prices`   — live/close price resolution.
* :mod:`src.paper.service`  — buy/sell/fees/FIFO/T+1, queries and statistics.
* :mod:`src.paper.scheduler`— 2-hour in-session background refresh task.
"""
