#!/usr/bin/env python3
"""Deterministic czsc structural scan over archived objective_kline payloads.

Input: a directory containing ``{level}.json`` files as returned by the
project objective_kline tool (bars: trade_date/open/high/low/close/volume).
Output (stdout): per level — provenance/window, zhongshu, every bi with its
MACD(12,26,9) histogram area + endDIF, unfinished-bi live areas, latest DIF;
daily level additionally prints MA stack, RSI6, 1y range and volume ratios.

The analyst (LLM) reads this output; this script makes no buy/sell judgment.

Usage:
  .venv/bin/python .trae/skills/chanlun-bi-analysis/scripts/czsc_scan.py \\
      <payload_dir> [--levels 30m,1d,1w,1mo,1y] [--last 30] [--symbol X.SH]
"""
from __future__ import annotations

import argparse
import json
import pathlib

import pandas as pd
from czsc import CZSC, Freq, RawBar

# czsc 1.0.1 has NO quarterly Freq — 1q payloads are reported raw-only.
FREQ = {'30m': Freq.F30, '1d': Freq.D, '1w': Freq.W,
        '1mo': Freq.M, '1y': Freq.Y}


def load_payload(path: pathlib.Path):
    payload = json.loads(path.read_text())
    df = pd.DataFrame(payload['bars'])
    df['dt'] = pd.to_datetime(df['trade_date'])  # dict access: row['dt']
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'amount' in df.columns:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
    else:
        df['amount'] = df['close'] * df['volume']
    df = (df.dropna(subset=['open', 'high', 'low', 'close'])
            .sort_values('dt').reset_index(drop=True))
    meta = {k: payload.get(k) for k in
            ('level_status', 'fresh', 'source', 'refresh_error', 'bars_count')}
    return df, meta


def build_czsc(df: pd.DataFrame, interval: str, symbol: str) -> CZSC:
    bars = [
        RawBar(symbol=symbol, id=i, dt=row['dt'].to_pydatetime(),
               freq=FREQ[interval], open=float(row['open']),
               close=float(row['close']), high=float(row['high']),
               low=float(row['low']), vol=float(row['volume']),
               amount=float(row['amount']))
        for i, row in df.iterrows()
    ]
    return CZSC(bars)


def macd_series(df):
    dif = df['close'].ewm(span=12, adjust=False).mean() - \
        df['close'].ewm(span=26, adjust=False).mean()
    hist = dif - dif.ewm(span=9, adjust=False).mean()
    return (pd.Series(list(dif), index=df['dt']),
            pd.Series(list(hist), index=df['dt']))


def rsi(close: pd.Series, n: int = 6) -> float:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, pd.NA)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def report_level(payload_dir: pathlib.Path, interval: str,
                 last_n: int, symbol: str) -> None:
    path = payload_dir / f'{interval}.json'
    print('=' * 88)
    if not path.exists():
        print(f'LEVEL {interval}: payload missing ({path})')
        print('=' * 88)
        return
    df, meta = load_payload(path)
    print(f"LEVEL {interval}  status={meta['level_status']} "
          f"source={meta['source']} bars={len(df)} "
          f"{df['dt'].iloc[0]} -> {df['dt'].iloc[-1]}")
    print('=' * 88)

    if interval not in FREQ or len(df) < 12:
        print(f"  raw-only read ({len(df)} bars; czsc needs >=12 "
              f"or no intramonth Freq): H={df['high'].max():.2f} "
              f"L={df['low'].min():.2f} C={df['close'].iloc[-1]:.2f}")
        return

    c = build_czsc(df, interval, symbol)
    dif, hist = macd_series(df)

    print(f"-- zhongshu ({len(c.zs_list)} total); "
          f"attrs are lowercase zg/zd/zz/gg/dd --")
    for z in c.zs_list:
        print(f"  ZS {str(z.sdt)[:10]}~{str(z.edt)[:10]} ({len(z.bis)}bi) "
              f"zg={z.zg:.2f} zd={z.zd:.2f} zz={z.zz:.2f} "
              f"gg={z.gg:.2f} dd={z.dd:.2f}")

    print(f"-- bi ({len(c.bi_list)} completed; "
          f"last {min(last_n, len(c.bi_list))}); direction 0=up --")
    for b in c.bi_list[-last_n:]:
        seg = hist.loc[b.sdt:b.edt]
        up = int(b.direction) == 0
        area = (float(seg[seg > 0].sum()) if up
                else float(seg[seg < 0].sum()))
        print(f"  {str(b.sdt)[:10]} {b.fx_a.fx:8.2f} -> "
              f"{str(b.edt)[:10]} {b.fx_b.fx:8.2f} "
              f"{'up  ' if up else 'down'} area={area:8.2f} "
              f"endDIF={float(dif.loc[b.edt]):7.3f}")

    if c.bars_ubi:
        u = c.bars_ubi
        live = hist.loc[u[0].dt:]
        print(f"-- unfinished bi: {len(u)} bars since {str(u[0].dt)[:16]}; "
              f"last {str(u[-1].dt)[:16]} H{u[-1].high:.2f} "
              f"L{u[-1].low:.2f} C{u[-1].close:.2f} | live area "
              f"+{float(live[live > 0].sum()):.2f}/"
              f"{float(live[live < 0].sum()):.2f}")
    print(f"-- latest close {float(df['close'].iloc[-1]):.2f} "
          f"DIF={float(dif.iloc[-1]):.3f} hist={float(hist.iloc[-1]):.3f}")

    if interval == '1d':
        close = df['close']
        mas = {n: float(close.rolling(n).mean().iloc[-1])
               for n in (5, 10, 20, 60, 120, 250) if len(close) >= n}
        ma_txt = ' '.join(f'MA{n}={v:.2f}' for n, v in mas.items())
        vol = df['volume']
        v60 = float(vol.rolling(60).mean().iloc[-1])
        v250 = (float(vol.rolling(250).mean().iloc[-1])
                if len(vol) >= 250 else float('nan'))
        print(f"-- daily context: {ma_txt}")
        print(f"   RSI6(SMA method; vendor terminals may differ)="
              f"{rsi(close):.1f}  vol {float(vol.iloc[-1]):.0f} "
              f"= {float(vol.iloc[-1]) / v60:.2f}x60ma / "
              f"{float(vol.iloc[-1]) / v250:.2f}x250ma")
        win = df.tail(250)
        print(f"   1y range {float(win['low'].min()):.2f} ~ "
              f"{float(win['high'].max()):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('payload_dir', type=pathlib.Path)
    ap.add_argument('--levels', default='30m,1d,1w,1mo,1y')
    ap.add_argument('--last', type=int, default=30)
    ap.add_argument('--symbol', default='X')
    args = ap.parse_args()
    for lv in args.levels.split(','):
        report_level(args.payload_dir, lv.strip(), args.last, args.symbol)
        print()


if __name__ == '__main__':
    main()
