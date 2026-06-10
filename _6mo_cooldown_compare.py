"""
6-Month Backtest: Boof 21 / 22 / 23
TP=+0.10% underlying  SL=-0.05% underlying
Compare RAW vs 2-loss 10-min cooldown per symbol
Data: Alpaca 1-min bars
"""
import sys, time
import numpy as np
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')

import backtest_boof21 as b21
import backtest_boof22 as b22
import backtest_boof23 as b23
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

# ── Strategy config ────────────────────────────────────────────────
b23.CLUSTER_COMPLETION = False
b23.LOW_VOL_FILTER     = False

TP_PCT  =  0.001   # +0.10% underlying TP
SL_PCT  =  0.0005  # -0.05% underlying SL

# Option P&L mapping (fixed model)
OPT_TP  =  0.35    # +35% option premium on TP
OPT_SL  = -0.10    # -10% option premium on SL
OPT_TM  =  0.0     # time exit = flat

B21_SIZE  = 250
B22_EXP   = 200;  B22_CORE = 600
B23_EXP   = 200;  B23_CORE = 600

SYMS_B21 = ['QQQ', 'SPY']
SYMS_B22 = ['NVDA','AAPL','META','MSFT','AMZN','GOOGL','AVGO','TSLA','LLY']
SYMS_B23 = ['NVDA','AAPL','META','MSFT','AMZN','GOOGL','AVGO','TSLA','LLY']

MONTHS = [
    ('Dec 25', datetime(2025,12,1),  datetime(2025,12,31), 23),
    ('Jan 26', datetime(2026,1,1),   datetime(2026,1,31),  23),
    ('Feb 26', datetime(2026,2,1),   datetime(2026,2,28),  20),
    ('Mar 26', datetime(2026,3,1),   datetime(2026,3,31),  21),
    ('Apr 26', datetime(2026,4,1),   datetime(2026,4,30),  22),
    ('May 26', datetime(2026,5,1),   datetime(2026,5,28),  20),
]

COOLDOWN_LOSSES = 2
COOLDOWN_MINS   = 10
SEP  = '=' * 72
SEP2 = '-' * 72

creds = get_alpaca_credentials()

# ── Data cache ─────────────────────────────────────────────────────
_data_cache = {}
def get_df(sym, label, start, end):
    key = (sym, label)
    if key not in _data_cache:
        print(f'    Fetching {sym} {label}...', end=' ', flush=True)
        df = fetch_alpaca_bars(sym, start, end, '1Min', creds['api_key'], creds['secret_key'])
        _data_cache[key] = df
        n = len(df) if df is not None else 0
        print(f'{n} bars')
        time.sleep(0.15)  # rate limit
    return _data_cache[key]

# ── Cooldown filter ────────────────────────────────────────────────
def apply_cooldown(trades):
    out = []
    filtered = 0
    sym_losses   = defaultdict(int)
    sym_cd_until = {}   # symbol -> (month, bar) cooldown end

    for t in trades:
        sym   = t['symbol']
        mo    = t['month']
        eb    = t['entry_bar']
        et    = t['exit_type']
        hb    = t.get('hold_bars', 1)

        cd = sym_cd_until.get(sym)
        if cd and cd[0] == mo and eb < cd[1]:
            filtered += 1
            continue

        out.append(t)

        if et == 'sl':
            sym_losses[sym] += 1
            if sym_losses[sym] >= COOLDOWN_LOSSES:
                sym_cd_until[sym] = (mo, eb + hb + COOLDOWN_MINS)
                sym_losses[sym]   = 0
        else:
            sym_losses[sym] = 0

    return out, filtered

# ── Run one bot ────────────────────────────────────────────────────
def run_bot(name, syms, run_fn, size_fn):
    print(f'\n--- {name} ---')
    all_trades = []

    for label, start, end, tdays in MONTHS:
        for sym in syms:
            df = get_df(sym, label, start, end)
            if df is None or len(df) < 200:
                continue
            raw = run_fn(df, sym)
            for t in raw:
                t['month']      = label
                t['tdays']      = tdays
                t['size']       = size_fn(t)
                t['pnl_dollar'] = t['pnl_pct'] * t['size']
            all_trades.extend(raw)

    all_trades.sort(key=lambda t: (t['month'], t['symbol'], t['entry_bar']))
    cooled, filtered = apply_cooldown(all_trades)
    return all_trades, cooled, filtered

# ── Boof 21 wrapper ────────────────────────────────────────────────
def b21_run(df, symbol):
    trades = b21.backtest(df, symbol)
    out = []
    for i, t in enumerate(trades):
        et = t['exit_type']  # 'stop','tp','time'
        pnl_pct = OPT_TP if et == 'tp' else OPT_SL if et == 'stop' else OPT_TM
        out.append({
            'symbol':    symbol,
            'exit_type': 'sl' if et == 'stop' else et,
            'pnl_pct':   pnl_pct,
            'tier':      'core',
            'entry_bar': i,
            'hold_bars': t.get('hold_min', 1),
        })
    return out

def b21_size(t): return B21_SIZE

# ── Boof 22 wrapper ────────────────────────────────────────────────
def b22_run(df, symbol):
    trades = b22.run_boof22(df, symbol=symbol, tp_pct=TP_PCT, sl_pct=SL_PCT)
    for t in trades:
        et = t['exit_type']
        t['pnl_pct']   = OPT_TP if et == 'tp' else OPT_SL if et == 'sl' else OPT_TM
        t['entry_bar'] = t.get('bar', 0)
        t['hold_bars'] = 1
    return trades

def b22_size(t): return B22_CORE if t.get('tier') == 'core' else B22_EXP

# ── Boof 23 wrapper ────────────────────────────────────────────────
def b23_run(df, symbol):
    trades = b23.run_boof23(df, symbol=symbol)
    for t in trades:
        et = t['exit_type']
        t['pnl_pct']   = OPT_TP if et == 'tp' else OPT_SL if et == 'sl' else OPT_TM
        t['entry_bar'] = t.get('entry_bar', 0)
        t['hold_bars'] = t.get('exit_bar', t['entry_bar'] + 1) - t['entry_bar']
    return trades

def b23_size(t): return B23_CORE if t.get('tier') == 'core' else B23_EXP

# ── Stats ──────────────────────────────────────────────────────────
def stats(trades):
    if not trades: return dict(n=0, wr=0, ev=0, pf=0, tot=0)
    p   = np.array([t['pnl_dollar'] for t in trades])
    pos = p[p > 0]; neg = p[p < 0]
    wr  = len(pos) / len(p) * 100
    pf  = float(sum(pos) / max(abs(sum(neg)), 0.01))
    return dict(n=len(p), wr=round(wr,1), ev=round(float(np.mean(p)),2),
                pf=round(pf,2), tot=round(float(sum(p)),0))

# ── Print comparison ───────────────────────────────────────────────
def print_comparison(name, raw, cooled, filtered):
    sr = stats(raw); sc = stats(cooled)
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
    ann_r = sr["tot"] * 2; ann_c = sc["tot"] * 2
    print(f'  {"Annualized est":<22}  ${ann_r:>11,.0f}  ${ann_c:>11,.0f}  ${ann_c-ann_r:>+9,.0f}')
    print(f'  {"Trades filtered":<22}  {"—":>12}  {filtered:>12,}  ({filtered/max(sr["n"],1)*100:.1f}%)')

    print(f'\n  Monthly P&L (RAW vs COOLDOWN):')
    print(f'  {"Month":<10}  {"RAW P&L":>12}  {"COOL P&L":>12}  {"Delta":>10}')
    print(f'  {"-"*50}')
    for label,_,_,_ in MONTHS:
        r_pnl = sum(t['pnl_dollar'] for t in raw    if t['month'] == label)
        c_pnl = sum(t['pnl_dollar'] for t in cooled if t['month'] == label)
        flag  = '  ◄ saved' if c_pnl > r_pnl else ('  ◄ cost' if c_pnl < r_pnl - 50 else '')
        print(f'  {label:<10}  ${r_pnl:>11,.0f}  ${c_pnl:>11,.0f}  ${c_pnl-r_pnl:>+9,.0f}{flag}')

# ── Main ───────────────────────────────────────────────────────────
print(f'\n{SEP}')
print(f'  6-MONTH BACKTEST  Dec 2025 – May 2026')
print(f'  TP=+0.10% / SL=-0.05% underlying  |  Cooldown: {COOLDOWN_LOSSES} SL → {COOLDOWN_MINS}min')
print(SEP)

raw21, cool21, filt21 = run_bot('Boof 21 (QQQ+SPY)',      SYMS_B21, b21_run, b21_size)
raw22, cool22, filt22 = run_bot('Boof 22 (9 symbols)',     SYMS_B22, b22_run, b22_size)
raw23, cool23, filt23 = run_bot('Boof 23 (9 symbols)',     SYMS_B23, b23_run, b23_size)

print_comparison('BOOF 21  (QQQ + SPY,  $250/trade)',  raw21, cool21, filt21)
print_comparison('BOOF 22  (9 syms, tiered $200/$600)',raw22, cool22, filt22)
print_comparison('BOOF 23  (9 syms, tiered $200/$600)',raw23, cool23, filt23)

all_raw  = raw21 + raw22 + raw23
all_cool = cool21 + cool22 + cool23
all_filt = filt21 + filt22 + filt23
print_comparison('ALL THREE BOTS COMBINED',            all_raw, all_cool, all_filt)

print(f'\n{SEP}')
print('  DONE')
print(SEP)
