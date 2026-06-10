import sys, importlib
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt_mod
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime
import numpy as np

creds  = get_alpaca_credentials()
TRADE_SIZE = 300
# 0DTE near-ATM option leverage (conservative):
#   TP hit   -> ~10x underlying % (delta ~0.5, gamma pop on move through level)
#   Stop hit -> -50% flat  (1-min stop = option loses ~half its value quickly)
#   Time exit-> ~4x underlying % (partial move, theta drag)
LEV_TP   = 10
LEV_TIME = 4
LOSS_SL  = 0.50

periods = [
    ('April 2026', datetime(2026,4,1),  datetime(2026,4,30),  21),
    ('March 2026', datetime(2026,3,1),  datetime(2026,3,31),  21),
]

for label, s, e, tdays in periods:
    # patch dates into live module so it uses current config
    bt_mod.START_DATE = s
    bt_mod.END_DATE   = e
    importlib.reload(bt_mod)
    all_trades = []
    for sym in ['QQQ', 'SPY']:
        df = fetch_alpaca_bars(sym, s, e, timeframe='1Min',
                               api_key=creds['api_key'], secret_key=creds['secret_key'])
        all_trades.extend(bt_mod.backtest(df, sym))

    if not all_trades:
        print(f"\n{label}: no trades"); continue

    wins  = [t for t in all_trades if t['pnl'] > 0]
    losses= [t for t in all_trades if t['pnl'] <= 0]
    tp_ct = sum(1 for t in all_trades if t['exit_type'] == 'tp')
    sl_ct = sum(1 for t in all_trades if t['exit_type'] == 'stop')
    tm_ct = sum(1 for t in all_trades if t['exit_type'] == 'time')
    pf    = sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)) if losses else 999
    wr    = len(wins) / len(all_trades) * 100

    opt_pnl = 0.0
    for t in all_trades:
        if t['exit_type'] == 'tp':
            opt_pnl += TRADE_SIZE * t['pnl'] * LEV_TP
        elif t['exit_type'] == 'stop':
            opt_pnl -= TRADE_SIZE * LOSS_SL
        else:
            opt_pnl += TRADE_SIZE * t['pnl'] * LEV_TIME

    per_day = opt_pnl / tdays
    per_trade = opt_pnl / len(all_trades)

    print(f"\n{'='*52}")
    print(f"  {label}  |  QQQ + SPY  |  10m levels / 1m entry")
    print(f"{'='*52}")
    print(f"  Trades   : {len(all_trades):>4}  ({len(all_trades)/tdays:.1f}/day)")
    print(f"  Win Rate : {wr:.1f}%   PF: {pf:.2f}")
    print(f"  Exits    : TP={tp_ct}  Stop={sl_ct}  Time={tm_ct}")
    print(f"")
    print(f"  --- ${TRADE_SIZE}/trade, 0DTE near-ATM option ---")
    print(f"  Monthly P&L : ${opt_pnl:>8,.0f}")
    print(f"  Daily avg   : ${per_day:>8,.0f} / day")
    print(f"  Per trade   : ${per_trade:>8,.0f} / trade")
