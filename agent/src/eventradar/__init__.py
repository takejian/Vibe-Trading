"""Event Analysis: breaking-news radar + macro Event-Driven Task Force.

Two concerns live in this package:

1. ``radar`` — multi-source news collection, dedup/clustering, verification
   state machine and paradigm scoring (tables ``radar_*``).
2. ``reports`` — macro event Task Force runs archived from the swarm runtime
   (table ``event_report``).

Everything is local-only: news access goes through the existing throttled
tool clients, persistence lands in the market DuckDB via short connections,
and no new outbound listener is introduced.
"""
