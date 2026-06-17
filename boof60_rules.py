"""
BOOF60 Rule Experiments
Testing fundamentally different rules to improve signal quality:

Rule A: Breakout confirmation — price must stay above PDH for 2 consecutive bars
Rule B: Volume surge proxy — only take signals where gap is >3% (strong conviction gap)
Rule C: Trailing stop — exit if option drops X% from peak (lock in gains)
Rule D: Early exit — if trade is flat after 15 bars, close it (don't hold 60)
Rule E: SPY alignment — only take longs when SPY is also up on the day
Rule F: Stacked gaps — gap >2% AND previous day was also up (momentum continuation)
Rule G: Combine best rules
"""
import pickle
import pandas as pd
import numpy as np
import pytz
import os
from itertools import product

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_6mo.parquet"
BUDGET = 750.0
PKL    = "boof60_v2_paths.pkl"

with open(PKL, 'rb') as f:
    raw_trades = pickle.load(f)

# Base filter: longs only, gap>2%, entry <=10:00
base = [t for t in raw_trades
        if t['signal'] == 'BOOF55'
        and t['gap_pct'] >= 2.0
        and t.get('entry_time','00:00') <= '10:00']
print(f"Base filter trades: {len(base)}\n")

# ── Load daily data for extra filters ────────────────────────────
def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print("Loading SPY data for alignment filter...")
spy_data = load_sym('SPY')
spy_daily = spy_data.between_time('09:30','16:00').resample('1D').agg(
    open=('open','first'), close=('close','last')).dropna()
spy_daily['spy_up'] = spy_daily['close'] > spy_daily['open']
spy_up_days = set(spy_daily[spy_daily['spy_up']].index.date)

print("Loading symbol daily data for momentum filter...")
sym_daily = {}
all_syms = list(set(t['sym'] for t in raw_trades))
for sym in all_syms:
    df = load_sym(sym)
    if df.empty: continue
    d = df.between_time('09:30','16:00').resample('1D').agg(
        open=('open','first'), close=('close','last')).dropna()
    sym_daily[sym] = d

def prev_day_up(sym, day):
    d = sym_daily.get(sym, pd.DataFrame())
    prev = d[d.index.date < day]
    if len(prev) < 1: return None
    last = prev.iloc[-1]
    return last['close'] > last['open']

print("Data loaded.\n")

# ── Simulation function ────────────────────────────────────────────
def sim(trades, tp, sl, trail_pct=None, flat_exit_bars=None, label=""):
    results = []
    for t in trades:
        pnl = None; exit_type = 'TIMEOUT'
        peak_mfe = 0.0
        for b in t['bars']:
            mfe = b['mfe_opt'] / 2.0 * 3.0   # 3x mult
            mae = b['mae_opt'] / 2.0 * 3.0
            cur = b['opt_pct'] / 2.0 * 3.0
            peak_mfe = max(peak_mfe, mfe)

            if mfe >= tp:  pnl = BUDGET*tp/100;  exit_type='TP'; break
            if mae <= sl:  pnl = BUDGET*sl/100;  exit_type='SL'; break

            # Trailing stop: if peak then dropped X% from peak
            if trail_pct and peak_mfe > 0:
                drop_from_peak = peak_mfe - cur
                if drop_from_peak >= trail_pct:
                    pnl = BUDGET * cur / 100; exit_type = 'TRAIL'; break

            # Early flat exit
            if flat_exit_bars and t['bars'].index(b) >= flat_exit_bars:
                if abs(cur) < 3.0:  # still flat after N bars
                    pnl = BUDGET * cur / 100; exit_type = 'FLAT_EXIT'; break

        if pnl is None:
            last = t['bars'][-1]
            pnl  = BUDGET * (last['opt_pct']/2.0*3.0) / 100
        results.append({'pnl': pnl, 'exit': exit_type})

    df = pd.DataFrame(results)
    if df.empty: return None
    wins = df[df['pnl']>0]; losses = df[df['pnl']<=0]
    wr  = len(wins)/len(df)
    pf  = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    ev  = df['pnl'].mean()
    return {
        'label': label, 'n': len(df), 'wr': round(wr*100,1),
        'pf': round(pf,2), 'ev': round(ev,2),
        'total': round(df['pnl'].sum(),2),
        'ann': round(df['pnl'].sum()/6*12,2),
        'tp_hits': len(df[df['exit']=='TP']),
        'sl_hits': len(df[df['exit']=='SL']),
        'trail_hits': len(df[df['exit']=='TRAIL']) if 'TRAIL' in df['exit'].values else 0,
        'flat_hits': len(df[df['exit']=='FLAT_EXIT']) if 'FLAT_EXIT' in df['exit'].values else 0,
    }

def pr(r):
    if not r: print("  No trades"); return
    print(f"  n={r['n']:3d}  WR={r['wr']}%  PF={r['pf']}x  "
          f"EV=${r['ev']:.2f}  6mo=${r['total']}  ann=${r['ann']}/yr  "
          f"TP={r['tp_hits']} SL={r['sl_hits']} TRAIL={r.get('trail_hits',0)} FLAT={r.get('flat_hits',0)}")

BEST_TP = 20.0; BEST_SL = -25.0

print("="*65)
print("BASELINE (longs gap>2%, entry≤10:00, TP=20, SL=-25, 3x mult)")
print("="*65)
bl = sim(base, BEST_TP, BEST_SL, label="baseline")
pr(bl)

# ── RULE A: Tighter gap thresholds ───────────────────────────────
print("\n" + "="*65)
print("RULE A: Gap threshold sweep")
print("="*65)
for gap in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
    t = [x for x in raw_trades if x['signal']=='BOOF55'
         and x['gap_pct']>=gap and x.get('entry_time','00:00')<='10:00']
    r = sim(t, BEST_TP, BEST_SL, label=f"gap>{gap}%")
    print(f"  gap>{gap}%:  ", end=""); pr(r)

# ── RULE B: Trailing stop ─────────────────────────────────────────
print("\n" + "="*65)
print("RULE B: Trailing stop (lock in gains from peak)")
print("="*65)
for trail in [5, 8, 10, 15, 20]:
    r = sim(base, BEST_TP, BEST_SL, trail_pct=trail, label=f"trail{trail}%")
    print(f"  Trail -{trail}% from peak:  ", end=""); pr(r)

# ── RULE C: Early flat exit ───────────────────────────────────────
print("\n" + "="*65)
print("RULE C: Early exit if flat after N bars")
print("="*65)
for bars in [10, 15, 20, 30]:
    r = sim(base, BEST_TP, BEST_SL, flat_exit_bars=bars, label=f"flat_exit_{bars}bars")
    print(f"  Flat exit after {bars} bars:  ", end=""); pr(r)

# ── RULE D: SPY up-day alignment ─────────────────────────────────
print("\n" + "="*65)
print("RULE D: SPY alignment (only trade on SPY up days)")
print("="*65)
spy_aligned = [t for t in base if t['date'] in spy_up_days]
r_spy = sim(spy_aligned, BEST_TP, BEST_SL, label="spy_up_days")
print(f"  SPY up days only:  ", end=""); pr(r_spy)

spy_down = [t for t in base if t['date'] not in spy_up_days]
r_spyd = sim(spy_down, BEST_TP, BEST_SL, label="spy_down_days")
print(f"  SPY down days only:", end=""); pr(r_spyd)

# ── RULE E: Momentum continuation (prev day also up) ─────────────
print("\n" + "="*65)
print("RULE E: Momentum continuation (prev day close > open)")
print("="*65)
mom = [t for t in base if prev_day_up(t['sym'], t['date']) == True]
anti = [t for t in base if prev_day_up(t['sym'], t['date']) == False]
r_mom  = sim(mom,  BEST_TP, BEST_SL, label="prev_day_up")
r_anti = sim(anti, BEST_TP, BEST_SL, label="prev_day_down")
print(f"  Prev day UP:   ", end=""); pr(r_mom)
print(f"  Prev day DOWN: ", end=""); pr(r_anti)

# ── RULE F: Large gap filter + SPY up + prev day up ──────────────
print("\n" + "="*65)
print("RULE F: All filters combined")
print("="*65)
combos = [
    ("gap>2 + spy_up",         [t for t in base if t['date'] in spy_up_days]),
    ("gap>3 + spy_up",         [t for t in raw_trades if t['signal']=='BOOF55' and t['gap_pct']>=3.0 and t.get('entry_time','00:00')<='10:00' and t['date'] in spy_up_days]),
    ("gap>2 + prev_up",        [t for t in base if prev_day_up(t['sym'],t['date'])==True]),
    ("gap>3 + prev_up",        [t for t in raw_trades if t['signal']=='BOOF55' and t['gap_pct']>=3.0 and t.get('entry_time','00:00')<='10:00' and prev_day_up(t['sym'],t['date'])==True]),
    ("gap>2 + spy + prev_up",  [t for t in base if t['date'] in spy_up_days and prev_day_up(t['sym'],t['date'])==True]),
    ("gap>3 + spy + prev_up",  [t for t in raw_trades if t['signal']=='BOOF55' and t['gap_pct']>=3.0 and t.get('entry_time','00:00')<='10:00' and t['date'] in spy_up_days and prev_day_up(t['sym'],t['date'])==True]),
]
for label, filtered in combos:
    r = sim(filtered, BEST_TP, BEST_SL, label=label)
    print(f"  {label:<30}", end=""); pr(r)

# ── RULE G: Best combo + trailing stop sweep ─────────────────────
print("\n" + "="*65)
print("RULE G: Best filter + trailing stop optimization")
print("="*65)
best_combo = [t for t in base if t['date'] in spy_up_days and prev_day_up(t['sym'],t['date'])==True]
print(f"  Trades: {len(best_combo)}")
rows = []
for tp, sl, trail in product([15,20,25,35],[-20,-25,-35],[None,5,8,10,15]):
    r = sim(best_combo, tp, sl, trail_pct=trail)
    if r: r['tp']=tp; r['sl']=sl; r['trail']=trail; rows.append(r)
df_g = pd.DataFrame(rows).sort_values('total', ascending=False)
print("\n  Top 15 combos:")
print(df_g.head(15)[['tp','sl','trail','n','wr','pf','ev','total','ann','tp_hits']].to_string(index=False))
