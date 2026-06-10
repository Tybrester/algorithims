import pickle, sys
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21

TRADE = 200
TP_BASE = 0.35
SL_BASE = -0.18
TM_BASE = 0.08

months21 = [('Jan 25',23),('Feb 25',20),('Mar 25',21),('Apr 25',22),
            ('May 25',21),('Jun 25',21),('Jul 25',23),('Aug 25',21),
            ('Sep 25',22),('Oct 25',23),('Nov 25',20),('Dec 25',23)]
SYM21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

print('Loading cache...')
dfs21 = pickle.load(open('_boof21_cache.pkl','rb'))

# Collect raw trades once
print('Running base backtest...')
raw_trades = []
for mo, _ in months21:
    for s in SYM21:
        df = dfs21.get((s, mo))
        if df is None: continue
        trades = bt21.backtest(df, symbol=s)
        for t in trades:
            raw_trades.append(t)

print(f'Total trades: {len(raw_trades)}\n')

def simulate(trades, label,
             tp_reduction=0.0,   # reduce TP pct (slippage on winner exit)
             sl_increase=0.0,    # widen SL pct (slippage on loser exit)
             entry_slip=0.0,     # cost added per entry (as % of trade)
             flip_pct=0.0):      # % of wins flipped to losses (delayed entry misses move)
    pnls = []
    tp_hits = 0
    sl_hits = 0
    tm_hits = 0
    flipped = 0

    for i, t in enumerate(trades):
        et = t['exit_type']

        if et == 'tp':
            # TP exit: reduce win by slippage
            pnl = TRADE * (TP_BASE - tp_reduction) - TRADE * entry_slip
            # flip_pct: delayed entry causes some TPs to become time exits
            if flip_pct > 0 and (i % int(1/flip_pct)) == 0:
                pnl = TRADE * TM_BASE - TRADE * entry_slip
                flipped += 1
                tm_hits += 1
            else:
                tp_hits += 1
        elif et == 'stop':
            # SL exit: loss is worse due to slippage
            pnl = TRADE * (SL_BASE - sl_increase) - TRADE * entry_slip
            sl_hits += 1
        else:
            # Time exit
            pnl = TRADE * TM_BASE - TRADE * entry_slip
            tm_hits += 1

        pnls.append(pnl)

    arr = np.array(pnls)
    wins   = arr[arr > 0]
    losses = arr[arr < 0]
    n = len(arr)
    wr  = round(len(wins)/n*100, 1)
    pf  = round(sum(wins) / max(abs(sum(losses)), 0.01), 2)
    annual = round(sum(arr))
    monthly = round(annual/12)
    ev = round(np.mean(arr), 2)

    status = 'STRONG' if pf >= 1.1 else 'FRAGILE'
    flag   = '✓' if pf >= 1.1 else '✗'

    print(f'{flag} {label}')
    print(f'   PF={pf}  WR={wr}%  EV/trade=${ev}  Annual=${annual:,}  Monthly=${monthly:,}  [{status}]')
    if flipped > 0:
        print(f'   ({flipped} wins flipped to time exits from delayed entry)')
    return pf

print('='*65)
print('BOOF 21.0 — SLIPPAGE STRESS TEST | +35% TP / -18% SL / $200/trade')
print('='*65)

# 1. Baseline
print('\n--- BASELINE ---')
simulate(raw_trades, 'Baseline (no slippage)')

# 2. +1 tick worse fills (~0.05% per side for mid-cap stocks)
print('\n--- +1 TICK WORSE FILLS (0.05% entry slip) ---')
simulate(raw_trades, '+1 tick entry slippage (0.05%)', entry_slip=0.0005)

# 3. Realistic spread (0.1% round trip — wider spread stocks like COIN/NVDA)
print('\n--- REALISTIC SPREAD (0.1% entry slip) ---')
simulate(raw_trades, 'Realistic spread (0.1%)', entry_slip=0.001)

# 4. Worse exits: TP fills 2% lower, SL fills 2% worse
print('\n--- WORSE EXITS (TP -2%, SL -2% worse) ---')
simulate(raw_trades, 'Worse exits: TP-2% / SL-2% worse',
         tp_reduction=0.02, sl_increase=0.02)

# 5. Delayed entry: 10% of wins miss the move and become time exits
print('\n--- DELAYED ENTRY (10% of wins become time exits) ---')
simulate(raw_trades, 'Delayed entry: 10% TPs become time exits', flip_pct=0.10)

# 6. Combined worst case: all slippage at once
print('\n--- COMBINED WORST CASE ---')
simulate(raw_trades, 'All slippage combined (0.1% + TP-2% + SL-2% + 10% delayed)',
         tp_reduction=0.02, sl_increase=0.02, entry_slip=0.001, flip_pct=0.10)

# 7. Extreme stress: 20% delayed + 0.2% slip + TP-5% + SL-5%
print('\n--- EXTREME STRESS ---')
simulate(raw_trades, 'Extreme: 0.2% slip + TP-5% + SL-5% + 20% delayed',
         tp_reduction=0.05, sl_increase=0.05, entry_slip=0.002, flip_pct=0.20)

print()
print('='*65)
print('PF >= 1.1 = STRONG  |  PF < 1.1 = FRAGILE')
print('='*65)
