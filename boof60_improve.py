"""
BOOF60 Improvement Tests — 4 targeted experiments using cached paths
Test 1: Tighter gap filter (gap >2% longs only)
Test 2: Regime hard block (no shorts in bull, no longs in bear)
Test 3: Longs only, tight gap >2%, best TP/SL
Test 4: RVOL filter — only take trades where volume is above average (proxy: gap size as vol proxy)
Test 5: Time-of-day filter — only enter 09:30-11:00 (morning momentum window)
Test 6: Combine best of all above
"""
import pandas as pd
import numpy as np
import pytz
import os
import pickle
from itertools import product

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_6mo.parquet"

SYMBOLS_LONG = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]
ROUTING = {
    "UPST":("PMH",None,None),"APP":("PMH",None,None),"SMCI":("PMH",None,None),
    "HIMS":("PMH",None,None),"GOOGL":("PMH",None,None),"META":("PDH",None,None),
    "AFRM":("PDH",None,None),"TSLA":("PIV",10,2),"CLSK":("PIV",10,2),
    "HOOD":("PIV",10,2),"ADBE":("PIV",30,3),"PANW":("PIV",30,3),
    "MU":("PIV",30,3),"AMD":("PIV",30,3),"COIN":("PIV",30,3),"NVDA":("PIV",30,3),
    "MRVL":("PIV",120,4),"AVGO":("PIV",120,4),"PLTR":("PIV",240,5),"CRM":("PIV",390,5),
}
SHORT_SYMS = list(ROUTING.keys())
ALL_SYMS   = list(set(SYMBOLS_LONG + SHORT_SYMS))

GAP_LONG=1.0; GAP_SHORT=0.5; NEAR_PCT=0.0015; BOUNCE=0.0015; OVERLAP=0.002
MAX_BARS=60; BUDGET=750.0; MAX_POS=5; OPTION_MULT=2.0
BEST_TP=12.0; BEST_SL=-25.0

PKL = "boof60_v2_paths.pkl"

def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

def build_pivots(bars, lookback, wing):
    hist = bars[-lookback:] if len(bars)>=lookback else bars
    if len(hist)<wing+1: return []
    H=[b['h'] for b in hist]
    raw=[H[i] for i in range(wing,len(hist)) if H[i]==max(H[max(0,i-wing):i+1])]
    if not raw: return []
    raw=sorted(raw); cl=[raw[0]]
    for lv in raw[1:]:
        if abs(lv-cl[-1])/cl[-1]<OVERLAP: cl[-1]=(cl[-1]+lv)/2
        else: cl.append(lv)
    return cl

def init_sm(): return {'state':'IDLE','extreme':None,'touch_num':0,'was_below':False,'broken':False}

def update_level_sm(sm, level, bar):
    high=bar['h']; close=bar['c']
    if close<level: sm['was_below']=True
    touching=sm['was_below'] and high>=level*(1-NEAR_PCT)
    if sm['state']=='IDLE':
        if touching: sm['state']='IN'; sm['extreme']=close; sm['touch_num']+=1
    elif sm['state']=='IN':
        if high>=level*(1-NEAR_PCT): sm['extreme']=min(sm['extreme'],close)
        else:
            bounced=sm['extreme'] is not None and (level-sm['extreme'])/level>=BOUNCE
            req=2 if sm['broken'] else 1
            if bounced and sm['touch_num']==req: sm['state']='FIRED'; return True
            sm['state']='DEAD'; sm['broken']=True; sm['was_below']=False
    elif sm['state']=='DEAD':
        if sm['was_below']: sm['state']='IDLE'; sm['extreme']=None; sm['touch_num']=0
    return False

# ── Load or build raw paths ───────────────────────────────────────
if os.path.exists(PKL):
    print(f"Loading cached paths...")
    with open(PKL,'rb') as f: raw_trades = pickle.load(f)
    print(f"  {len(raw_trades)} paths\n")
else:
    print("ERROR: run boof60_v2_optimize.py first to build the path cache")
    exit()

# Also need full trade metadata for filters — rebuild with extra fields
# We need: entry_time (hm), gap_pct, regime, signal already in raw_trades
# Check if we have entry_time
sample = raw_trades[0]
has_entry_hm = 'entry_time' in sample
print(f"Path fields: {list(sample.keys())}")
print(f"Sample entry_time: {sample.get('entry_time','MISSING')}\n")

def sim(trades, tp, sl, label=""):
    results=[]
    for t in trades:
        pnl=None; exit_type='TIMEOUT'
        for b in t['bars']:
            if b['mfe_opt']>=tp:  pnl=BUDGET*tp/100;  exit_type='TP'; break
            if b['mae_opt']<=sl:  pnl=BUDGET*sl/100;  exit_type='SL'; break
        if pnl is None:
            last=t['bars'][-1]; pnl=BUDGET*last['opt_pct']/100
        results.append({'pnl':pnl,'exit':exit_type,'signal':t.get('signal',''),'regime':t.get('regime','')})
    df=pd.DataFrame(results)
    if df.empty: return None
    wins=df[df['pnl']>0]; losses=df[df['pnl']<=0]
    wr  = len(wins)/len(df)
    pf  = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    ev  = df['pnl'].mean(); tot=df['pnl'].sum()
    tp_n= len(df[df['exit']=='TP']); sl_n=len(df[df['exit']=='SL'])
    return {'label':label,'n':len(df),'wr':round(wr*100,1),'pf':round(pf,2),
            'ev':round(ev,2),'total':round(tot,2),'tp_hits':tp_n,'sl_hits':sl_n}

def print_result(r):
    if not r: print("  No trades"); return
    print(f"  n={r['n']:4d}  WR={r['wr']}%  PF={r['pf']}x  EV=${r['ev']}  "
          f"Total=${r['total']}  TP={r['tp_hits']}  SL={r['sl_hits']}")

results_all = []

# ── BASELINE ─────────────────────────────────────────────────────
print("="*60)
print("BASELINE (all trades, TP=12, SL=-25)")
print("="*60)
base = sim(raw_trades, BEST_TP, BEST_SL, "baseline")
print_result(base)
results_all.append(base)

# ── TEST 1: Tighter gap filters ───────────────────────────────────
print("\n" + "="*60)
print("TEST 1: Gap filter on longs (>1% vs >1.5% vs >2% vs >3%)")
print("="*60)
for gap_min in [1.0, 1.5, 2.0, 3.0]:
    filtered = [t for t in raw_trades if
                not (t['signal']=='BOOF55' and t['gap_pct'] < gap_min)]
    r = sim(filtered, BEST_TP, BEST_SL, f"gap>{gap_min}%")
    print(f"  Long gap >{gap_min}%  ", end=""); print_result(r)
    results_all.append(r)

# ── TEST 2: Regime block ──────────────────────────────────────────
print("\n" + "="*60)
print("TEST 2: Regime hard blocks")
print("="*60)
# No shorts in bull
t2a = [t for t in raw_trades if not (t['signal']=='BOOF51' and t['regime']=='bull')]
r2a = sim(t2a, BEST_TP, BEST_SL, "no_short_in_bull")
print(f"  No shorts in bull:      ", end=""); print_result(r2a)
results_all.append(r2a)

# No longs in bear
t2b = [t for t in raw_trades if not (t['signal']=='BOOF55' and t['regime']=='bear')]
r2b = sim(t2b, BEST_TP, BEST_SL, "no_long_in_bear")
print(f"  No longs in bear:       ", end=""); print_result(r2b)
results_all.append(r2b)

# Both combined
t2c = [t for t in raw_trades if not
       ((t['signal']=='BOOF51' and t['regime']=='bull') or
        (t['signal']=='BOOF55' and t['regime']=='bear'))]
r2c = sim(t2c, BEST_TP, BEST_SL, "regime_aligned_only")
print(f"  Regime-aligned only:    ", end=""); print_result(r2c)
results_all.append(r2c)

# Neutral only (skip both bull and bear entries)
t2d = [t for t in raw_trades if t['regime']=='neutral']
r2d = sim(t2d, BEST_TP, BEST_SL, "neutral_regime_only")
print(f"  Neutral regime only:    ", end=""); print_result(r2d)
results_all.append(r2d)

# ── TEST 3: Longs only ────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 3: Longs only (BOOF55) with various gap filters")
print("="*60)
for gap_min in [1.0, 1.5, 2.0, 2.5, 3.0]:
    filtered = [t for t in raw_trades if t['signal']=='BOOF55' and t['gap_pct']>=gap_min]
    r = sim(filtered, BEST_TP, BEST_SL, f"longs_gap>{gap_min}%")
    print(f"  Longs only gap>{gap_min}%:  ", end=""); print_result(r)
    results_all.append(r)

# ── TEST 4: Time of day filter ────────────────────────────────────
print("\n" + "="*60)
print("TEST 4: Entry time windows")
print("="*60)
windows = [
    ("09:30-10:00", "09:30", "10:00"),
    ("09:30-10:30", "09:30", "10:30"),
    ("09:30-11:00", "09:30", "11:00"),
    ("09:30-12:00", "09:30", "12:00"),
    ("10:00-12:00", "10:00", "12:00"),
    ("after_10:30", "10:30", "15:30"),
]
for label, start, end in windows:
    filtered = [t for t in raw_trades if
                t.get('entry_time','00:00') >= start and
                t.get('entry_time','00:00') <= end]
    r = sim(filtered, BEST_TP, BEST_SL, label)
    print(f"  Entry {label}:  ", end=""); print_result(r)
    results_all.append(r)

# ── TEST 5: Longs-only sweep with tighter TP/SL ──────────────────
print("\n" + "="*60)
print("TEST 5: Longs-only (gap>2%) TP/SL sweep")
print("="*60)
longs_2pct = [t for t in raw_trades if t['signal']=='BOOF55' and t['gap_pct']>=2.0]
print(f"  {len(longs_2pct)} long trades with gap >2%")
best_l = None
for tp, sl in product([5,8,10,12,15,20],[-5,-8,-10,-12,-15,-20,-25]):
    r = sim(longs_2pct, tp, sl)
    if r and (best_l is None or r['total'] > best_l['total']):
        best_l = r; best_l['tp']=tp; best_l['sl']=sl
print(f"  Best TP/SL for longs gap>2%: TP={best_l['tp']} SL={best_l['sl']}")
print(f"  ", end=""); print_result(best_l)

# Full longs>2% sweep top 10
longs_sweep = []
for tp, sl in product([5,8,10,12,15,20],[-5,-8,-10,-12,-15,-20,-25]):
    r = sim(longs_2pct, tp, sl, f"TP{tp}_SL{sl}")
    if r: r['tp']=tp; r['sl']=sl; longs_sweep.append(r)
ls_df = pd.DataFrame(longs_sweep).sort_values('total',ascending=False)
print("\n  Top 10 combos for longs gap>2%:")
print(ls_df.head(10)[['tp','sl','n','wr','pf','ev','total','tp_hits']].to_string(index=False))

# ── TEST 6: Best combined ─────────────────────────────────────────
print("\n" + "="*60)
print("TEST 6: Best combined — regime-aligned + gap>2% longs + entry <11:00")
print("="*60)
combined = [t for t in raw_trades if
    not ((t['signal']=='BOOF51' and t['regime']=='bull') or
         (t['signal']=='BOOF55' and t['regime']=='bear')) and
    (t['signal']=='BOOF51' or t['gap_pct']>=2.0) and
    t.get('entry_time','00:00') <= '11:00']
print(f"  {len(combined)} trades after all filters")
best_c = None
for tp, sl in product([5,8,10,12,15,20],[-8,-12,-15,-20,-25]):
    r = sim(combined, tp, sl)
    if r and (best_c is None or r['total'] > best_c['total']):
        best_c = r; best_c['tp']=tp; best_c['sl']=sl
print(f"  Best TP={best_c['tp']} SL={best_c['sl']}")
print_result(best_c)

# per-month on best combined
print("\n  Monthly breakdown (best combined):")
for tp, sl in [(best_c['tp'], best_c['sl'])]:
    monthly = {}
    for t in combined:
        month = str(t['date'])[:7]
        pnl=None
        for b in t['bars']:
            if b['mfe_opt']>=tp:  pnl=BUDGET*tp/100; break
            if b['mae_opt']<=sl:  pnl=BUDGET*sl/100; break
        if pnl is None: pnl=BUDGET*t['bars'][-1]['opt_pct']/100
        if month not in monthly: monthly[month]={'pnl':0,'n':0,'wins':0}
        monthly[month]['pnl']+=pnl; monthly[month]['n']+=1
        if pnl>0: monthly[month]['wins']+=1
    for m,v in sorted(monthly.items()):
        wr=v['wins']/v['n']*100 if v['n'] else 0
        print(f"    {m}  trades={v['n']:3d}  pnl=${v['pnl']:8.2f}  wr={wr:.0f}%")

print(f"\n{'='*60}")
print("SUMMARY — Total P&L comparison")
print(f"{'='*60}")
summary = pd.DataFrame([r for r in results_all if r])
print(summary[['label','n','wr','pf','ev','total']].sort_values('total',ascending=False).to_string(index=False))
