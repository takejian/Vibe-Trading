#!/usr/bin/env python3
"""Gap-free bi-centric ASCII charts for chanlun_analyst reports.

Library + simple CLI. The CLI auto-draws pivots from ``c.zs_list`` and is
mainly a smoke test / quick view; production reports use a small driver
script that imports ``build_czsc`` / ``bi_chains`` / ``bi_grid`` and passes
curated pivots, markers and titles (see SKILL.md for the snippet).

Hard visual contract (mirrors the chanlun_analyst prompt):
* the bi polyline is ONE continuous chain — flat '─', steep '│',
  diagonal '╱'/'╲', unfinished bi '╌'/'╎'; every ● joins both neighbours;
* bi strokes OVERPRINT pivot shading (never broken by '░' / '═');
* 100% of the bi in the drawn segment are shown, plus the unfinished bi;
* a dated/priced node table is printed under every grid.

Usage:
  .venv/bin/python bi_charts.py <payload.json> <30m|1d|1w|1mo|1y>
      [--tail N] [--width 104] [--height 20] [--price P]
"""
from __future__ import annotations

import argparse
import json

import pandas as pd
from czsc import CZSC, Freq, RawBar

FREQ = {'30m': Freq.F30, '1d': Freq.D, '1w': Freq.W,
        '1mo': Freq.M, '1y': Freq.Y}


def build_czsc(json_payload, interval):
    df = pd.DataFrame(json_payload['bars'])
    df['dt'] = pd.to_datetime(df['trade_date'])
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'amount' not in df.columns:
        df['amount'] = df['close'] * df['volume']
    else:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
    df = (df.dropna(subset=['open', 'high', 'low', 'close'])
            .sort_values('dt').reset_index(drop=True))
    bars = [RawBar(symbol='x', id=i, dt=r['dt'].to_pydatetime(),
                   freq=FREQ[interval], open=float(r['open']),
                   close=float(r['close']), high=float(r['high']),
                   low=float(r['low']), vol=float(r['volume']),
                   amount=float(r['amount']))
            for i, r in df.iterrows()]
    return CZSC(bars), df


def bi_chains(c, wrap=8, with_ubi=True, date_slice=10):
    """Full compact chain of 100% bi, wrapped; returns (lines, legs)."""
    legs = []
    for i, b in enumerate(c.bi_list):
        if i == 0:
            legs.append((str(b.sdt)[:date_slice], b.fx_a.fx, None))
        legs.append((str(b.edt)[:date_slice], b.fx_b.fx,
                     'up' if int(b.direction) == 0 else 'down'))
    if with_ubi and c.bars_ubi:
        legs.append((str(c.bars_ubi[-1].dt)[:date_slice],
                     float(c.bars_ubi[-1].close), 'ubi'))
    lines, cur = [], ''
    for i, (_d, p, dirn) in enumerate(legs):
        token = f'{p:6.2f}'
        if dirn == 'up':
            token = ' ↗ ' + token
        elif dirn == 'down':
            token = ' ↘ ' + token
        elif dirn == 'ubi':
            token = ' ┊ ' + token + '(未完成)'
        if i == 0:
            token = token.strip()
        cur += token
        if (i + 1) % wrap == 0:
            lines.append(cur.strip())
            cur = ''
    if cur.strip():
        lines.append(cur.strip())
    return lines, legs


def node_table(c, tail=None, date_slice=10):
    bis = c.bi_list if tail is None else c.bi_list[-tail:]
    rows = [(str(bis[0].sdt)[:date_slice], bis[0].fx_a.fx, '起点')]
    for b in bis:
        rows.append((str(b.edt)[:date_slice], b.fx_b.fx,
                     '向上笔' if int(b.direction) == 0 else '向下笔'))
    if c.bars_ubi:
        u = c.bars_ubi[-1]
        rows.append((str(u.dt)[:date_slice], float(u.close), '未完成笔'))
    return rows


def bi_grid(c, pivots, markers, current_price, width=104, height=20,
            tail=None, title=''):
    """Rasterize the bi zigzag onto one canvas.

    pivots: [(label, zg, zd)]; markers: {node_index: '▲'/'▼'} where node 0
    is the first bi start (use ``tail`` consistently with the grid).
    Returns (chart_text, coords, pts).
    """
    bis = c.bi_list if tail is None else c.bi_list[-tail:]
    pts = [(str(bis[0].sdt)[:10], bis[0].fx_a.fx, False)]
    for b in bis:
        pts.append((str(b.edt)[:10], b.fx_b.fx, False))
    if c.bars_ubi:
        pts.append((str(c.bars_ubi[-1].dt)[:10],
                    float(c.bars_ubi[-1].close), True))

    band_vals = [v for _label, zg, zd in pivots for v in (zg, zd)]
    pmin = min(p[1] for p in pts) * 0.985
    pmax = max(p[1] for p in pts) * 1.015
    if band_vals:
        pmin = min(pmin, min(band_vals) * 0.985)
        pmax = max(pmax, max(band_vals) * 1.015)
    n = len(pts)
    step = max(2, (width - 6) // max(1, n - 1))
    xs = [3 + min(i * step, width - 4) for i in range(n)]
    grid = [[' '] * width for _ in range(height)]

    def row_of(p):
        return int(round((height - 3) * (pmax - p) / (pmax - pmin))) + 1

    def put(r, col, ch):
        if 0 <= r < height and 0 <= col < width:
            grid[r][col] = ch

    # pivot bands first: '═' edges, '░' body
    for _label, zg, zd in pivots:
        rt, rb = sorted((row_of(zg), row_of(zd)))
        for r in range(rt, rb + 1):
            fill = '═' if r in (rt, rb) else '░'
            for x in range(1, width - 1):
                if grid[r][x] == ' ':
                    grid[r][x] = fill
    coords = [(xs[i], row_of(p[1])) for i, p in enumerate(pts)]

    # current-price dotted line BEFORE strokes, so bi lines overprint it
    ry = row_of(current_price)
    for x in range(1, width - 1):
        if grid[ry][x] in (' ', '░', '═'):
            grid[ry][x] = '┈'

    # ONE continuous slope-aware polyline; strokes overprint pivot shading
    for i in range(n - 1):
        x0, r0 = coords[i]
        x1, r1 = coords[i + 1]
        dashed = pts[i + 1][2]
        hflat, hvert = ('╌', '╎') if dashed else ('─', '│')
        prev_r = r0
        for x in range(x0 + 1, x1):
            t = (x - x0) / (x1 - x0)
            yf = r0 + (r1 - r0) * t
            r = int(yf + 0.5) if yf >= 0 else -int(0.5 - yf)
            lo, hi = sorted((prev_r, r))
            for rr in range(lo + 1, hi):       # steep: vertical fill
                put(rr, x, hvert)
            if r == prev_r:
                put(r, x, hflat)
            else:
                put(r, x, '╲' if r > prev_r else '╱')
            prev_r = r

    lab = f'现价{current_price:.2f}'
    last_x = coords[-1][0]
    lx = width - len(lab) - 2 if last_x < width - len(lab) - 4 else 2
    for j, ch in enumerate(lab):
        put(ry, lx + j, ch)

    # nodes / markers on the very top
    for i, ((x, y), (_d, _p, ubi)) in enumerate(zip(coords, pts)):
        mk = markers.get(i)
        grid[y][x] = mk if mk else ('◌' if ubi else '●')

    idx_row = [' '] * width
    for i, x in enumerate(xs):
        s = str(i + 1)
        for j, ch in enumerate(s):
            if x + j < width:
                idx_row[x + j - (len(s) // 2)] = ch
    out = [f'  {title}']
    for r in range(height):
        line = ''.join(grid[r]).rstrip()
        if 1 <= r <= height - 2:
            price_at = pmax - (pmax - pmin) * (r - 1) / (height - 3)
            axis = f'{price_at:6.2f} |'
        else:
            axis = '       |'
        if line.strip():
            out.append(axis + line)
    out.append('       +' + '-' * (width - 2))
    out.append('        ' + ''.join(idx_row).rstrip())
    return '\n'.join(out), coords, pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('payload', type=argparse.FileType('r'))
    ap.add_argument('interval', choices=sorted(FREQ))
    ap.add_argument('--tail', type=int, default=None)
    ap.add_argument('--width', type=int, default=104)
    ap.add_argument('--height', type=int, default=20)
    ap.add_argument('--price', type=float, default=None)
    args = ap.parse_args()

    c, df = build_czsc(json.loads(args.payload.read()), args.interval)
    price = args.price if args.price is not None else float(df['close'].iloc[-1])
    tail = args.tail
    pivots = [(f'ZS{i + 1}', float(z.zg), float(z.zd))
              for i, z in enumerate(c.zs_list[-4:])]
    if tail is not None:
        pivots = pivots[-3:]
    grid, _coords, _pts = bi_grid(
        c, pivots=pivots, markers={}, current_price=price,
        width=args.width, height=args.height, tail=tail,
        title=f'{args.interval} bi grid ({len(c.bi_list)} completed bi)')
    print(grid)
    for line in bi_chains(c, date_slice=5)[0]:
        print('  ' + line)
    print('节点明细：' + '；'.join(f'{i + 1}={d} {p:.2f}({k})'
          for i, (d, p, k) in enumerate(node_table(c, tail=tail))))


if __name__ == '__main__':
    main()
