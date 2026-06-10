"""
Cooldown Comparison Backtest — Boof 21 / 22 / 23
6 months (Dec 2025 – May 2026) using cached + Alpaca data
Compares: RAW vs WITH 2-loss 10-min cooldown per symbol
"""
import sys, pickle
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')

import backtest_boof21 as b21
import backtest_boof22 as b22
import backtest_boof23 as b23
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

b23.CLUSTER_COMPLETION = False
b23.LOW_VOL_FILTER     = False

# ── Config ────────────────────────────────────────────────────────
COOLDOWN_LOSSES = 2    # SL hits before cooldown
COOLDOWN_MINS   = 10   # minutes to pause

SYMS_B21 = ['QQQ', 'SPY']
SYMS_B22 = ['NVDA','AAPL','META','MSFT','AMZN','GOOGL','AVGO','TSLA','LLY']
SYMS_B23 = ['NVDA','AAPL','META','MSFT','AMZN','GOOGL','AVGO','TSLA','LLY']

B21_SIZE  = 250
B22_EXP   = 200; B22_CORE = 600
B23_EXP   = 200; B23_CORE = 600

MONTHS = [
    ('Dec 25', datetime(2025,12,1),  datetime(2025,12,31), 23),
    ('Jan 26', datetime(2026,1,1),   datetime(2026,1,31),  23),
    ('Feb 26', datetime(2026,2,1),   datetime(2026,2,28),  20),
    ('Mar 26', datetime(2026,3,1),   datetime(2026,3,31),  21),
    ('Apr 26', datetime(2026,4,1),   datetime(2026,4,30),  22),
    ('May 26', datetime(2026,5,1),   datetime(2026,5,28),  20),
]

SEP  = '=' * 72
SEP2 = '-' * 72

# ── Load caches ───────────────────────────────────────────────────
print('Loading caches...')
cache_2025 = pickle.load(open('_boof22_cache.pkl',    'rb'))
cache_2026 = pickle.load(open('_boof_2026_cache.pkl', 'rb'))
print('  Done.\n')

creds = get_alpaca_credentials()

def get_df(sym, label, start, end):
    # Try 2026 cache first, then 2025 cache, then Alpaca
    df = cache_2026.get((sym, label)) or cache_2025.get((sym, label))
    if df is not None and len(df) >= 100:
        return df
    df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
    return df

# ── Cooldown filter ───────────────────────────────────────────────
def apply_cooldown(trades):
    """
    Apply per-symbol 2-loss cooldown.
    trades must be sorted by entry_bar (sequential within a symbol's session).
    Returns filtered trade list and count of filtered trades.
    """
    # Group by symbol+month, sort within each group by entry_bar
    # Then apply cooldown state across the full sorted list
    trades_out   = []
    filtered_cnt = 0
    sym_losses   = defaultdict(int)        # symbol -> consecutive SL count
    sym_cooldown = defaultdict(lambda: None)  # symbol -> cooldown expiry bar index

    # We need wall-clock time — use entry_bar as proxy within each symbol's session
    # Since trades are per-symbol per month, sort globally by (month_idx, sym, entry_bar)
    for t in trades:
        sym = t['symbol']
        et  = t['exit_type']

        # Check cooldown (using actual cooldown_until_bar stored on t)
        cooldown_bar = sym_cooldown[sym]
        if cooldown_bar is not None and t['entry_bar'] < cooldown_bar:
            filtered_cnt += 1
            continue

        trades_out.append(t)

        if et == 'sl':
            sym_losses[sym] += 1
            if sym_losses[sym] >= COOLDOWN_LOSSES:
                # Cooldown: pause for COOLDOWN_MINS bars (1 bar = 1 min)
                sym_cooldown[sym] = t['entry_bar'] + t.get('hold_bars', 1) + COOLDOWN_MINS
                sym_losses[sym]   = 0
        else:
            sym_losses[sym] = 0  # win resets counter

    return trades_out, filtered_cnt

# ── Run all three bots ────────────────────────────────────────────
def run_bot(name, syms, run_fn, size_fn):
    print(f'Running {name}...')
    all_raw = []

    for label, start, end, tdays in MONTHS:
        for sym in syms:
            df = get_df(sym, label, start, end)
            if df is None or len(df) < 100:
                continue
            trades = run_fn(df, symbol=sym)
            for t in trades:
                t['symbol']    = sym
                t['month']     = label
                t['tdays']     = tdays
                t['size']      = size_fn(t)
                t['pnl_dollar']= t['pnl_pct'] * t['size']
                t['hold_bars'] = t.get('trade_end', t['entry_bar']) - t['entry_bar']
            all_raw.extend(trades)

    # Sort by entry_bar within each symbol+month for cooldown simulation
    all_raw.sort(key=lambda t: (t['month'], t['symbol'], t['entry_bar']))
    all_cooled, filtered = apply_cooldown(all_raw)

    return all_raw, all_cooled, filtered

def b21_size(t): return B21_SIZE
def b22_size(t): return B22_CORE if t.get('tier') == 'core' else B22_EXP
def b23_size(t): return B23_CORE if t.get('tier') == 'core' else B23_EXP

# Boof21 wrapper: normalize keys to match b22/b23 format
def b21_run(df, symbol):
    trades = b21.backtest(df, symbol)
    out = []
    for i, t in enumerate(trades):
        et = t['exit_type']  # 'stop', 'tp', 'time'
        pnl_pct = B21_SIZE * (0.35 if et=='tp' else -0.10 if et=='stop' else 0.08) / B21_SIZE
        out.append({
            'symbol':    symbol,
            'direction': t['direction'],
            'exit_type': 'sl' if et=='stop' else et,
            'pnl_pct':   pnl_pct,
            'tier':      'core',
            'entry_bar': i,  # use sequential index as proxy
            'hold_bars': t.get('hold_min', 1),
        })
    return out

raw21, cool21, filt21 = run_bot('Boof 21', SYMS_B21, b21_run, b21_size)
raw22, cool22, filt22 = run_bot('Boof 22', SYMS_B22, b22.run_boof22, b22_size)
raw23, cool23, filt23 = run_bot('Boof 23', SYMS_B23, b23.run_boof23, b23_size)

# ── Stats ──────────────────────────────────────────────────────────
def stats(trades):
    if not trades: return dict(n=0,wr=0,ev=0,pf=0,tot=0)
    p    = np.array([t['pnl_dollar'] for t in trades])
    pos  = p[p>0]; neg = p[p<0]
    wr   = len(pos)/len(p)*100
    pf   = float(sum(pos)/max(abs(sum(neg)),0.01))
    return dict(n=len(p), wr=round(wr,1), ev=round(float(np.mean(p)),2),
                pf=round(pf,2), tot=round(float(sum(p)),0))

def print_comparison(name, raw, cooled, filtered):
    sr = stats(raw);   sc = stats(cooled)
    tdays = sum(set(t['tdays'] for t in raw)) if raw else 1
    print(f'\n{SEP}')
    print(f'  {name}')
    print(f'{SEP}')
    print(f'  {"Metric":<22}  {"RAW":>12}  {"+ COOLDOWN":>12}  {"Delta":>10}')
    print(f'  {SEP2[:66]}')
    print(f'  {"Trades":<22}  {sr["n"]:>12,}  {sc["n"]:>12,}  {sc["n"]-sr["n"]:>+10,}')
    print(f'  {"Win Rate":<22}  {sr["wr"]:>11.1f}%  {sc["wr"]:>11.1f}%  {sc["wr"]-sr["wr"]:>+9.1f}%')
    print(f'  {"EV / trade":<22}  ${sr["ev"]:>11.2f}  ${sc["ev"]:>11.2f}  ${sc["ev"]-sr["ev"]:>+9.2f}')
    print(f'  {"Profit Factor":<22}  {sr["pf"]:>12.2f}  {sc["pf"]:>12.2f}  {sc["pf"]-sr["pf"]:>+10.2f}')
    print(f'  {"6-month P&L":<22}  ${sr["tot"]:>11,.0f}  ${sc["tot"]:>11,.0f}  ${sc["tot"]-sr["tot"]:>+9,.0f}')
    ann_r = sr["tot"]*2; ann_c = sc["tot"]*2
    print(f'  {"Annualized est":<22}  ${ann_r:>11,.0f}  ${ann_c:>11,.0f}  ${ann_c-ann_r:>+9,.0f}')
    print(f'  {"Trades filtered":<22}  {"—":>12}  {filtered:>12,}  ({filtered/max(sr["n"],1)*100:.1f}%)')

    # Monthly breakdown
    print(f'\n  Monthly P&L (RAW vs COOLDOWN):')
    print(f'  {"Month":<10}  {"RAW P&L":>12}  {"COOL P&L":>12}  {"Delta":>10}')
    print(f'  {"-"*48}')
    for label,_,_,_ in MONTHS:
        r_mo = [t for t in raw    if t['month']==label]
        c_mo = [t for t in cooled if t['month']==label]
        r_pnl = sum(t['pnl_dollar'] for t in r_mo)
        c_pnl = sum(t['pnl_dollar'] for t in c_mo)
        flag = ' ◄ saved' if c_pnl > r_pnl else ''
        print(f'  {label:<10}  ${r_pnl:>11,.0f}  ${c_pnl:>11,.0f}  ${c_pnl-r_pnl:>+9,.0f}{flag}')

print_comparison('BOOF 21  (QQQ + SPY)',          raw21, cool21, filt21)
print_comparison('BOOF 22  (9 symbols)',           raw22, cool22, filt22)
print_comparison('BOOF 23  (9 symbols)',           raw23, cool23, filt23)

# Combined
all_raw   = raw21 + raw22 + raw23
all_cool  = cool21 + cool22 + cool23
all_filt  = filt21 + filt22 + filt23
print_comparison('COMBINED (all three bots)',      all_raw, all_cool, all_filt)

print(f'\n{SEP}')
print('  DONE')
print(SEP)
