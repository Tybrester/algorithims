"""
BOOF 29 — Core Sectors Only: Semiconductors + Fintech + Industrials
3-year backtest (2024 / 2025 / 2026)
"""
import pickle, os, sys
import pandas as pd
import numpy as np

CACHE_KEY = "2024-01-01_2026-12-31"

SECTORS = {
    "Semiconductors": [
        "NVDA","AVGO","TSM","ASML","MU","AMAT","KLAC","LRCX",
        "ADI","QCOM","NXPI","ON","MPWR","MRVL","INTC","ARM",
        "TER","SWKS","QRVO","GFS","WOLF","COHR","LSCC","AEHR",
        "ACLS","FORM","CRUS","SYNA","SMTC","AMKR","RMBS","UCTT",
        "ENTG","CEVA","ICHR","VECO","ONTO","SIMO","HIMX",
        "PI","IPGP","DIOD","POWI","MTSI","AOSL",
    ],
    "Fintech": [
        "HOOD","COIN","SOFI","AFRM","UPST","SQ","FI","PYPL",
        "NU","BILL","TOST","PAYO","MA","V","AXP","SCHW",
        "MS","GS","JPM","BAC","WFC","BX","BLK",
        "SPGI","MCO","CME","ICE","AJG","PGR","TRV","MMC",
        "AMP","RJF","STT","NTRS",
    ],
    "Industrials": [
        "CAT","PH","TT","URI","DE","ROP","PWR",
        "AME","HUBB","XYL","DOV","GWW","FAST","ODFL",
        "UNP","NSC","CSX","PCAR","ROK","JCI","IR",
        "CARR","GE","RTX","LMT","NOC","GD","TDG",
        "HEI","EXPD","CHRW","ITW","EMR","HON",
    ],
    "Mega-cap Tech": [
        "AAPL","MSFT","META","GOOGL","AMZN","TSLA","NFLX",
        "ORCL","CRM","ADBE","NOW","INTU","IBM","CSCO",
    ],
}

SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS   = list(dict.fromkeys(s for syms in SECTORS.values() for s in syms))

def load(sym):
    f = f"boof_cache/{sym}_{CACHE_KEY}.pkl"
    return pickle.load(open(f,"rb")) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.groupby(qqq.index.date)["close"].last()
    d.index = pd.to_datetime(d.index)
    return d.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v  = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if d.date() < date]
        v = s[prior[-1]] if prior else None
    return v

def pregroup(df_et, sd, ed):
    sub = df_et[(df_et.index.date >= sd) & (df_et.index.date <= ed)]
    return {d: g for d, g in sub.groupby(sub.index.date)}

def collect(all_et, ema50, start, end):
    s_et = start.tz_convert("America/New_York")
    e_et = end.tz_convert("America/New_York")
    sd = s_et.date(); ed = e_et.date()
    qqq_grp  = pregroup(all_et["QQQ"], sd, ed)
    sym_grps = {sym: pregroup(all_et[sym], sd, ed) for sym in ALL_SYMBOLS if sym in all_et}
    trades = []; active_days = 0
    for d in sorted(qqq_grp.keys()):
        qday = qqq_grp[d]
        op = qday[(qday.index.hour==9)&(qday.index.minute>=30)&(qday.index.minute<=34)]
        if len(op)==0: continue
        q5 = (op.iloc[-1]["close"]-op.iloc[0]["open"])/op.iloc[0]["open"]
        ob = qday[(qday.index.hour==9)&(qday.index.minute==30)]
        if len(ob)==0: continue
        qqq_open = ob.iloc[0]["open"]
        e50 = get_ema(ema50, d)
        if e50 is None: continue
        if not (qqq_open > e50 and q5 >= 0.001): continue
        dhit = False
        for sym, grps in sym_grps.items():
            sday = grps.get(d)
            if sday is None: continue
            so = sday[(sday.index.hour==9)&(sday.index.minute>=30)&(sday.index.minute<=34)]
            if len(so)==0: continue
            s5p = (so.iloc[-1]["close"]-so.iloc[0]["open"])/so.iloc[0]["open"]*100
            if not (0.50 <= s5p < 0.60): continue
            en = sday[(sday.index.hour==9)&(sday.index.minute==35)]
            ex = sday[(sday.index.hour==10)&(sday.index.minute==20)]
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]["open"]; xp = ex.iloc[0]["open"]
            ts2 = pd.Timestamp(d)
            trades.append({
                "date":    d,
                "symbol":  sym,
                "sector":  SYM_TO_SECTOR.get(sym, "?"),
                "pnl":     (xp-ep)/ep*100,
                "month":   ts2.to_period("M"),
                "year":    ts2.year,
            })
            dhit = True
        if dhit: active_days += 1
    return trades, active_days

def st(rows_or_df):
    df = pd.DataFrame(rows_or_df) if isinstance(rows_or_df, list) else rows_or_df
    if len(df)==0: return None
    w = df[df["pnl"]>0]; l = df[df["pnl"]<=0]
    wr = len(w)/len(df)
    aw = w["pnl"].mean() if len(w) else 0
    al = abs(l["pnl"].mean()) if len(l) else 0
    ev = wr*aw-(1-wr)*al
    pf = w["pnl"].sum()/abs(l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 0
    tot = df["pnl"].sum(); cum = df["pnl"].cumsum()
    dd  = (cum.expanding().max()-cum).max()
    return dict(n=len(df), wr=wr, aw=aw, al=al, ev=ev, pf=pf, tot=tot, dd=dd, df=df)

OUT = open("boof29_4sector.txt", "w", encoding="utf-8")
_p = print
def print(*a, **k):
    _p(*a, **k); _p(*a, **k, file=OUT)

def sep(w=90): print("="*w)
def line(w=90): print("-"*w)
def hdr(t): sep(); print(f"  {t}"); sep()

# ── Load ─────────────────────────────────────────────────────────────
print("Loading...")
all_data = {}
for sym in ["QQQ"] + ALL_SYMBOLS:
    df = load(sym)
    if df is not None: all_data[sym] = df
all_et  = {sym: df.tz_convert("America/New_York") for sym, df in all_data.items()}
ema50   = build_ema50(all_data["QQQ"].copy())
print(f"Loaded {len(all_data)} symbols ({len(ALL_SYMBOLS)} in universe)\n")

def ts(s): return pd.to_datetime(s).tz_localize("UTC")
periods = {
    "2024": (ts("2024-01-01"), ts("2024-12-31")),
    "2025": (ts("2025-01-01"), ts("2025-12-31")),
    "2026": (ts("2026-01-01"), ts("2026-06-09")),
}

print("Collecting trades...")
yt = {}; ya = {}
for yr, (s, e) in periods.items():
    print(f"  {yr}...", flush=True)
    t, a = collect(all_et, ema50, s, e)
    yt[yr] = t; ya[yr] = a
    print(f"    {len(t)} trades / {a} active days")

all_t = yt["2024"] + yt["2025"] + yt["2026"]
df    = pd.DataFrame(all_t)
tot_a = sum(ya.values())
print(f"Total {len(all_t)} trades\n")

# ════════════════════════════════════════════════════════════════════
hdr("BOOF 29 -- Semis + Fintech + Industrials + Mega-cap Tech (-AMD -KKR -ALAB -MCHP -ETN) | 0.50-0.60% | 9:35->10:20")
print(f"  {'Period':<10} {'Trades':>8} {'T/Day':>7} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'MaxDD':>8} {'Total':>9}  Verdict")
line()
for yr in ["2024", "2025", "2026"]:
    s = st(yt[yr]); a = ya[yr]
    if not s: continue
    tpd = s["n"]/a if a>0 else 0
    v = "PASS" if s["pf"]>=1.3 else ("EDGE" if s["pf"]>=1.0 else "FAIL")
    print(f"  {yr:<10} {s['n']:>8} {tpd:>7.2f} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% -{s['dd']:>6.2f}% {s['tot']:>+8.2f}%  {v}")
line()
s = st(all_t); tpd = s["n"]/tot_a
v = "PASS" if s["pf"]>=1.3 else ("EDGE" if s["pf"]>=1.0 else "FAIL")
print(f"  {'COMBINED':<10} {s['n']:>8} {tpd:>7.2f} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% -{s['dd']:>6.2f}% {s['tot']:>+8.2f}%  {v}")
sep()

# ════════════════════════════════════════════════════════════════════
hdr("SECTOR BREAKDOWN")
print(f"  {'Sector':<22} {'Trades':>8} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'Total':>9}  Verdict")
line()
for sec in SECTORS:
    sub = df[df["sector"]==sec]; s = st(sub)
    if not s: continue
    v = "PASS" if s["pf"]>=1.3 else ("EDGE" if s["pf"]>=1.0 else "FAIL")
    print(f"  {sec:<22} {s['n']:>8} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% {s['tot']:>+8.2f}%  {v}")
sep()

# ════════════════════════════════════════════════════════════════════
hdr("TOP 20 SYMBOLS")
sym_rows = []
for sym, grp in df.groupby("symbol"):
    w = grp[grp["pnl"]>0]; l = grp[grp["pnl"]<=0]
    pf = w["pnl"].sum()/abs(l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 0
    sym_rows.append({"sym":sym,"sec":SYM_TO_SECTOR.get(sym,"?"),"n":len(grp),
                     "wr":len(w)/len(grp)*100,"pf":pf,
                     "ev":grp["pnl"].mean(),"total":grp["pnl"].sum()})
sdf = pd.DataFrame(sym_rows).sort_values("total", ascending=False)

print(f"  {'Symbol':>8} {'Sector':<16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'Total':>9}")
line()
for _, r in sdf.head(20).iterrows():
    print(f"  {r['sym']:>8} {r['sec']:<16} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['ev']:>+9.3f}% {r['total']:>+8.2f}%")
sep()

# ════════════════════════════════════════════════════════════════════
hdr("BOTTOM 20 SYMBOLS")
print(f"  {'Symbol':>8} {'Sector':<16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'Total':>9}")
line()
for _, r in sdf.tail(20).iloc[::-1].iterrows():
    print(f"  {r['sym']:>8} {r['sec']:<16} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['ev']:>+9.3f}% {r['total']:>+8.2f}%")
sep()

# ════════════════════════════════════════════════════════════════════
hdr("MONTHLY BREAKDOWN")
print(f"  {'Month':<10} {'Trades':>8} {'T/Day':>7} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'Total':>9}  {'Cum':>9}")
line()
tdays_pm = df.groupby("month")["date"].nunique()
cum2 = 0
for m in sorted(df["month"].unique()):
    mdf = df[df["month"]==m]; s = st(mdf)
    if not s: continue
    cum2 += s["tot"]
    tpd = s["n"] / tdays_pm.get(m, 1)
    flag = "  RED" if s["tot"]<0 else ""
    print(f"  {str(m):<10} {s['n']:>8} {tpd:>7.2f} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% {s['tot']:>+8.2f}%  {cum2:>+8.2f}%{flag}")
sep()

# ════════════════════════════════════════════════════════════════════
hdr("MONTHLY BY YEAR")
for yr in ["2024", "2025", "2026"]:
    ydf = df[df["year"]==int(yr)]
    if len(ydf)==0: continue
    print(f"\n  --- {yr} ---")
    print(f"  {'Month':<10} {'Trades':>8} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'Total':>9}")
    line(60)
    for m in sorted(ydf["month"].unique()):
        mdf = ydf[ydf["month"]==m]; s = st(mdf)
        if not s: continue
        flag = "  RED" if s["tot"]<0 else ""
        print(f"  {str(m):<10} {s['n']:>8} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% {s['tot']:>+8.2f}%{flag}")
sep()

OUT.flush(); OUT.close()
_p("\nDone -> boof29_4sector.txt")
