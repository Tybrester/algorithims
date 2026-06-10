"""
BOOF 29 — Advanced Validation on Pruned Watchlist
  1. Walk-Forward (train 2024-2025, test 2026)
  2. Monte Carlo (1000 sims)
  3. Options Modeling (1DTE ATM, realistic fills)
"""
import pickle, os, random
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
                "date":       d,
                "symbol":     sym,
                "sector":     SYM_TO_SECTOR.get(sym, "?"),
                "pnl":        (xp-ep)/ep*100,
                "entry_px":   ep,
                "exit_px":    xp,
                "month":      ts2.to_period("M"),
                "year":       ts2.year,
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

OUT = open("boof29_validation_delta80.txt", "w", encoding="utf-8")
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
all_et = {sym: df.tz_convert("America/New_York") for sym, df in all_data.items()}
ema50  = build_ema50(all_data["QQQ"].copy())
print(f"Loaded {len(all_data)} symbols\n")

def ts(s): return pd.to_datetime(s).tz_localize("UTC")

# Collect all periods
print("Collecting trades...")
t24, a24 = collect(all_et, ema50, ts("2024-01-01"), ts("2024-12-31"))
t25, a25 = collect(all_et, ema50, ts("2025-01-01"), ts("2025-12-31"))
t26, a26 = collect(all_et, ema50, ts("2026-01-01"), ts("2026-06-09"))
print(f"  2024: {len(t24)} trades / {a24} days")
print(f"  2025: {len(t25)} trades / {a25} days")
print(f"  2026: {len(t26)} trades / {a26} days")

t_train = t24 + t25
t_test  = t26
t_all   = t24 + t25 + t26
df_all  = pd.DataFrame(t_all)
pnl_arr = df_all["pnl"].values
print(f"  Train (2024-2025): {len(t_train)} | Test (2026): {len(t_test)}\n")

# ════════════════════════════════════════════════════════════════════
# 1. WALK-FORWARD
# ════════════════════════════════════════════════════════════════════
hdr("WALK-FORWARD TEST  |  Train: 2024+2025  |  Test: 2026 (out-of-sample)")
print(f"  {'Period':<30} {'Trades':>8} {'WR%':>6} {'PF':>6} {'EV/trade':>10} {'MaxDD':>8} {'Total':>9}  Tag")
line()
for label, t, tag in [
    ("TRAIN  2024",         t24,     "TRAIN"),
    ("TRAIN  2025",         t25,     "TRAIN"),
    ("TRAIN  COMBINED",     t_train, "TRAIN"),
    ("TEST   2026 (unseen)",t_test,  "OUT-OF-SAMPLE"),
]:
    s = st(t)
    if not s: continue
    v = "PASS" if s["pf"]>=1.3 else ("EDGE" if s["pf"]>=1.0 else "FAIL")
    print(f"  {label:<30} {s['n']:>8} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+9.3f}% -{s['dd']:>6.2f}% {s['tot']:>+8.2f}%  {v}  [{tag}]")

s_tr = st(t_train); s_te = st(t_test)
pf_decay = (s_te["pf"] - s_tr["pf"]) / s_tr["pf"] * 100
wr_decay = (s_te["wr"] - s_tr["wr"]) / s_tr["wr"] * 100
ev_decay = (s_te["ev"] - s_tr["ev"]) / abs(s_tr["ev"]) * 100 if s_tr["ev"]!=0 else 0
line()
print(f"\n  PF  decay train->test:  {pf_decay:>+.1f}%  ({'PASS' if abs(pf_decay)<30 else 'WARN — >30% decay'})")
print(f"  WR  decay train->test:  {wr_decay:>+.1f}%  ({'PASS' if abs(wr_decay)<10 else 'WARN'})")
print(f"  EV  decay train->test:  {ev_decay:>+.1f}%  ({'PASS' if ev_decay>-50 else 'WARN'})")
pass_wf = s_te["pf"]>=1.3 and s_te["ev"]>0
print(f"\n  Walk-Forward Verdict:  {'PASS -- Edge survives out-of-sample' if pass_wf else 'FAIL -- Edge does not survive OOS'}")
sep()

# ════════════════════════════════════════════════════════════════════
# 2. MONTE CARLO
# ════════════════════════════════════════════════════════════════════
hdr("MONTE CARLO SIMULATION  |  1000 runs  |  Randomized trade order")
random.seed(42)
pnl_list = pnl_arr.tolist()
N = len(pnl_list)
final_rets = []; max_dds = []; worst_streaks = []

for _ in range(1000):
    sh = random.sample(pnl_list, N)
    arr = np.array(sh)
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    final_rets.append(cum[-1])
    max_dds.append((cum - peak).min())
    # worst losing streak
    streak = 0; best_streak = 0
    for x in arr:
        if x <= 0: streak += 1; best_streak = max(best_streak, streak)
        else: streak = 0
    worst_streaks.append(best_streak)

fr = np.array(final_rets); md = np.array(max_dds); ws = np.array(worst_streaks)

print(f"  Simulations:    1000  |  Trades per sim: {N}")
print()
print(f"  {'Metric':<30} {'5th pct':>10} {'Median':>10} {'95th pct':>10}")
line(65)
print(f"  {'Final Return (%)':<30} {np.percentile(fr,5):>+9.2f}% {np.median(fr):>+9.2f}% {np.percentile(fr,95):>+9.2f}%")
print(f"  {'Max Drawdown (%)':<30} {np.percentile(md,5):>+9.2f}% {np.median(md):>+9.2f}% {np.percentile(md,95):>+9.2f}%")
print(f"  {'Worst Loss Streak':<30} {np.percentile(ws,5):>10.0f}  {np.median(ws):>9.0f}  {np.percentile(ws,95):>9.0f}")
print()
print(f"  % of sims profitable:    {(fr>0).mean()*100:.1f}%")
print(f"  % sims DD worse -15%:    {(md<-15).mean()*100:.1f}%")
print(f"  % sims DD worse -20%:    {(md<-20).mean()*100:.1f}%")
print(f"  % sims DD worse -30%:    {(md<-30).mean()*100:.1f}%")
print()

# Equity curve bar chart (median sim)
sorted_fr = sorted(range(1000), key=lambda i: abs(final_rets[i]-np.median(fr)))
med_idx   = sorted_fr[0]
random.seed(42)
sims_data = []
for i in range(1000):
    sh = random.sample(pnl_list, N)
    sims_data.append(sh)
med_path = np.cumsum(sims_data[med_idx])
scale    = max(abs(med_path.max()), abs(med_path.min()), 0.01) / 35
chk      = [int(i*(N-1)/19) for i in range(20)] + [N-1]
chk      = sorted(set(chk))
print(f"  Median-sim equity curve:")
line(70)
for i in chk:
    v   = med_path[i]
    bar = ("+" if v>=0 else "-") * max(1, int(abs(v)/scale))
    print(f"  Trade {i+1:>4}  {v:>+7.2f}%  |{bar}")
sep()

# ════════════════════════════════════════════════════════════════════
# 3. OPTIONS MODELING — 1DTE ATM CALL, REALISTIC FILLS
# ════════════════════════════════════════════════════════════════════
hdr("OPTIONS MODELING  |  1DTE 0.80-Delta Deep ITM Call  |  Realistic Fills")
print("""
  Assumptions:
    - Buy 1DTE 0.80-delta call at 9:35 open (strike solved via Black-Scholes)
    - IV assumed 40% annualized (typical for momentum names)
    - Option price modeled via Black-Scholes approximation
    - Time to expiry at entry:  ~6.5 hrs  (0.27 days)
    - Time to expiry at exit:   ~4.5 hrs  (0.19 days)  [10:20 exit]
    - Bid/ask spread:  $0.10 per contract  (wider for deep ITM)
    - Commission:      $0.65 per contract
    - Multiplier:      100 shares/contract
    - Position size:   1 contract per signal
    - Delta at entry:  ~0.80  (captures ~80% of stock move, less theta risk)
""")

from math import log, sqrt, exp
from scipy.stats import norm as scipy_norm

def bs_call(S, K, T, r, sigma):
    if T <= 0: return max(S-K, 0)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S*scipy_norm.cdf(d1) - K*exp(-r*T)*scipy_norm.cdf(d2)

IV    = 0.40        # 40% annualized IV
R     = 0.05        # risk-free rate
T_in  = 6.5/252/6.5  # ~6.5 trading hours = 0.27 trading days
T_out = 4.5/252/6.5  # ~4.5 trading hours at 10:20
SPREAD= 0.10        # wider spread for deep ITM (0.10 per side)
COMM  = 0.65        # commission per contract
MULT  = 100
TARGET_DELTA = 0.80  # deep ITM call

def bs_delta(S, K, T, r, sigma):
    if T <= 0: return 1.0 if S > K else 0.0
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    return scipy_norm.cdf(d1)

def find_strike_for_delta(S, target_delta, T, r, sigma, tol=0.001):
    """Binary search for strike K such that bs_delta(S,K,T,r,sigma) == target_delta"""
    # Higher delta = lower strike (deeper ITM)
    K_lo, K_hi = S * 0.50, S * 1.10
    for _ in range(60):
        K_mid = (K_lo + K_hi) / 2
        d = bs_delta(S, K_mid, T, r, sigma)
        if abs(d - target_delta) < tol:
            return K_mid
        if d > target_delta:
            K_lo = K_mid   # delta too high → strike too low → raise strike
        else:
            K_hi = K_mid
    return K_mid

# Use actual entry/exit prices from trade data
trade_results = []
for t in t_all:
    S_in  = t["entry_px"]
    S_out = t["exit_px"]
    K     = find_strike_for_delta(S_in, TARGET_DELTA, T_in, R, IV)  # 0.80-delta strike

    opt_in  = bs_call(S_in,  K, T_in,  R, IV)
    opt_out = bs_call(S_out, K, T_out, R, IV)

    # Pay spread + commission on entry and exit
    buy_price  = opt_in  + SPREAD + COMM/MULT
    sell_price = opt_out - SPREAD - COMM/MULT

    pnl_opt  = (sell_price - buy_price) * MULT
    pnl_pct  = pnl_opt / (buy_price * MULT) * 100

    trade_results.append({
        "date":      t["date"],
        "symbol":    t["symbol"],
        "stock_pnl": t["pnl"],
        "opt_buy":   buy_price,
        "opt_sell":  sell_price,
        "pnl_d":     pnl_opt,
        "pnl_pct":   pnl_pct,
        "year":      t["year"],
    })

odf = pd.DataFrame(trade_results)
wins  = odf[odf["pnl_d"]>0]
loses = odf[odf["pnl_d"]<=0]
wr    = len(wins)/len(odf)
aw_d  = wins["pnl_d"].mean()   if len(wins)  else 0
al_d  = loses["pnl_d"].mean()  if len(loses) else 0
pf    = wins["pnl_d"].sum()/abs(loses["pnl_d"].sum()) if loses["pnl_d"].sum()!=0 else 0
ev_d  = wins["pnl_d"].sum()/len(odf)
tot_d = odf["pnl_d"].sum()
avg_prem = odf["opt_buy"].mean() * MULT

# max drawdown in $
cum_d = odf["pnl_d"].cumsum()
dd_d  = (cum_d.expanding().max()-cum_d).max()

print(f"  Total trades modeled:   {len(odf)}")
print(f"  Avg premium paid:      ${avg_prem:.2f}  per contract")
print()
print(f"  {'Metric':<28} {'Options':>12}  {'Underlying':>12}")
line(60)
s_all = st(t_all)
print(f"  {'Win Rate':<28} {wr*100:>10.1f}%  {s_all['wr']*100:>10.1f}%")
print(f"  {'Profit Factor':<28} {pf:>12.2f}  {s_all['pf']:>12.2f}")
print(f"  {'Avg Winner':<28} ${aw_d:>10.2f}  {s_all['aw']:>+10.3f}%")
print(f"  {'Avg Loser':<28} ${al_d:>10.2f}  {s_all['al']:>-10.3f}%")
print(f"  {'EV per trade':<28} ${ev_d:>10.2f}")
print(f"  {'Total P&L (1 contract/trade)':<28} ${tot_d:>10.2f}")
print(f"  {'Max Drawdown':<28} ${dd_d:>10.2f}")
print()

# Year breakdown for options
print(f"  {'Year':<8} {'Trades':>8} {'WR%':>7} {'PF':>7} {'EV $':>9} {'Total $':>10}  Verdict")
line(60)
for yr in [2024, 2025, 2026]:
    ydf = odf[odf["year"]==yr]
    if len(ydf)==0: continue
    yw = ydf[ydf["pnl_d"]>0]; yl = ydf[ydf["pnl_d"]<=0]
    ywr = len(yw)/len(ydf)
    ypf = yw["pnl_d"].sum()/abs(yl["pnl_d"].sum()) if yl["pnl_d"].sum()!=0 else 0
    yev = ydf["pnl_d"].sum()/len(ydf)
    ytot= ydf["pnl_d"].sum()
    v   = "PASS" if ypf>=1.3 and yev>0 else ("EDGE" if ytot>0 else "FAIL")
    print(f"  {yr:<8} {len(ydf):>8} {ywr*100:>6.1f}% {ypf:>7.2f} {yev:>+8.2f} {ytot:>+9.2f}  {v}")
line(60)
print(f"  {'COMBINED':<8} {len(odf):>8} {wr*100:>6.1f}% {pf:>7.2f} {ev_d:>+8.2f} {tot_d:>+9.2f}")
print()

# Capital efficiency comparison
print(f"  --- Capital Efficiency (1 contract/signal) ---")
avg_stock_px = df_all["entry_px"].mean()
stock_cost   = avg_stock_px * 100   # 100 shares equivalent
opt_cost     = avg_prem
print(f"  Stock (100 shares):   ${stock_cost:,.0f}  capital per trade")
print(f"  Option (1 contract):  ${opt_cost:,.0f}  capital per trade")
print(f"  Leverage ratio:       {stock_cost/opt_cost:.0f}x")
if tot_d > 0:
    stock_return_on_opt = tot_d / (opt_cost) * 100
    print(f"  Options total return on premium:  {stock_return_on_opt:+.1f}%")
sep()

OUT.flush(); OUT.close()
_p("\nDone -> boof29_validation_delta80.txt")
