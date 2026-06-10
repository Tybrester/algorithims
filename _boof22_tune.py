import sys, os, pickle
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof22 as bt
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from datetime import datetime

TRADE   = 200
SYMBOLS = ["TSLA","NVDA","COIN","PLTR","AMD","AAPL","AMZN","META","GOOGL"]
MONTHS  = [
    ('Jan', datetime(2025,1,1), datetime(2025,1,31)),
    ('Feb', datetime(2025,2,1), datetime(2025,2,28)),
    ('Mar', datetime(2025,3,1), datetime(2025,3,31)),
]
CACHE = 'c:/Users/tybre/Desktop/aivibe/_boof22_cache.pkl'

# ── Load or fetch data ──────────────────────────────────
if os.path.exists(CACHE):
    print('Loading from cache...')
    with open(CACHE, 'rb') as f:
        dfs = pickle.load(f)
else:
    print('Fetching from Alpaca (one-time)...')
    creds = get_alpaca_credentials()
    dfs = {}
    for sym in SYMBOLS:
        for mo, s, e in MONTHS:
            dfs[(sym,mo)] = fetch_alpaca_bars(sym, s, e, '1Min', creds['api_key'], creds['secret_key'])
    with open(CACHE, 'wb') as f:
        pickle.dump(dfs, f)
print('Ready.\n')

# ── Tune function ────────────────────────────────────────
def test(atr_mult, sr_dist, sr_strength, label=''):
    bt.SR_STRENGTH_MIN = sr_strength
    for sym in bt.SYMBOL_PARAMS:
        bt.SYMBOL_PARAMS[sym]['atr_mult'] = atr_mult
        bt.SYMBOL_PARAMS[sym]['sr_dist']  = sr_dist
    total_tr=total_tp=total_sl=total_tm=0
    for sym in SYMBOLS:
        for mo,_,_ in MONTHS:
            df = dfs.get((sym,mo))
            if df is None: continue
            trades = bt.run_boof22(df, symbol=sym, tp_pct=0.008, sl_pct=-0.004)
            total_tr += len(trades)
            total_tp += sum(1 for t in trades if t['exit_type']=='tp')
            total_sl += sum(1 for t in trades if t['exit_type']=='sl')
            total_tm += sum(1 for t in trades if t['exit_type']=='time')
    pnl = total_tp*TRADE*0.35 + total_sl*TRADE*(-0.15) + total_tm*TRADE*0.08
    pf  = round((total_tp*0.35) / max(total_sl*0.15, 0.01), 2)
    tpd = round(total_tr / (3*21), 1)
    lbl = ('  <- '+label) if label else ''
    print(f'atr={atr_mult}  dist={sr_dist}  str={sr_strength}  | {str(tpd).ljust(6)}/day  PF={str(pf).ljust(5)}  ${round(pnl/3)}/mo{lbl}')

print('atr_mult  dist  strength | trades/day  PF     monthly')
print('-'*58)
test(1.4, 1.0, 2, 'current')
test(1.8, 1.0, 2)
test(2.0, 1.0, 2)
test(2.2, 0.8, 2)
test(2.5, 0.8, 3)
test(2.5, 0.6, 3)
test(3.0, 0.6, 3)
test(3.0, 0.5, 4)
