import sys, os, pickle
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import run_boof22

CACHE21 = 'c:/Users/tybre/Desktop/aivibe/_boof21_cache.pkl'
CACHE22 = 'c:/Users/tybre/Desktop/aivibe/_boof22_cache.pkl'

SYMBOLS_21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
SYMBOLS_22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

months = [
    ('Jan 25', 'Jan', 23), ('Feb 25', 'Feb', 20), ('Mar 25', 'Mar', 21), ('Apr 25', 'Apr', 22),
    ('May 25', 'May', 21), ('Jun 25', 'Jun', 21), ('Jul 25', 'Jul', 23), ('Aug 25', 'Aug', 21),
    ('Sep 25', 'Sep', 22), ('Oct 25', 'Oct', 23), ('Nov 25', 'Nov', 20), ('Dec 25', 'Dec', 23),
]

TRADE_SIZE = 200
TP = 0.40   # +40% TP
SL = -0.10  # -10% SL
TM = 0.08   # time exit ~+8%

def compute_sharpe(trade_pnls, label):
    arr = np.array(trade_pnls)
    n_trades = len(arr)
    mean = np.mean(arr)
    std  = np.std(arr, ddof=1)
    # Annualized Sharpe using trades/year as scaling factor
    trades_per_year = n_trades  # already a full year
    sharpe = (mean / std) * np.sqrt(trades_per_year) if std > 0 else 0
    annual_pnl = np.sum(arr)
    monthly_pnl = annual_pnl / 12
    wins   = np.sum(arr > 0)
    losses = np.sum(arr < 0)
    wr     = round(wins / max(n_trades, 1) * 100, 1)
    pf     = round(np.sum(arr[arr>0]) / max(abs(np.sum(arr[arr<0])), 0.01), 2)
    max_dd = 0
    peak = 0
    cum = 0
    for p in arr:
        cum += p
        if cum > peak: peak = cum
        dd = peak - cum
        if dd > max_dd: max_dd = dd

    print(f'\n{"="*60}')
    print(f'{label}')
    print(f'{"="*60}')
    print(f'TP: +{int(TP*100)}%  SL: {int(SL*100)}%  Size: ${TRADE_SIZE}/trade')
    print(f'Total trades: {n_trades}  ({round(n_trades/252,1)}/day)')
    print(f'Win rate:     {wr}%  |  PF: {pf}')
    print(f'Annual P&L:   ${round(annual_pnl):,}')
    print(f'Monthly avg:  ${round(monthly_pnl):,}')
    print(f'Avg trade:    ${round(mean, 2)}  |  Std: ${round(std, 2)}')
    print(f'Max Drawdown: ${round(max_dd):,}')
    print(f'Sharpe Ratio: {sharpe:.2f}  (annualized, per-trade)')
    if sharpe >= 2.0:
        print(f'  → Excellent (institutional grade)')
    elif sharpe >= 1.5:
        print(f'  → Very Good')
    elif sharpe >= 1.0:
        print(f'  → Good')
    else:
        print(f'  → Below average (< 1.0)')
    return sharpe

# ── Boof 21 ─────────────────────────────────────────────────────────
print('Loading Boof 21 cache...')
with open(CACHE21, 'rb') as f:
    dfs21 = pickle.load(f)
print('Running Boof 21 backtest...')

trade_pnls_21 = []
for mo_label, mo_short, tdays in months:
    for sym in SYMBOLS_21:
        df = dfs21.get((sym, mo_label))
        if df is None: continue
        trades = bt21.backtest(df, symbol=sym)
        for t in trades:
            et = t['exit_type']
            if et == 'tp':     pnl = TRADE_SIZE * TP
            elif et == 'stop': pnl = TRADE_SIZE * SL
            else:              pnl = TRADE_SIZE * TM
            trade_pnls_21.append(pnl)

sharpe21 = compute_sharpe(trade_pnls_21, 'Boof 21.0 | 2025 Full Year | 11 Symbols')

# ── Boof 22 ─────────────────────────────────────────────────────────
print('\nLoading Boof 22 cache...')
if os.path.exists(CACHE22):
    with open(CACHE22, 'rb') as f:
        dfs22 = pickle.load(f)
    print('Running Boof 22 backtest...')

    trade_pnls_22 = []
    for mo_label, mo_short, tdays in months:
        for sym in SYMBOLS_22:
            df = dfs22.get((sym, mo_short))
            if df is None: continue
            trades = run_boof22(df, symbol=sym, tp_pct=TP, sl_pct=SL)
            for t in trades:
                et = t.get('exit_type', '')
                if et == 'tp':     pnl = TRADE_SIZE * TP
                elif et == 'sl':   pnl = TRADE_SIZE * SL
                else:              pnl = TRADE_SIZE * TM
                trade_pnls_22.append(pnl)

    sharpe22 = compute_sharpe(trade_pnls_22, 'Boof 22.0 | 2025 Full Year | 9 Symbols')
else:
    print('No Boof 22 cache found — skipping')

print(f'\n{"="*60}')
print(f'SUMMARY')
print(f'{"="*60}')
print(f'Boof 21 Sharpe: {sharpe21:.2f}')
if os.path.exists(CACHE22):
    print(f'Boof 22 Sharpe: {sharpe22:.2f}')
