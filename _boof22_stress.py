"""
Boof 22.0 — Full Stats + 4-Level Slippage Stress Test
Baseline + Level 1-4 slippage dials
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import run_boof22, compute_atr

TRADE    = 200
TM_PCT   = 0.08
MAX_HOLD = 30
ATR_TP   = 4.0
ATR_SL   = 2.0

SYMBOLS = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
months  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

# ── Collect raw signals ──
print('Extracting ATR signals...')
signals = []
for mo in months:
    for sym in SYMBOLS:
        df = dfs.get((sym, mo))
        if df is None: continue
        if 'atr' not in df.columns:
            df = df.copy(); df['atr'] = compute_atr(df)
        trades = run_boof22(df, symbol=sym, tp_pct=0.99, sl_pct=0.99)
        for t in trades:
            bar_i = t.get('bar')
            if bar_i is None: continue
            atr = float(df['atr'].iloc[bar_i]) if bar_i < len(df) else 0
            if not atr or np.isnan(atr): continue
            ep  = float(t['entry'])
            d   = t['direction']
            close_slice = df['close'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            high_slice  = df['high'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            low_slice   = df['low'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            if len(close_slice) == 0: continue
            signals.append({
                'entry': ep, 'atr': atr, 'direction': d,
                'closes': close_slice, 'highs': high_slice, 'lows': low_slice,
            })

print(f'Total signals: {len(signals)}\n')

# ── Simulate with slippage dials ──
def simulate(signals, entry_slip=0.0, exit_slip=0.0, spread=0.0, delay_bars=0, flip_pct=0.0, label=''):
    """
    entry_slip : fraction worse on entry price (e.g. 0.001 = 0.1%)
    exit_slip  : fraction worse on exit price (e.g. 0.001 = 0.1%)
    spread     : one-way spread cost as fraction of entry
    delay_bars : skip N bars before evaluating TP/SL (simulates fill lag)
    flip_pct   : fraction of TP wins converted to time exits (delayed entry miss)
    """
    pnls = []
    tp_c = sl_c = tm_c = 0

    for idx, s in enumerate(signals):
        ep_raw  = s['entry']
        atr     = s['atr']
        d       = s['direction']
        closes  = s['closes']
        highs   = s['highs']
        lows    = s['lows']

        # Worse entry fill
        if d == 'long':
            ep = ep_raw * (1 + entry_slip)   # paid more
        else:
            ep = ep_raw * (1 - entry_slip)   # sold less

        tp_p = ep + atr * ATR_TP if d == 'long' else ep - atr * ATR_TP
        sl_p = ep - atr * ATR_SL if d == 'long' else ep + atr * ATR_SL

        # Skip delay_bars before checking TP/SL
        start = min(delay_bars, len(closes))
        bars  = closes[start:]

        et = 'time'
        exit_price = closes[-1] if len(closes) > 0 else ep
        for i, price in enumerate(bars):
            if d == 'long':
                if price >= tp_p: et = 'tp'; exit_price = price; break
                if price <= sl_p: et = 'sl'; exit_price = price; break
            else:
                if price <= tp_p: et = 'tp'; exit_price = price; break
                if price >= sl_p: et = 'sl'; exit_price = price; break

        # Delayed entry flip: some TP wins become time exits
        if et == 'tp' and flip_pct > 0:
            if (idx % max(1, int(1/flip_pct))) == 0:
                et = 'time'
                exit_price = closes[-1] if len(closes) > 0 else ep

        # Worse exit fill + spread cost
        spread_cost = ep_raw * spread

        if et == 'tp':
            if d == 'long':
                exit_price = exit_price * (1 - exit_slip)
            else:
                exit_price = exit_price * (1 + exit_slip)
            raw_move = abs(exit_price - ep) / ep
            pnl = TRADE * raw_move - spread_cost
            tp_c += 1
        elif et == 'sl':
            if d == 'long':
                exit_price = exit_price * (1 - exit_slip)
            else:
                exit_price = exit_price * (1 + exit_slip)
            raw_move = abs(exit_price - ep) / ep
            pnl = -TRADE * raw_move - spread_cost
            sl_c += 1
        else:
            pnl = TRADE * TM_PCT - spread_cost
            tm_c += 1

        pnls.append(pnl)

    return np.array(pnls), tp_c, sl_c, tm_c


def stats(arr, tp_c, sl_c, tm_c, label):
    n     = len(arr)
    wins  = arr[arr > 0]
    losses= arr[arr < 0]
    wr    = round(len(wins)/n*100, 1)
    pf    = round(float(sum(wins)/max(abs(sum(losses)),0.01)), 2)
    ev    = round(float(np.mean(arr)), 2)
    avg_w = round(float(np.mean(wins)), 2) if len(wins) else 0
    avg_l = round(float(np.mean(losses)), 2) if len(losses) else 0
    annual= round(float(sum(arr)))

    # Sharpe
    sharpe = round((np.mean(arr)/np.std(arr, ddof=1))*np.sqrt(n), 2) if np.std(arr, ddof=1) > 0 else 0

    # Max Drawdown
    cum   = np.cumsum(arr)
    peak  = np.maximum.accumulate(cum)
    dd    = peak - cum
    max_dd= round(float(dd.max()))

    # Calmar
    calmar = round(annual / max(max_dd, 0.01), 2)

    # Max consec losses
    max_consec = cur = 0
    for p in arr:
        cur = cur+1 if p < 0 else 0
        max_consec = max(max_consec, cur)

    status = '🟢 STRONG' if pf >= 1.5 else '🟡 OK' if pf >= 1.1 else '🔴 FRAGILE'

    print(f'\n{"─"*62}')
    print(f' {label}  {status}')
    print(f'{"─"*62}')
    print(f'  Trades:          {n:,}  ({tp_c} TP / {sl_c} SL / {tm_c} time)')
    print(f'  Win Rate:        {wr}%')
    print(f'  Avg Win:         ${avg_w}  |  Avg Loss: ${avg_l}')
    print(f'  Profit Factor:   {pf}')
    print(f'  EV per trade:    ${ev}')
    print(f'  Annual P&L:      ${annual:,}')
    print(f'  Sharpe Ratio:    {sharpe}')
    print(f'  Max Drawdown:    ${max_dd:,}')
    print(f'  Calmar Ratio:    {calmar}')
    print(f'  Max consec loss: {max_consec}')

    return pf, annual


print('='*62)
print(' BOOF 22.0 — ATR Exits (4x TP / 2x SL) | $200/trade')
print('='*62)

# BASELINE
arr0, tp0, sl0, tm0 = simulate(signals, label='BASELINE')
stats(arr0, tp0, sl0, tm0, '🟢 BASELINE')

# LEVEL 1 — Light slippage (realistic retail)
arr1, tp1, sl1, tm1 = simulate(signals,
    entry_slip=0.0005,   # +1 tick worse entry (~0.05%)
    exit_slip=0.0005,    # -1 tick worse exit (~0.05%)
    spread=0.0005,       # 0.05% spread cost
    label='LEVEL 1')
stats(arr1, tp1, sl1, tm1, '🔵 LEVEL 1 — Light slippage (realistic retail)')

# LEVEL 2 — Realistic stress
arr2, tp2, sl2, tm2 = simulate(signals,
    entry_slip=0.0005,   # +0.05% worse entry
    exit_slip=0.0005,    # -0.05% worse exit
    delay_bars=1,        # 1-bar lag before TP/SL checks
    spread=0.0005,
    label='LEVEL 2')
stats(arr2, tp2, sl2, tm2, '🟡 LEVEL 2 — Realistic stress (fast but imperfect execution)')

# LEVEL 3 — Bad conditions
arr3, tp3, sl3, tm3 = simulate(signals,
    entry_slip=0.001,    # +0.1% worse entry
    exit_slip=0.001,     # -0.1% worse exit
    delay_bars=2,        # 2-bar fill lag
    spread=0.001,        # 0.1% spread
    flip_pct=0.10,       # 10% of TP wins → time exits (missed due to lag)
    label='LEVEL 3')
stats(arr3, tp3, sl3, tm3, '🟠 LEVEL 3 — Bad conditions (volatility / fast moves)')

# LEVEL 4 — Extreme stress
arr4, tp4, sl4, tm4 = simulate(signals,
    entry_slip=0.002,    # +0.2% worse entry
    exit_slip=0.002,     # -0.2% worse exit
    delay_bars=3,        # 3-bar fill lag
    spread=0.002,        # 0.2% spread expansion
    flip_pct=0.20,       # 20% of TP wins → time exits
    label='LEVEL 4')
stats(arr4, tp4, sl4, tm4, '🔴 LEVEL 4 — Extreme stress ("will it break?" test)')

# ── Summary table ──
print(f'\n{"="*62}')
print(' SUMMARY')
print(f'{"="*62}')
print(f'  {"Level":<40} {"PF":>6}  {"Status"}')
print(f'  {"-"*55}')
levels = [
    ('🟢 Baseline',                          arr0),
    ('🔵 L1 — Light slippage',               arr1),
    ('🟡 L2 — Realistic stress',             arr2),
    ('🟠 L3 — Bad conditions',               arr3),
    ('🔴 L4 — Extreme stress',               arr4),
]
for lbl, arr in levels:
    wins = arr[arr>0]; losses = arr[arr<0]
    pf = round(float(sum(wins)/max(abs(sum(losses)),0.01)),2)
    ann = round(float(sum(arr)))
    status = '✓ STRONG' if pf>=1.5 else '~ OK' if pf>=1.1 else '✗ FRAGILE'
    print(f'  {lbl:<40} {pf:>6}  {status}  ${ann:,}')
print(f'{"="*62}')
