"""
BOOF60 TP/SL Optimization Sweep
Tests multiple TP/SL combos on both option % and stock % basis
Uses cached 5m parquet data (6 months)
"""
import pandas as pd
import numpy as np
import pytz
import os
from itertools import product

ET    = pytz.timezone('America/New_York')
CACHE = "boof_data"
SUFFIX = "_5m_6mo.parquet"

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]

GAP_UP_MIN   = 1.0
PDH_NEAR_PCT = 0.8
REJECT_PCT   = 0.50
MAX_POS      = 5
MAX_BARS     = 60
BUDGET       = 750.0
OPTION_MULT  = 2.0

# ── TP/SL combos to test ──────────────────────────────────────────
# Option % based
OPT_TP_VALUES = [10, 15, 20, 25, 35, 50]
OPT_SL_VALUES = [-8, -12, -15, -20, -25, -35]

# Stock % based (converted to option % via OPTION_MULT)
STK_TP_VALUES = [0.5, 1.0, 1.5, 2.0, 3.0]   # stock % → opt % = *2
STK_SL_VALUES = [-0.4, -0.6, -0.8, -1.0, -1.5]

# ── Load data ─────────────────────────────────────────────────────
def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print("Loading cache...")
data = {sym: load_sym(sym) for sym in SYMBOLS + ['SPY']}

print("Building daily OHLC...")
daily = {}
for sym in SYMBOLS + ['SPY']:
    df = data[sym]
    if df.empty: daily[sym] = pd.DataFrame(); continue
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d

spy_daily = daily['SPY']
all_dates  = sorted(spy_daily.index.date)[1:]
print(f"Simulating {len(all_dates)} days across {len(SYMBOLS)} symbols\n")

# ── Collect raw bar-by-bar trade paths (entry → exit bar sequence) ─
# Do one pass to get all trade paths, then sweep TP/SL against them
print("Collecting trade paths (one-pass)...")
raw_trades = []  # {sym, date, direction, bars: [(opt_pct, mfe_so_far, mae_so_far)]}

for day in all_dates:
    pdh_broken  = set()
    pdh_touched = set()
    spy_prices  = []
    regime      = "neutral"
    active_pos  = {}

    spy_rth = data['SPY']
    spy_day = spy_rth[spy_rth.index.date == day].between_time('09:30','15:55') if not spy_rth.empty else pd.DataFrame()

    for sym in SYMBOLS:
        dh   = daily.get(sym, pd.DataFrame())
        if dh.empty: continue
        prev = dh[dh.index.date < day]
        if len(prev) < 1: continue
        prev_close = float(prev['close'].iloc[-1])
        pdh        = float(prev['high'].iloc[-1])

        bars_5m = data.get(sym, pd.DataFrame())
        if bars_5m.empty: continue
        rth = bars_5m[bars_5m.index.date == day].between_time('09:30','15:55')
        if len(rth) < 2: continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100
        gap_ok   = gap_pct > GAP_UP_MIN
        confirm  = False
        in_trade = None
        bar_path = []  # list of (opt_pct_at_bar, stock_pct_at_bar)

        for i, (ts, bar) in enumerate(rth.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            o_px  = float(bar['open'])
            high  = float(bar['high'])
            low   = float(bar['low'])

            # SPY regime
            if i < len(spy_day):
                spy_prices.append(float(spy_day.iloc[min(i, len(spy_day)-1)]['close']))
                if len(spy_prices) > 5: spy_prices.pop(0)
                if len(spy_prices) >= 3:
                    if   spy_prices[-1] > spy_prices[0] * 1.001:  regime = "bull"
                    elif spy_prices[-1] < spy_prices[0] * 0.999:  regime = "bear"
                    else:                                           regime = "neutral"

            if in_trade:
                entry_px  = in_trade['entry_price']
                direction = in_trade['direction']
                if direction == 'long':
                    stk_pct = (price - entry_px) / entry_px * 100
                    mfe_stk = (high  - entry_px) / entry_px * 100
                    mae_stk = (low   - entry_px) / entry_px * 100
                else:
                    stk_pct = (entry_px - price) / entry_px * 100
                    mfe_stk = (entry_px - low)   / entry_px * 100
                    mae_stk = (entry_px - high)  / entry_px * 100

                opt_pct = stk_pct * OPTION_MULT
                mfe_opt = mfe_stk * OPTION_MULT
                mae_opt = mae_stk * OPTION_MULT

                in_trade['bars_held'] += 1
                bar_path.append({
                    'opt_pct': opt_pct, 'stk_pct': stk_pct,
                    'mfe_opt': mfe_opt, 'mae_opt': mae_opt,
                    'mfe_stk': mfe_stk, 'mae_stk': mae_stk,
                    'hm': hm
                })

                if in_trade['bars_held'] >= MAX_BARS or hm >= '15:50':
                    raw_trades.append({
                        'date': day, 'sym': sym,
                        'direction': in_trade['direction'],
                        'entry_time': in_trade['entry_time'],
                        'regime': regime,
                        'gap_pct': gap_pct,
                        'bars': bar_path,
                    })
                    if sym in active_pos: del active_pos[sym]
                    in_trade = None
                continue

            if hm >= '15:30': break
            if len(active_pos) >= MAX_POS: continue

            # LONG signal
            if gap_ok and price > pdh and sym not in pdh_broken:
                if not confirm: confirm = True; continue
                if regime in ('bull', 'neutral'):
                    pdh_broken.add(sym)
                    in_trade = {'sym': sym, 'direction': 'long', 'entry_price': price,
                                'entry_time': hm, 'bars_held': 0}
                    active_pos[sym] = True

            # SHORT signal
            near_pdh = abs(price - pdh) / pdh < (PDH_NEAR_PCT / 100)
            reject   = o_px > 0 and price < o_px * (1 - REJECT_PCT / 100)
            if near_pdh and reject and sym not in pdh_touched and sym not in pdh_broken and not gap_ok:
                if regime in ('bear', 'neutral'):
                    pdh_touched.add(sym)
                    in_trade = {'sym': sym, 'direction': 'short', 'entry_price': price,
                                'entry_time': hm, 'bars_held': 0}
                    active_pos[sym] = True

        if in_trade and bar_path:
            raw_trades.append({'date': day, 'sym': sym,
                'direction': in_trade['direction'],
                'entry_time': in_trade['entry_time'],
                'regime': regime, 'gap_pct': gap_pct, 'bars': bar_path})

print(f"Collected {len(raw_trades)} raw trade paths\n")

# ── Sweep TP/SL combos ────────────────────────────────────────────
def sim_combo(tp, sl, mode='opt'):
    """Replay all trade paths with given TP/SL. mode='opt' or 'stk'"""
    results = []
    for t in raw_trades:
        pnl       = None
        exit_bar  = len(t['bars']) - 1
        exit_type = 'TIMEOUT'
        for j, b in enumerate(t['bars']):
            val = b['opt_pct'] if mode == 'opt' else b['stk_pct'] * OPTION_MULT
            mfe = b['mfe_opt'] if mode == 'opt' else b['mfe_stk'] * OPTION_MULT
            mae = b['mae_opt'] if mode == 'opt' else b['mae_stk'] * OPTION_MULT
            if mfe >= tp:
                pnl = BUDGET * tp / 100; exit_type = 'TP'; break
            if mae <= sl:
                pnl = BUDGET * sl / 100; exit_type = 'SL'; break
        if pnl is None:
            last = t['bars'][-1]
            pnl  = BUDGET * (last['opt_pct'] if mode == 'opt' else last['stk_pct'] * OPTION_MULT) / 100
        results.append({'pnl': pnl, 'exit': exit_type})
    df = pd.DataFrame(results)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr   = len(wins) / len(df) if len(df) else 0
    pf   = wins['pnl'].sum() / abs(losses['pnl'].sum()) if len(losses) and losses['pnl'].sum() != 0 else 999
    ev   = df['pnl'].mean()
    tot  = df['pnl'].sum()
    tp_hits = len(df[df['exit'] == 'TP'])
    sl_hits = len(df[df['exit'] == 'SL'])
    return {'tp': tp, 'sl': sl, 'mode': mode,
            'wr': round(wr*100,1), 'pf': round(pf,2), 'ev': round(ev,2),
            'total': round(tot,2), 'tp_hits': tp_hits, 'sl_hits': sl_hits,
            'n': len(df)}

print("Sweeping option % TP/SL combos...")
opt_rows = []
for tp, sl in product(OPT_TP_VALUES, OPT_SL_VALUES):
    opt_rows.append(sim_combo(tp, sl, mode='opt'))

print("Sweeping stock % TP/SL combos (converted to option %)...")
stk_rows = []
for tp_stk, sl_stk in product(STK_TP_VALUES, STK_SL_VALUES):
    tp_opt = tp_stk * OPTION_MULT
    sl_opt = sl_stk * OPTION_MULT
    row = sim_combo(tp_opt, sl_opt, mode='stk')
    row['tp_stk'] = tp_stk; row['sl_stk'] = sl_stk
    stk_rows.append(row)

# ── Print results ─────────────────────────────────────────────────
opt_df = pd.DataFrame(opt_rows).sort_values('total', ascending=False)
stk_df = pd.DataFrame(stk_rows).sort_values('total', ascending=False)

print(f"\n{'='*70}")
print("OPTION % TP/SL SWEEP — Top 15 by Total P&L")
print(f"{'='*70}")
print(opt_df.head(15)[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits']].to_string(index=False))

print(f"\n{'='*70}")
print("STOCK % TP/SL SWEEP (converted to option %) — Top 15 by Total P&L")
print(f"{'='*70}")
print(stk_df.head(15)[['tp_stk','sl_stk','wr','pf','ev','total','tp_hits','sl_hits']].to_string(index=False))

print(f"\n{'='*70}")
print("BEST BY PROFIT FACTOR (opt %)")
print(f"{'='*70}")
print(opt_df.sort_values('pf', ascending=False).head(10)[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits']].to_string(index=False))

print(f"\n{'='*70}")
print("BEST BALANCED (PF > 1.3 AND WR > 50%) — opt %")
print(f"{'='*70}")
bal = opt_df[(opt_df['pf'] > 1.3) & (opt_df['wr'] > 50)]
if bal.empty:
    print("  None found — relax thresholds")
    bal = opt_df[(opt_df['pf'] > 1.2) & (opt_df['wr'] > 48)]
print(bal[['tp','sl','wr','pf','ev','total','tp_hits','sl_hits']].to_string(index=False))

# Save full results
opt_df.to_csv('boof60_opt_sweep.csv', index=False)
stk_df.to_csv('boof60_stk_sweep.csv', index=False)
print(f"\nFull sweep saved to boof60_opt_sweep.csv and boof60_stk_sweep.csv")
