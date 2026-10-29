#!/bin/bash
# Wrapper to fix sqlite3 before starting vibe-trading
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libsqlite3.so.0
cd /home/ai/Vibe-Trading
source .venv/bin/activate
exec vibe-trading serve --host 0.0.0.0 --port 8899
