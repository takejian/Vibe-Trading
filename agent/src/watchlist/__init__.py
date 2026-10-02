"""Watchlist (自选标的) module: personal A-share watchlist + per-symbol research.

L2 business package. Stores:

* personal watchlist membership — JSON under ``<runtime_root>/watchlist``;
* objective raw data and structured Chanlun analyses — the local DuckDB
  market warehouse (see :mod:`src.watchlist.db`).

Agent analyses reuse the swarm standalone role-run machinery
(:mod:`src.swarm.role_runs`); this package never creates new agents.
"""
