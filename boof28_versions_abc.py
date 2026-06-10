"""
BOOF 28 - Version A/B/C Test
A: Long only
B: Stricter short filter QQQ_5m <= -0.25%
C: Remove bad symbols + no mega-cap tech shorts
"""
import sys
OUT = open('boof28_versions_abc_results.txt', 'w', encoding='utf-8')
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SECTORS = {
    "Semiconductors": ["NVDA","AMD","AVGO","MU","AMAT","ASML","TSM","QCOM","TXN","ADI","NXPI","MCHP","ON","MPWR","LRCX","KLAC","MRVL","INTC","ARM","TER","SWKS","QRVO","GFS","COHR","WOLF"],
    "Mega-cap Tech":  ["MSFT","AAPL","META","GOOGL","GOOG","AMZN","TSLA","NFLX","ORCL","IBM","ADBE","CRM","NOW","INTU","PANW","SNOW"],
    "Fintech":        ["HOOD","COIN","SQ","FI","PYPL","SOFI","AFRM","UPST","MA","V","JPM","GS","MS","SCHW","BLK"],
    "Industrials":    ["CAT","ETN","PH","TT","DE","URI","GE","EMR","HON","ROP","ITW","FAST","PWR","CARR","JCI","IR","NOC","LMT","RTX","GD","BA","HUBB","XYL","DOV"],
    "Biotech":        ["LLY","NVO","ISRG","REGN","VRTX","ABBV","AMGN","GILD","MRNA","BMY","PFE","TMO","DHR","ABT","MDT","BSX","SYK","ZTS","IDXX","HCA","HUM","UNH","CI","CVS","ELV","MCK","COR","CAH"],
    "Energy":         ["XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","OXY","DVN","FANG","APA","HAL","BKR","KMI","WMB","LNG","EQT"],
    "Consumer":       ["COST","WMT","TGT","HD","LOW","SBUX","MCD","CMG","NKE","LULU","TJX","ROST","DG","DLTR","BBY","ULTA","YUM","KO","PEP","PM","MO","CL","PG"],
    "Travel":         ["UBER","ABNB","BKNG","EXPE","RCL","CCL","NCLH","MAR","HLT","WYNN","MGM","LVS"],
    "Communications": ["CMCSA","DIS","T","VZ","CHTR","TMUS","ROKU","SPOT","FOXA","WBD"],
    "Materials":      ["LIN","APD","SHW","ECL","FCX","NEM","DD","DOW","NUE","STLD","MLM","VMC"],
    "Utilities":      ["NEE","SO","DUK","AEP","XEL","EXC","SRE"],
}
SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS   = list(SYM_TO_SECTOR.keys())

# Version C: remove bad symbols from short side, no mega-cap tech shorts
BAD_SYMBOLS    = {"KLAC","QCOM","ADI","CRM","LRCX"}
MEGACAP_TECH   = set(SECTORS["Mega-cap Tech"])

def load_cached(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    daily = d.groupby('date')['close'].last()
    return daily.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v  = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if pd.Timestamp(d).date() < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, start, end,
            long_only=False, short_qqq_thresh=-0.001,
            ban_short_syms=None, ban_short_sectors=None):

    ban_short_syms    = ban_short_syms    or set()
    ban_short_sectors = ban_short_sectors or set()

    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    tdays  = set()

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']

        qopen_bar = qday.between_time('09:30','09:30')
        if len(qopen_bar) == 0: continue
        qqq_open = qopen_bar.iloc[0]['open']
        e50 = get_ema(ema50, d)
        if e50 is None: continue

        bull = qqq_open > e50 and q5 >= 0.001
        bear = (not long_only) and qqq_open < e50 and q5 <= short_qqq_thresh

        if not bull and not bear: continue
        tdays.add(d)

        for sym in ALL_SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue

            so = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']

            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:20','10:20')
            if len(en) == 0 or len(ex) == 0: continue
            ep = en.iloc[0]['open']
            xp = ex.iloc[0]['open']
            sec = SYM_TO_SECTOR.get(sym, 'Other')

            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                if sym in ban_short_syms: continue
                if sec in ban_short_sectors: continue
                direction = 'SHORT'
            if direction is None: continue

            pnl = (xp-ep)/ep*100 if direction=='LONG' else (ep-xp)/ep*100
            trades.append({'date':d,'symbol':sym,'sector':sec,'side':direction,'pnl':pnl,'qqq_5m':round(q5*100,3)})

    return trades, tdays

def stats(df):
    if len(df) == 0: return 0,0,0,0,0
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr   = len(wins)/len(df)*100
    avg  = df['pnl'].mean(); tot = df['pnl'].sum()
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp/gl if gl>0 else 0
    cum  = df['pnl'].cumsum()
    dd   = (cum.expanding().max()-cum).max()
    return wr, avg, tot, pf, dd

def report(trades, tdays, label, ver):
    def pr(*a,**k): print(*a,**k); print(*a,**k,file=OUT)
    if not trades:
        pr(f"\n{ver} | {label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    n  = len(df)
    wr,avg,tot,pf,dd = stats(df)
    ldf = df[df['side']=='LONG']; sdf = df[df['side']=='SHORT']
    tpd = n/len(tdays) if tdays else 0

    W = 85
    pr(f"\n{'='*W}")
    pr(f"  {ver}  |  {label}")
    pr(f"{'='*W}")
    pr(f"  {'Trades:':<20} {n}   ({tpd:.2f}/day on {len(tdays)} active days)")
    pr(f"  {'Win Rate:':<20} {wr:.1f}%")
    pr(f"  {'Avg Trade:':<20} {avg:+.3f}%")
    pr(f"  {'Profit Factor:':<20} {pf:.2f}")
    pr(f"  {'Max Drawdown:':<20} -{dd:.2f}%")
    pr(f"  {'Total Return:':<20} {tot:+.2f}%")
    pr(f"  {'-'*W}")
    pr(f"  {'':8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    pr(f"  {'-'*W}")
    for side, d in [('LONG',ldf),('SHORT',sdf)]:
        if len(d)==0: continue
        _w,_a,_t,_p,_dd = stats(d)
        pr(f"  {side:8} {len(d):>7} {_w:>5.1f}% {_p:>6.2f} {_a:>+8.3f}% {_t:>+8.2f}%")
    pr(f"  {'-'*W}")
    # Sector
    pr(f"  {'Sector':18} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    pr(f"  {'-'*W}")
    for sec in ["Semiconductors","Mega-cap Tech","Fintech","Industrials","Biotech","Travel"]:
        sub = df[df['sector']==sec]
        if len(sub)==0: continue
        _w,_a,_t,_p,_ = stats(sub)
        pr(f"  {sec:18} {len(sub):>7} {_w:>5.1f}% {_p:>6.2f} {_a:>+8.3f}% {_t:>+8.2f}%")
    pr(f"  {'='*W}")
    OUT.flush()

# ── Load ──────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load_cached(sym)
    if df is not None: all_data[sym] = df
print(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())
s25s  = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e  = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s  = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e  = pd.to_datetime('2026-06-09').tz_localize('UTC')

VERSIONS = [
    ("VERSION A — Long Only",
     dict(long_only=True, short_qqq_thresh=-0.001)),
    ("VERSION B — Stricter Short (QQQ_5m <= -0.25%)",
     dict(long_only=False, short_qqq_thresh=-0.0025)),
    ("VERSION C — No Bad Syms + No MegaCap Shorts",
     dict(long_only=False, short_qqq_thresh=-0.001,
          ban_short_syms=BAD_SYMBOLS,
          ban_short_sectors={"Mega-cap Tech"})),
    ("VERSION D — B+C Combined (Strict + Cleaned)",
     dict(long_only=False, short_qqq_thresh=-0.0025,
          ban_short_syms=BAD_SYMBOLS,
          ban_short_sectors={"Mega-cap Tech"})),
]

for label, kwargs in VERSIONS:
    print(f"Running {label}...")
    t25, d25 = collect(all_data, ema50, s25s, s25e, **kwargs)
    t26, d26 = collect(all_data, ema50, s26s, s26e, **kwargs)
    all_t    = t25 + t26
    all_d    = d25 | d26
    report(t25,   d25,   "2025 FULL YEAR",        label)
    report(t26,   d26,   "2026 YTD (Jan-Jun 9)",  label)
    report(all_t, all_d, "COMBINED",               label)

print("\nDone. Results in boof28_versions_abc_results.txt")
