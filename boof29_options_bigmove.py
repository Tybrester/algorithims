"""
BOOF 29 — Options test on 0.80%+ move bucket (same pruned watchlist)
Tests multiple move buckets and delta levels to find where options become viable
"""
import pickle, os
import pandas as pd
import numpy as np
from math import log, sqrt, exp
from scipy.stats import norm

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

def collect(all_et, ema50, move_lo, move_hi):
    sd = pd.Timestamp("2024-01-01").date()
    ed = pd.Timestamp("2026-06-09").date()
    qqq_grp  = pregroup(all_et["QQQ"], sd, ed)
    sym_grps = {sym: pregroup(all_et[sym], sd, ed) for sym in ALL_SYMBOLS if sym in all_et}
    trades = []
    for d in sorted(qqq_grp.keys()):
        qday = qqq_grp[d]
        op = qday[(qday.index.hour==9)&(qday.index.minute>=30)&(qday.index.minute<=34)]
        if len(op)==0: continue
        q5 = (op.iloc[-1]["close"]-op.iloc[0]["open"])/op.iloc[0]["open"]
        ob = qday[(qday.index.hour==9)&(qday.index.minute==30)]
        if len(ob)==0: continue
        qqq_open = ob.iloc[0]["open"]
        e50 = get_ema(ema50, d)
        if e50 is None or not (qqq_open > e50 and q5 >= 0.001): continue
        for sym, grps in sym_grps.items():
            sday = grps.get(d)
            if sday is None: continue
            so = sday[(sday.index.hour==9)&(sday.index.minute>=30)&(sday.index.minute<=34)]
            if len(so)==0: continue
            s5p = (so.iloc[-1]["close"]-so.iloc[0]["open"])/so.iloc[0]["open"]*100
            if not (move_lo <= s5p < move_hi): continue
            en = sday[(sday.index.hour==9)&(sday.index.minute==35)]
            ex = sday[(sday.index.hour==10)&(sday.index.minute==20)]
            if len(en)==0 or len(ex)==0: continue
            ep = en.iloc[0]["open"]; xp = ex.iloc[0]["open"]
            trades.append({"entry_px": ep, "exit_px": xp,
                           "stock_pnl": (xp-ep)/ep*100})
    return trades

# Options math
def bs_call(S, K, T, r, sigma):
    if T <= 0: return max(S-K, 0)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S*norm.cdf(d1) - K*exp(-r*T)*norm.cdf(d2)

def bs_delta(S, K, T, r, sigma):
    if T <= 0: return 1.0 if S > K else 0.0
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    return norm.cdf(d1)

def find_strike(S, target_delta, T, r, sigma):
    K_lo, K_hi = S*0.50, S*1.10
    for _ in range(60):
        K_mid = (K_lo+K_hi)/2
        d = bs_delta(S, K_mid, T, r, sigma)
        if abs(d-target_delta) < 0.001: return K_mid
        if d > target_delta: K_lo = K_mid
        else: K_hi = K_mid
    return K_mid

def opt_stats(trades, delta_target, IV=0.40, R=0.05, SPREAD=0.10, COMM=0.0065):
    T_in  = 355/390/252
    T_out = 310/390/252
    wins=0; tot=0.0; gross_w=0.0; gross_l=0.0; premiums=[]
    for t in trades:
        S = t["entry_px"]; S_out = t["exit_px"]
        K = find_strike(S, delta_target, T_in, R, IV)
        opt_in  = bs_call(S,     K, T_in,  R, IV)
        opt_out = bs_call(S_out, K, T_out, R, IV)
        buy  = opt_in  + SPREAD + COMM
        sell = opt_out - SPREAD - COMM
        pnl  = (sell-buy)*100
        premiums.append(buy*100)
        tot += pnl
        if pnl > 0: wins+=1; gross_w+=pnl
        else: gross_l+=abs(pnl)
    n = len(trades)
    wr  = wins/n if n else 0
    pf  = gross_w/gross_l if gross_l>0 else 0
    ev  = tot/n if n else 0
    avg_prem = sum(premiums)/len(premiums) if premiums else 0
    return dict(n=n, wr=wr, pf=pf, ev=ev, tot=tot, avg_prem=avg_prem)

def stock_stats(trades):
    pnls = [t["stock_pnl"] for t in trades]
    if not pnls: return None
    w = [p for p in pnls if p>0]; l = [p for p in pnls if p<=0]
    wr = len(w)/len(pnls)
    pf = sum(w)/abs(sum(l)) if l else 0
    ev = sum(pnls)/len(pnls)
    return dict(n=len(pnls), wr=wr, pf=pf, ev=ev, tot=sum(pnls))

# Load
print("Loading...")
all_data = {}
for sym in ["QQQ"]+ALL_SYMBOLS:
    df = load(sym)
    if df is not None: all_data[sym] = df
all_et = {sym: df.tz_convert("America/New_York") for sym,df in all_data.items()}
ema50  = build_ema50(all_data["QQQ"].copy())
print(f"Loaded {len(all_data)} symbols\n")

OUT = open("boof29_options_bigmove.txt","w",encoding="utf-8")
_p = print
def print(*a,**k): _p(*a,**k); _p(*a,**k,file=OUT)

def sep(w=90): print("="*w)
def line(w=90): print("-"*w)
def hdr(t): sep(); print(f"  {t}"); sep()

# Move buckets to test
buckets = [
    ("0.50-0.60%  (baseline)", 0.50, 0.60),
    ("0.60-0.80%",             0.60, 0.80),
    ("0.80-1.00%",             0.80, 1.00),
    ("1.00-1.50%",             1.00, 1.50),
    ("1.50-2.00%",             1.50, 2.00),
    ("0.80-2.00%  (combined)", 0.80, 2.00),
]

deltas = [0.50, 0.70, 0.80, 0.90]

hdr("MOVE BUCKET vs DELTA — STOCK + OPTIONS COMPARISON (2024-2026)")
for bname, blo, bhi in buckets:
    print(f"\n  === {bname} ===")
    trades = collect(all_et, ema50, blo, bhi)
    if not trades:
        print(f"  No trades found.")
        continue
    ss = stock_stats(trades)
    print(f"  STOCK:   {ss['n']:>4} trades  WR {ss['wr']*100:.1f}%  PF {ss['pf']:.2f}  EV {ss['ev']:+.3f}%  Total {ss['tot']:+.2f}%")
    line(70)
    print(f"  {'Delta':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV $':>8} {'Total $':>9} {'Prem':>8}  Verdict")
    line(70)
    for d in deltas:
        os_ = opt_stats(trades, d)
        v = "PASS" if os_["pf"]>=1.3 and os_["ev"]>0 else ("EDGE" if os_["tot"]>0 else "FAIL")
        print(f"  {d:.2f}d  {os_['n']:>7} {os_['wr']*100:>5.1f}% {os_['pf']:>6.2f} {os_['ev']:>+7.2f} {os_['tot']:>+9.2f}  ${os_['avg_prem']:>6.0f}  {v}")

sep()
OUT.flush(); OUT.close()
_p("\nDone -> boof29_options_bigmove.txt")
