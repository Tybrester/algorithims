"""BOOF55 — 55A 1H reclaim, gap-up days, per year per symbol."""
import pandas as pd, numpy as np, pytz
ET = pytz.timezone("America/New_York")

SYMBOLS = ["APP","NVDA","CRWD","HOOD","AMD","PLTR","COIN","TSLA"]
PERIODS = ["2022","2023","2024","2025_26"]
TP,SL,MAXB = 0.010,0.005,90
TOUCH,BRK,RET = 0.0025,0.003,0.0025

def gap_up_dates(df):
    gd=set(); dates=sorted(df.index.normalize().unique())
    for i in range(1,len(dates)):
        prev=df[df.index.normalize()==dates[i-1]]
        curr=df[df.index.normalize()==dates[i]]
        if prev.empty or curr.empty: continue
        if (curr['open'].iloc[0]-prev['close'].iloc[-1])/prev['close'].iloc[-1]>=0.001:
            gd.add(dates[i])
    return gd

def run_sm(df, gap_days):
    close=df['close'].values; lo=df['low'].values; hi=df['high'].values
    op=df['open'].values; lvls=df['hi60'].values
    dates=df.index.normalize(); n=len(df)
    trades=[]; cur_date=None; state='IDLE'; fired=False; skip_to=0
    for i in range(n):
        d=dates[i]
        if d!=cur_date:
            cur_date=d; state='IDLE'; fired=False; skip_to=0
            if d not in gap_days: skip_to=i+999999
        if i<skip_to or fired: continue
        lvl=lvls[i]
        if np.isnan(lvl) or lvl<=0: continue
        dist=(close[i]-lvl)/lvl
        if state=='IDLE':
            if abs(dist)<=TOUCH: state='TOUCH'
        elif state=='TOUCH':
            if dist>BRK: state='BREAK'
            elif abs(dist)>TOUCH*4: state='IDLE'
        elif state=='BREAK':
            if abs(dist)<=RET: state='RETEST'
        elif state=='RETEST':
            if dist>RET:
                ei=i+1
                if ei<n:
                    entry=op[ei]; tp_p=entry*(1+TP); sl_p=entry*(1-SL)
                    result='TIME'; pnl=0; bars=MAXB
                    for j in range(ei,min(ei+MAXB,n)):
                        if lo[j]<=sl_p: result='SL'; pnl=-SL; bars=j-ei; break
                        if hi[j]>=tp_p: result='TP'; pnl=TP; bars=j-ei; break
                    else: pnl=(close[min(ei+MAXB,n-1)]-entry)/entry
                    trades.append({'result':result,'pnl':pnl,'bars':bars})
                    fired=True; skip_to=ei+bars
                state='IDLE'
            elif abs(dist)>RET*4: state='IDLE'
    return trades

# collect results[sym][period] = trades list
results = {sym: {} for sym in SYMBOLS}
days_map = {sym: {} for sym in SYMBOLS}

for sym in SYMBOLS:
    for period in PERIODS:
        path = f"cache55_years/{sym}_{period}.parquet"
        df = pd.read_parquet(path).tz_convert(ET)
        df = df.between_time("09:30","16:00").copy()
        df['hi60'] = df['high'].rolling(60).max().shift(1)
        gd = gap_up_dates(df)
        days = df.index.normalize().nunique()
        days_map[sym][period] = days
        results[sym][period] = run_sm(df, gd)

# ── print ──────────────────────────────────────────────────────────────────────
PLABELS = {"2022":"2022","2023":"2023","2024":"2024","2025_26":"25-26"}

def fmt(trades, days):
    if not trades: return f"{'--':>28}"
    d=pd.DataFrame(trades); n=len(d)
    w=(d.result=='TP').sum(); l=(d.result=='SL').sum()
    wr=w/n; pf=(w*TP)/(l*SL) if l else 999
    ev=d.pnl.mean(); weeks=days/5
    return f"n={n:>3} {n/weeks:>4.1f}/wk {wr*100:>4.0f}% PF={pf:>4.2f} EV={ev*100:>+5.2f}%"

print(f"\nBOOF55 — 55A 1H Reclaim, Gap-Up Days Only  |  TP=1%  SL=0.5%")
print(f"{'='*105}")

for period in PERIODS:
    lbl = PLABELS[period]
    print(f"\n── {lbl} {'─'*95}")
    print(f"  {'Sym':<6}  {'N':>4}  {'T/wk':>5}  {'WR':>6}  {'PF':>5}  {'EV':>8}  {'W':>3}  {'L':>3}  {'T':>3}")
    print(f"  {'-'*55}")
    period_trades = []
    total_days = 0
    for sym in SYMBOLS:
        t = results[sym][period]
        days = days_map[sym][period]
        total_days = max(total_days, days)
        weeks = days/5
        period_trades += t
        if not t:
            print(f"  {sym:<6}  {'0':>4}"); continue
        d=pd.DataFrame(t); n=len(d)
        w=int((d.result=='TP').sum()); l=int((d.result=='SL').sum()); ti=int((d.result=='TIME').sum())
        wr=w/n; pf=(w*TP)/(l*SL) if l else 999; ev=d.pnl.mean()
        flag=' ✅' if ev>0.001 and wr>=0.38 else (' ❌' if ev<0 else ' ~')
        print(f"  {sym:<6}  {n:>4}  {n/weeks:>5.2f}  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+7.3f}%  {w:>3}  {l:>3}  {ti:>3}{flag}")
    # period total
    if period_trades:
        d=pd.DataFrame(period_trades); n=len(d)
        w=int((d.result=='TP').sum()); l=int((d.result=='SL').sum()); ti=int((d.result=='TIME').sum())
        wr=w/n; pf=(w*TP)/(l*SL) if l else 999; ev=d.pnl.mean(); weeks=total_days/5
        print(f"  {'─'*55}")
        print(f"  {'TOT':<6}  {n:>4}  {n/weeks:>5.2f}  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+7.3f}%  {w:>3}  {l:>3}  {ti:>3}")

# cross-year summary per symbol
print(f"\n\n── ALL YEARS COMBINED per symbol {'─'*65}")
print(f"  {'Sym':<6}  {'N':>4}  {'T/wk':>5}  {'WR':>6}  {'PF':>5}  {'EV':>8}  {'W':>3}  {'L':>3}  {'T':>3}")
print(f"  {'-'*55}")
all_trades = []
for sym in SYMBOLS:
    t = [tr for p in PERIODS for tr in results[sym][p]]
    all_trades += t
    total_days = sum(days_map[sym][p] for p in PERIODS)
    weeks = total_days/5
    if not t: print(f"  {sym:<6}  0"); continue
    d=pd.DataFrame(t); n=len(d)
    w=int((d.result=='TP').sum()); l=int((d.result=='SL').sum()); ti=int((d.result=='TIME').sum())
    wr=w/n; pf=(w*TP)/(l*SL) if l else 999; ev=d.pnl.mean()
    flag=' ✅' if ev>0.001 and wr>=0.38 else (' ❌' if ev<0 else ' ~')
    print(f"  {sym:<6}  {n:>4}  {n/weeks:>5.2f}  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+7.3f}%  {w:>3}  {l:>3}  {ti:>3}{flag}")
d=pd.DataFrame(all_trades); n=len(d)
w=int((d.result=='TP').sum()); l=int((d.result=='SL').sum()); ti=int((d.result=='TIME').sum())
wr=w/n; pf=(w*TP)/(l*SL); ev=d.pnl.mean()
total_weeks = max(sum(days_map[sym][p] for p in PERIODS) for sym in SYMBOLS)/5
print(f"  {'─'*55}")
print(f"  {'TOTAL':<6}  {n:>4}  {n/total_weeks:>5.2f}  {wr*100:>5.1f}%  {pf:>5.2f}  {ev*100:>+7.3f}%  {w:>3}  {l:>3}  {ti:>3}")
