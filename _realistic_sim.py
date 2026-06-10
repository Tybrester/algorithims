"""
Realistic Market Simulation — Boof 21 & 22
Step 1: Bid/Ask spread model (entry=ask, exit=bid, dynamic spread 0.05%-0.2%)
Step 2: Random fill delay (0-1 bar, small miss probability)
Step 3: Intra-bar randomness (when both TP+SL possible in same bar, coin flip)
"""
import pickle, sys, random
import numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import run_boof22, compute_atr

random.seed(42)
np.random.seed(42)

TRADE    = 200
TP21     = 0.35
SL21     = -0.18
TM21     = 0.08
ATR_TP   = 4.0
ATR_SL   = 2.0
TM22     = 0.08
MAX_HOLD = 30

SYM21 = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
SYM22 = ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

MONTHS_25 = ['Dec 25']
MONTHS_26 = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26']

print('Loading caches...')
cache25 = pickle.load(open('_boof21_cache.pkl','rb'))
cache22 = pickle.load(open('_boof22_cache.pkl','rb'))
cache26 = pickle.load(open('_boof_2026_cache.pkl','rb'))

def get21(sym, mo): return cache25.get((sym, mo)) if '25' in mo else cache26.get((sym, mo))
def get22(sym, mo):
    if '25' in mo: return cache22.get((sym, mo[:3]))  # 'Dec 25' -> 'Dec'
    return cache26.get((sym, mo))

# ── Dynamic spread: uniform between min and max based on vol proxy ──
def dynamic_spread(atr, price, min_sp=0.0005, max_sp=0.002):
    vol_ratio = min(atr / price, 0.01) / 0.01  # normalize: high ATR = wide spread
    return min_sp + (max_sp - min_sp) * vol_ratio

# ══════════════════════════════════════════════════════════════════
# BOOF 21 — signal collection with full bar data
# ══════════════════════════════════════════════════════════════════
print('Collecting Boof 21 signals...')
sigs21 = []
all_months = MONTHS_25 + MONTHS_26
for mo in all_months:
    for sym in SYM21:
        df = get21(sym, mo)
        if df is None or len(df) < 100: continue
        if 'atr' not in df.columns:
            df = df.copy()
            from backtest_boof21 import compute_atr as compute_atr21
            df['atr'] = compute_atr21(df)
        trades = bt21.backtest(df, symbol=sym)
        for t in trades:
            entry_time = t.get('entry_time')
            if entry_time is None: continue
            locs = df.index.get_indexer([entry_time], method='nearest')
            ei = locs[0]
            if ei < 0 or ei >= len(df) - 2: continue
            atr = float(df['atr'].iloc[ei])
            if np.isnan(atr) or atr == 0: continue
            ep = float(t['entry'])
            d  = t['direction']
            # grab highs AND lows for intra-bar analysis
            highs  = df['high'].iloc[ei+1 : ei+MAX_HOLD+2].values
            lows   = df['low'].iloc[ei+1 : ei+MAX_HOLD+2].values
            closes = df['close'].iloc[ei+1 : ei+MAX_HOLD+2].values
            if len(closes) == 0: continue
            sigs21.append({'entry': ep, 'atr': atr, 'direction': d,
                           'highs': highs, 'lows': lows, 'closes': closes,
                           'hold_min': t['hold_min'], 'sym': sym, 'mo': mo,
                           'orig_exit': t['exit_type']})

# ══════════════════════════════════════════════════════════════════
# BOOF 22 — signal collection with full bar data
# ══════════════════════════════════════════════════════════════════
print('Collecting Boof 22 signals...')
sigs22 = []
for mo in all_months:
    for sym in SYM22:
        df = get22(sym, mo)
        if df is None or len(df) < 100: continue
        if 'atr' not in df.columns:
            df = df.copy(); df['atr'] = compute_atr(df)
        trades = run_boof22(df, symbol=sym, tp_pct=0.99, sl_pct=0.99)
        for t in trades:
            bar_i = t.get('bar')
            if bar_i is None: continue
            atr = float(df['atr'].iloc[bar_i]) if bar_i < len(df) else 0
            if not atr or np.isnan(atr): continue
            ep = float(t['entry']); d = t['direction']
            highs  = df['high'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            lows   = df['low'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            closes = df['close'].iloc[bar_i+1 : bar_i+MAX_HOLD+2].values
            if len(closes) == 0: continue
            sigs22.append({'entry': ep, 'atr': atr, 'direction': d,
                           'highs': highs, 'lows': lows, 'closes': closes,
                           'sym': sym, 'mo': mo})

print(f'Boof 21 signals: {len(sigs21)}')
print(f'Boof 22 signals: {len(sigs22)}\n')

# ══════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ══════════════════════════════════════════════════════════════════
def sim21(signals, use_spread=False, use_delay=False, use_intrabar=False, label=''):
    pnls = []
    for s in signals:
        ep_raw = s['entry']; atr = s['atr']; d = s['direction']
        highs  = s['highs']; lows = s['lows']; closes = s['closes']

        spread = dynamic_spread(atr, ep_raw) if use_spread else 0.0

        # Step 1: entry = ask (pay spread on entry)
        ep = ep_raw * (1 + spread) if d == 'LONG' else ep_raw * (1 - spread)

        tp_price = ep * (1 + TP21)
        sl_price = ep * (1 + SL21)

        # Step 2: random fill delay (0 or 1 bar skip)
        start = 0
        if use_delay:
            if random.random() < 0.3:   # 30% chance of 1-bar delay
                start = 1
            if random.random() < 0.05:  # 5% chance of full miss → time exit
                pnls.append(TRADE * TM21 - ep_raw * spread * TRADE / ep_raw)
                continue

        et = 'time'
        exit_px = closes[-1] if len(closes) > 0 else ep

        for i in range(start, len(closes)):
            hi = highs[i]; lo = lows[i]; cl = closes[i]

            tp_hit = (d == 'LONG' and hi >= tp_price) or (d == 'SHORT' and lo <= tp_price)
            sl_hit = (d == 'LONG' and lo <= sl_price) or (d == 'SHORT' and hi >= sl_price)

            # Step 3: intra-bar — both hit in same bar → coin flip
            if tp_hit and sl_hit and use_intrabar:
                if random.random() < 0.5:
                    sl_hit = False
                else:
                    tp_hit = False

            if tp_hit:
                et = 'tp'
                exit_px = tp_price * (1 - spread) if d == 'LONG' else tp_price * (1 + spread)
                break
            if sl_hit:
                et = 'sl'
                exit_px = sl_price * (1 - spread) if d == 'LONG' else sl_price * (1 + spread)
                break

        if et == 'tp':
            pnl = TRADE * abs(exit_px - ep) / ep
        elif et == 'sl':
            pnl = -TRADE * abs(exit_px - ep) / ep
        else:
            pnl = TRADE * TM21 - ep_raw * spread * TRADE / ep_raw

        pnls.append(pnl)
    return np.array(pnls)


def sim22(signals, use_spread=False, use_delay=False, use_intrabar=False, label=''):
    pnls = []
    for s in signals:
        ep_raw = s['entry']; atr = s['atr']; d = s['direction']
        highs  = s['highs']; lows = s['lows']; closes = s['closes']

        spread = dynamic_spread(atr, ep_raw) if use_spread else 0.0

        ep = ep_raw * (1 + spread) if d == 'long' else ep_raw * (1 - spread)

        tp_p = ep + atr * ATR_TP if d == 'long' else ep - atr * ATR_TP
        sl_p = ep - atr * ATR_SL if d == 'long' else ep + atr * ATR_SL

        start = 0
        if use_delay:
            if random.random() < 0.3:
                start = 1
            if random.random() < 0.05:
                pnls.append(TRADE * TM22 - ep_raw * spread * TRADE / ep_raw)
                continue

        et = 'time'
        exit_px = closes[-1] if len(closes) > 0 else ep

        for i in range(start, len(closes)):
            hi = highs[i]; lo = lows[i]

            tp_hit = (d == 'long' and hi >= tp_p) or (d == 'short' and lo <= tp_p)
            sl_hit = (d == 'long' and lo <= sl_p) or (d == 'short' and hi >= sl_p)

            if tp_hit and sl_hit and use_intrabar:
                if random.random() < 0.5:
                    sl_hit = False
                else:
                    tp_hit = False

            if tp_hit:
                et = 'tp'
                exit_px = tp_p * (1 - spread) if d == 'long' else tp_p * (1 + spread)
                break
            if sl_hit:
                et = 'sl'
                exit_px = sl_p * (1 - spread) if d == 'long' else sl_p * (1 + spread)
                break

        if et == 'tp':
            pnl = TRADE * abs(exit_px - ep) / ep
        elif et == 'sl':
            pnl = -TRADE * abs(exit_px - ep) / ep
        else:
            pnl = TRADE * TM22 - ep_raw * spread * TRADE / ep_raw

        pnls.append(pnl)
    return np.array(pnls)


def print_stats(arr21, arr22, label):
    print(f'\n{"═"*70}')
    print(f' {label}')
    print(f'{"═"*70}')

    for name, arr in [('Boof 21', arr21), ('Boof 22', arr22)]:
        n     = len(arr)
        wins  = arr[arr > 0]; losses = arr[arr < 0]
        wr    = round(len(wins)/n*100, 1)
        pf    = round(float(sum(wins)/max(abs(sum(losses)),0.01)), 2)
        ev    = round(float(np.mean(arr)), 2)
        total = round(float(sum(arr)))
        sharpe= round((np.mean(arr)/np.std(arr,ddof=1))*np.sqrt(n),2) if np.std(arr,ddof=1)>0 else 0
        cum   = np.cumsum(arr); peak = np.maximum.accumulate(cum)
        dd    = round(float((peak-cum).max()))
        avg_w = round(float(np.mean(wins)),2) if len(wins) else 0
        avg_l = round(float(np.mean(losses)),2) if len(losses) else 0
        status = '✓ STRONG' if pf >= 1.5 else '~ OK' if pf >= 1.1 else '✗ FRAGILE'
        print(f'\n  {name}  {status}')
        print(f'    WR: {wr}%  |  PF: {pf}  |  EV: ${ev}  |  Total: ${total:,}')
        print(f'    Avg Win: ${avg_w}  |  Avg Loss: ${avg_l}  |  Sharpe: {sharpe}  |  MaxDD: ${dd:,}')


# ══════════════════════════════════════════════════════════════════
# RUN ALL SCENARIOS
# ══════════════════════════════════════════════════════════════════

# Baseline (close-based, no friction)
a21_base = sim21(sigs21)
a22_base = sim22(sigs22)
print_stats(a21_base, a22_base, '🟢 BASELINE — close-based, no friction')

# Step 1 only: Bid/Ask spread
a21_s1 = sim21(sigs21, use_spread=True)
a22_s1 = sim22(sigs22, use_spread=True)
print_stats(a21_s1, a22_s1, '🔵 STEP 1 — Bid/Ask spread (entry=ask, exit=bid, dynamic 0.05%–0.2%)')

# Step 1+2: Spread + random fill delay
a21_s2 = sim21(sigs21, use_spread=True, use_delay=True)
a22_s2 = sim22(sigs22, use_spread=True, use_delay=True)
print_stats(a21_s2, a22_s2, '🟡 STEP 2 — Spread + random fill delay (30% 1-bar lag, 5% full miss)')

# Step 1+2+3: Full realistic sim
a21_s3 = sim21(sigs21, use_spread=True, use_delay=True, use_intrabar=True)
a22_s3 = sim22(sigs22, use_spread=True, use_delay=True, use_intrabar=True)
print_stats(a21_s3, a22_s3, '🟠 STEP 3 — Full sim: spread + delay + intra-bar TP/SL coin flip')

# ══════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════
print(f'\n{"═"*70}')
print(' SUMMARY TABLE')
print(f'{"═"*70}')
print(f'  {"Scenario":<42} {"B21 PF":>7} {"B21 $":>9} {"B22 PF":>7} {"B22 $":>9}')
print(f'  {"-"*66}')

scenarios = [
    ('🟢 Baseline',              a21_base, a22_base),
    ('🔵 S1: Bid/Ask spread',    a21_s1,   a22_s1),
    ('🟡 S2: + fill delay',      a21_s2,   a22_s2),
    ('🟠 S3: + intra-bar rand',  a21_s3,   a22_s3),
]
for lbl, a21, a22 in scenarios:
    def pf(arr):
        w=arr[arr>0]; l=arr[arr<0]
        return round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    p21=pf(a21); p22=pf(a22)
    t21=round(float(sum(a21))); t22=round(float(sum(a22)))
    st21 = '✓' if p21>=1.5 else '~' if p21>=1.1 else '✗'
    st22 = '✓' if p22>=1.5 else '~' if p22>=1.1 else '✗'
    print(f'  {lbl:<42} {st21}{p21:>6} ${t21:>8,} {st22}{p22:>6} ${t22:>8,}')
print(f'{"═"*70}')
