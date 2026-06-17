"""
ATR-Based Exit Optimizer for Boof 21.0
Tests different ATR multipliers for TP and SL to find the best combination.
Uses cached 1-min data + re-runs exit logic post-signal using per-bar ATR.
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21

TRADE_SIZE = 200
TM_PCT     = 0.08   # time exit pct (flat trade)
MAX_HOLD   = 30     # bars (minutes) before time exit

months = [('Jan 25',23),('Feb 25',20),('Mar 25',21),('Apr 25',22),
          ('May 25',21),('Jun 25',21),('Jul 25',23),('Aug 25',21),
          ('Sep 25',22),('Oct 25',23),('Nov 25',20),('Dec 25',23)]
SYMBOLS = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

print('Loading cache...')
dfs = pickle.load(open('_boof21_cache.pkl','rb'))

# ── Collect raw signal data: entry_price, atr_at_entry, direction, df slice ──
print('Extracting signals with ATR at entry...')
signals = []
for mo, _ in months:
    for sym in SYMBOLS:
        df = dfs.get((sym, mo))
        if df is None: continue
        # ensure ATR column exists
        if 'atr' not in df.columns:
            from backtest_boof21 import compute_atr
            df = df.copy()
            df['atr'] = compute_atr(df)
        trades = bt21.backtest(df, symbol=sym)
        for t in trades:
            entry_time = t.get('entry_time')
            if entry_time is None: continue
            # timezone-safe index lookup
            locs = df.index.get_indexer([entry_time], method='nearest')
            ei = locs[0]
            if ei < 0 or ei >= len(df): continue
            atr = float(df['atr'].iloc[ei])
            if np.isnan(atr) or atr == 0: continue
            direction   = t['direction']
            entry_price = float(t['entry'])
            close_slice = df['close'].iloc[ei+1 : ei+MAX_HOLD+2].values
            if len(close_slice) == 0: continue
            signals.append({
                'entry':     entry_price,
                'atr':       atr,
                'direction': direction,
                'bars':      close_slice,
            })

print(f'Total signals: {len(signals)}\n')

# ── ATR multiplier combinations to test ──
tp_mults = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
sl_mults = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

def simulate_atr_exits(signals, tp_mult, sl_mult):
    pnls = []
    tp_c = sl_c = tm_c = 0
    for s in signals:
        ep  = s['entry']
        atr = s['atr']
        d   = s['direction']
        bars = s['bars']

        tp_price = ep + atr * tp_mult if d == 'LONG' else ep - atr * tp_mult
        sl_price = ep - atr * sl_mult if d == 'LONG' else ep + atr * sl_mult

        exit_type = 'time'
        for price in bars:
            if d == 'LONG':
                if price >= tp_price:
                    exit_type = 'tp'; break
                if price <= sl_price:
                    exit_type = 'sl'; break
            else:
                if price <= tp_price:
                    exit_type = 'tp'; break
                if price >= sl_price:
                    exit_type = 'sl'; break

        if exit_type == 'tp':
            pnl = TRADE_SIZE * (atr * tp_mult / ep)
            tp_c += 1
        elif exit_type == 'sl':
            pnl = -TRADE_SIZE * (atr * sl_mult / ep)
            sl_c += 1
        else:
            pnl = TRADE_SIZE * TM_PCT
            tm_c += 1
        pnls.append(pnl)

    arr  = np.array(pnls)
    wins = arr[arr > 0]
    loss = arr[arr < 0]
    n    = len(arr)
    wr   = round(len(wins)/n*100, 1)
    pf   = round(sum(wins)/max(abs(sum(loss)), 0.01), 2)
    ann  = round(sum(arr))
    ev   = round(np.mean(arr), 2)
    return wr, pf, ann, ev, tp_c, sl_c, tm_c

# ── Run grid ──
print(f'{"TP×ATR":<8} {"SL×ATR":<8} {"WR%":<7} {"PF":<6} {"Annual$":<12} {"EV/trade":<10} {"TP/SL/TM"}')
print('-'*72)

results = []
for tp_m in tp_mults:
    for sl_m in sl_mults:
        wr, pf, ann, ev, tp_c, sl_c, tm_c = simulate_atr_exits(signals, tp_m, sl_m)
        results.append((tp_m, sl_m, wr, pf, ann, ev))
        print(f'{tp_m:<8} {sl_m:<8} {wr:<7} {pf:<6} ${ann:<11,} ${ev:<9} {tp_c}/{sl_c}/{tm_c}')

# ── Top 5 by Annual P&L ──
print(f'\n{"="*72}')
print('TOP 5 BY ANNUAL P&L')
print(f'{"="*72}')
top5 = sorted(results, key=lambda x: x[4], reverse=True)[:5]
for r in top5:
    print(f'  TP={r[0]}x ATR  SL={r[1]}x ATR  →  PF={r[3]}  WR={r[2]}%  Annual=${r[4]:,}  EV=${r[5]}')

# ── Top 5 by Profit Factor ──
print(f'\n{"="*72}')
print('TOP 5 BY PROFIT FACTOR')
print(f'{"="*72}')
top5pf = sorted(results, key=lambda x: x[3], reverse=True)[:5]
for r in top5pf:
    print(f'  TP={r[0]}x ATR  SL={r[1]}x ATR  →  PF={r[3]}  WR={r[2]}%  Annual=${r[4]:,}  EV=${r[5]}')
