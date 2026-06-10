"""
Full analysis suite for Boof 22.0 — mirrors all tests run on Boof 21:
1. EV / Win Rate / PF
2. Sharpe Ratio
3. Max Drawdown + Calmar
4. Slippage Stress Test
5. ATR Exit Optimizer
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import run_boof22, compute_atr

TRADE   = 200
TP      = 0.35
SL      = -0.18
TM      = 0.08
MAX_HOLD = 30

SYMBOLS = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
months  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print('Loading Boof 22 cache...')
dfs = pickle.load(open('_boof22_cache.pkl','rb'))

# ── Collect trades ──
print('Running Boof 22 backtest...')
raw_trades = []
for mo in months:
    for sym in SYMBOLS:
        df = dfs.get((sym, mo))
        if df is None: continue
        trades = run_boof22(df, symbol=sym, tp_pct=TP, sl_pct=abs(SL))
        for t in trades:
            et = t.get('exit_type','')
            pnl = TRADE*TP if et=='tp' else TRADE*SL if et=='sl' else TRADE*TM
            raw_trades.append({'pnl': pnl, 'exit_type': et, 'trade': t, 'sym': sym, 'mo': mo})

pnls = [t['pnl'] for t in raw_trades]
arr  = np.array(pnls)
n    = len(arr)
print(f'Total trades: {n}\n')

# ══════════════════════════════════════════════════════
# 1. EV / WIN RATE / PF
# ══════════════════════════════════════════════════════
wins   = arr[arr > 0]
losses = arr[arr < 0]
wr     = round(len(wins)/n*100, 1)
lr     = 100 - wr
avg_w  = round(float(np.mean(wins)), 2) if len(wins) else 0
avg_l  = round(float(np.mean(losses)), 2) if len(losses) else 0
pf     = round(float(sum(wins)/max(abs(sum(losses)),0.01)), 2)
ev     = round(float(np.mean(arr)), 2)
annual = round(float(sum(arr)))
monthly= round(annual/12)
tpd    = round(n/252, 1)

print('='*55)
print(f'BOOF 22.0 | +{int(TP*100)}% TP / {int(SL*100)}% SL | ${TRADE}/trade')
print('='*55)

print(f'\n--- 1. EV / WIN RATE / PF ---')
print(f'Trades:       {n}  ({tpd}/day)')
print(f'Win Rate:     {wr}%  |  Avg Win: ${avg_w}  |  Avg Loss: ${avg_l}')
print(f'PF:           {pf}')
print(f'EV per trade: ${ev}')
print(f'EV per day:   ${round(ev*tpd, 2)}')
print(f'Annual P&L:   ${annual:,}')
print(f'Monthly avg:  ${monthly:,}')
print(f'Formula: ({wr/100:.3f} × ${avg_w}) - ({lr/100:.3f} × ${abs(avg_l)}) = ${ev}')

# ══════════════════════════════════════════════════════
# 2. SHARPE RATIO
# ══════════════════════════════════════════════════════
mean   = np.mean(arr)
std    = np.std(arr, ddof=1)
sharpe = round((mean/std)*np.sqrt(n), 2) if std > 0 else 0

print(f'\n--- 2. SHARPE RATIO ---')
print(f'Avg trade:    ${round(float(mean),2)}  |  Std: ${round(float(std),2)}')
print(f'Sharpe:       {sharpe}  (annualized per-trade)')
grade = 'Excellent' if sharpe>=2 else 'Very Good' if sharpe>=1.5 else 'Good' if sharpe>=1 else 'Below avg'
print(f'Grade:        {grade}')

# ══════════════════════════════════════════════════════
# 3. MAX DRAWDOWN + CALMAR
# ══════════════════════════════════════════════════════
cum    = np.cumsum(arr)
peak   = np.maximum.accumulate(cum)
dd_ser = peak - cum
max_dd = float(dd_ser.max())
max_dd_idx = int(dd_ser.argmax())
max_consec = cur = 0
for p in arr:
    cur = cur+1 if p < 0 else 0
    max_consec = max(max_consec, cur)
recovery = None
peak_val = float(cum[:max_dd_idx+1].max())
for i in range(max_dd_idx, len(cum)):
    if cum[i] >= peak_val:
        recovery = i - max_dd_idx
        break
calmar = round(annual / max(max_dd, 0.01), 2)

print(f'\n--- 3. MAX DRAWDOWN ---')
print(f'Max Drawdown:    ${round(max_dd):,}  (trade #{max_dd_idx})')
print(f'DD % of annual:  {round(max_dd/max(annual,1)*100,1)}%')
print(f'Max consec loss: {max_consec} in a row')
print(f'Recovery:        {recovery} trades' if recovery else 'Recovery:        Not recovered by year end')
print(f'Calmar Ratio:    {calmar}')

# ══════════════════════════════════════════════════════
# 4. SLIPPAGE STRESS TEST
# ══════════════════════════════════════════════════════
print(f'\n--- 4. SLIPPAGE STRESS TEST ---')

def stress(label, tp_red=0.0, sl_inc=0.0, entry_slip=0.0, flip_pct=0.0):
    p = []
    flipped = 0
    for i, t in enumerate(raw_trades):
        et = t['exit_type']
        if et == 'tp':
            pnl = TRADE*(TP - tp_red) - TRADE*entry_slip
            if flip_pct > 0 and (i % max(1,int(1/flip_pct))) == 0:
                pnl = TRADE*TM - TRADE*entry_slip
                flipped += 1
            p.append(pnl)
        elif et == 'sl':
            p.append(TRADE*(SL - sl_inc) - TRADE*entry_slip)
        else:
            p.append(TRADE*TM - TRADE*entry_slip)
    a = np.array(p)
    w = a[a>0]; lo = a[a<0]
    pf_s = round(float(sum(w)/max(abs(sum(lo)),0.01)), 2)
    status = 'STRONG' if pf_s >= 1.1 else 'FRAGILE'
    flag = '✓' if pf_s >= 1.1 else '✗'
    print(f'{flag} {label}')
    print(f'   PF={pf_s}  Annual=${round(float(sum(a))):,}  [{status}]')

stress('Baseline')
stress('+1 tick (0.05% slip)',         entry_slip=0.0005)
stress('Realistic spread (0.1%)',      entry_slip=0.001)
stress('Worse exits TP-2%/SL-2%',     tp_red=0.02, sl_inc=0.02)
stress('Delayed entry 10% miss',       flip_pct=0.10)
stress('Combined worst case',          tp_red=0.02, sl_inc=0.02, entry_slip=0.001, flip_pct=0.10)
stress('Extreme stress',               tp_red=0.05, sl_inc=0.05, entry_slip=0.002, flip_pct=0.20)

# ══════════════════════════════════════════════════════
# 5. ATR EXIT OPTIMIZER
# ══════════════════════════════════════════════════════
print(f'\n--- 5. ATR EXIT OPTIMIZER ---')
print('Collecting signals with ATR...')

signals = []
for mo in months:
    for sym in SYMBOLS:
        df = dfs.get((sym, mo))
        if df is None: continue
        if 'atr' not in df.columns:
            df = df.copy()
            df['atr'] = compute_atr(df)
        # Use a large TP/SL to capture all entries, then re-simulate
        trades = run_boof22(df, symbol=sym, tp_pct=0.99, sl_pct=0.99)
        for t in trades:
            bar_i = t.get('bar')
            if bar_i is None: continue
            atr = float(df['atr'].iloc[bar_i]) if bar_i < len(df) else None
            if not atr or np.isnan(atr) or atr == 0: continue
            ep  = float(t['entry'])
            d   = t['direction']
            close_slice = df['close'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            if len(close_slice) == 0: continue
            signals.append({'entry': ep, 'atr': atr, 'direction': d, 'bars': close_slice})

print(f'Signals: {len(signals)}')

tp_mults = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
sl_mults = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

def sim_atr(sigs, tp_m, sl_m):
    p = []
    for s in sigs:
        ep = s['entry']; atr = s['atr']; d = s['direction']
        tp_p = ep + atr*tp_m if d=='long' else ep - atr*tp_m
        sl_p = ep - atr*sl_m if d=='long' else ep + atr*sl_m
        et = 'time'
        for price in s['bars']:
            if d == 'long':
                if price >= tp_p: et='tp'; break
                if price <= sl_p: et='sl'; break
            else:
                if price <= tp_p: et='tp'; break
                if price >= sl_p: et='sl'; break
        if et=='tp':   pnl = TRADE*(atr*tp_m/ep)
        elif et=='sl': pnl = -TRADE*(atr*sl_m/ep)
        else:          pnl = TRADE*TM
        p.append(pnl)
    a = np.array(p); w = a[a>0]; lo = a[a<0]
    pf_v = round(float(sum(w)/max(abs(sum(lo)),0.01)), 2)
    return pf_v, round(float(sum(a))), round(float(np.mean(a)),2), round(len(w)/max(len(a),1)*100,1)

print(f'\n{"TP×ATR":<8} {"SL×ATR":<8} {"WR%":<7} {"PF":<6} {"Annual$":<12} {"EV/trade"}')
print('-'*60)
atr_results = []
for tp_m in tp_mults:
    for sl_m in sl_mults:
        pf_v, ann, ev_v, wr_v = sim_atr(signals, tp_m, sl_m)
        atr_results.append((tp_m, sl_m, wr_v, pf_v, ann, ev_v))
        print(f'{tp_m:<8} {sl_m:<8} {wr_v:<7} {pf_v:<6} ${ann:<11,} ${ev_v}')

print(f'\nTOP 5 BY ANNUAL P&L:')
for r in sorted(atr_results, key=lambda x: x[4], reverse=True)[:5]:
    print(f'  TP={r[0]}x  SL={r[1]}x  →  PF={r[3]}  WR={r[2]}%  Annual=${r[4]:,}  EV=${r[5]}')

print(f'\nTOP 5 BY PROFIT FACTOR:')
for r in sorted(atr_results, key=lambda x: x[3], reverse=True)[:5]:
    print(f'  TP={r[0]}x  SL={r[1]}x  →  PF={r[3]}  WR={r[2]}%  Annual=${r[4]:,}  EV=${r[5]}')
