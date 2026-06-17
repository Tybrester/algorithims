"""
BOOF 29 — 3-Year Full Backtest (2024 / 2025 / 2026)
Long-only, bucket 0.50-0.60%, exit 10:20
Full sector / symbol / monthly breakdown
"""
import sys, pickle, os, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd

OUT = open('boof29_3year_results.txt', 'w', encoding='utf-8')
_p = print
def print(*a, **k):
    _p(*a, **k)
    _p(*a, **k, file=OUT)

CACHE_KEY = "2024-01-01_2026-12-31"

SECTORS = {
    "Semiconductors": [
        "NVDA","AMD","AVGO","TSM","ASML","MU","AMAT","KLAC","LRCX",
        "MCHP","ADI","QCOM","NXPI","ON","MPWR","MRVL","INTC","ARM",
        "TER","SWKS","QRVO","GFS","WOLF","COHR","LSCC","AEHR",
        "ACLS","FORM","CRUS","SYNA","SMTC","AMKR","RMBS","UCTT",
        "ENTG","ALAB","CEVA","ICHR","VECO","ONTO","SIMO","HIMX",
        "PI","IPGP","DIOD","POWI","MTSI","AOSL",
    ],
    "AI/Software/Cloud": [
        "PLTR","APP","SNOW","CRWD","NET","DDOG","MDB","ZS",
        "PANW","FTNT","HUBS","DUOL","CFLT","ESTC","GTLB",
        "SMAR","AI","PATH","DOCN","MNDY","ASAN","TEAM",
        "SHOP","ROKU","SPOT","AFRM","UPST","BILL","TOST",
        "PAYO","CELH","HIMS","SOUN","IONQ","TEM","RKLB",
        "S","DOCU","OKTA","TWLO","FIVN","U","DMRC",
    ],
    "Mega-cap Tech": [
        "AAPL","MSFT","META","GOOGL","AMZN","TSLA","NFLX",
        "ORCL","CRM","ADBE","NOW","INTU","IBM","CSCO",
    ],
    "Fintech": [
        "HOOD","COIN","SOFI","AFRM","UPST","SQ","FI","PYPL",
        "NU","BILL","TOST","PAYO","MA","V","AXP","SCHW",
        "MS","GS","JPM","BAC","WFC","KKR","BX","BLK",
        "SPGI","MCO","CME","ICE","AJG","PGR","TRV","MMC",
        "AMP","RJF","STT","NTRS",
    ],
    "Biotech": [
        "LLY","NVO","ISRG","REGN","VRTX","MRNA","DXCM",
        "EW","ALGN","PODD","HOLX","RMD","TECH","BIO",
        "IDXX","ZTS","HCA","UNH","ELV","CI","HUM",
        "ABBV","AMGN","GILD","TMO","DHR","ABT","MDT",
        "BSX","SYK","INCY","BMRN","EXAS","RVTY",
        "WAT","IQV","CRL","ILMN","VEEV",
    ],
    "Industrials": [
        "CAT","ETN","PH","TT","URI","DE","ROP","PWR",
        "AME","HUBB","XYL","DOV","GWW","FAST","ODFL",
        "UNP","NSC","CSX","PCAR","ROK","JCI","IR",
        "CARR","GE","RTX","LMT","NOC","GD","TDG",
        "HEI","EXPD","CHRW","ITW","EMR","HON",
    ],
    "Travel/Consumer": [
        "UBER","ABNB","BKNG","EXPE","MAR","HLT",
        "RCL","CCL","NCLH","LVS","MGM","WYNN",
        "CMG","SBUX","MCD","YUM","DPZ",
        "LULU","NKE","ULTA","TJX","ROST","MELI",
        "ETSY","DASH","CAVA","WING","SG",
    ],
    "Energy/Materials": [
        "XOM","CVX","COP","EOG","SLB","MPC","VLO",
        "PSX","OXY","DVN","FANG","APA","HAL","BKR",
        "LNG","EQT","FCX","NUE","STLD","NEM",
        "LIN","APD","SHW","MLM","VMC",
    ],
}

SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS   = list(dict.fromkeys(s for syms in SECTORS.values() for s in syms))

# ── Loaders ──────────────────────────────────────────────────────────
def load(sym):
    f = f"boof_cache/{sym}_{CACHE_KEY}.pkl"
    if os.path.exists(f):
        return pickle.load(open(f, "rb"))
    return None

def build_ema50(qqq):
    d = qqq.groupby(qqq.index.date)["close"].last()
    d.index = pd.to_datetime(d.index)
    return d.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(ema_series, date):
    ts = pd.Timestamp(date)
    v  = ema_series.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in ema_series.index if d.date() < date]
        v = ema_series[prior[-1]] if prior else None
    return v

# ── Core collector (fast: pre-grouped by date) ───────────────────────
def extract_bar(grp, time_str):
    """Get first bar matching HH:MM from an already-filtered day group."""
    h, m = int(time_str[:2]), int(time_str[3:])
    mask = (grp.index.hour == h) & (grp.index.minute == m)
    sub  = grp[mask]
    return sub.iloc[0] if len(sub) > 0 else None

def pregroup(df_et, start_date, end_date):
    """Group a df by date, pre-filtered to the date range."""
    sub = df_et[(df_et.index.date >= start_date) & (df_et.index.date <= end_date)]
    return {d: grp for d, grp in sub.groupby(sub.index.date)}

def collect(all_data_et, ema50, start, end):
    s_et = start.tz_convert("America/New_York")
    e_et = end.tz_convert("America/New_York")
    sd   = s_et.date(); ed = e_et.date()

    print("    Pre-grouping QQQ...", flush=True)
    qqq_grp = pregroup(all_data_et["QQQ"], sd, ed)

    print("    Pre-grouping stocks...", flush=True)
    sym_grps = {}
    for sym in ALL_SYMBOLS:
        if sym in all_data_et:
            sym_grps[sym] = pregroup(all_data_et[sym], sd, ed)

    trades = []; active_days = 0
    all_dates = sorted(qqq_grp.keys())
    print(f"    Scanning {len(all_dates)} trading days...", flush=True)

    for d in all_dates:
        qday = qqq_grp[d]
        # Opening 5m move: 09:30-09:34
        op_mask = (qday.index.hour == 9) & (qday.index.minute >= 30) & (qday.index.minute <= 34)
        qop = qday[op_mask]
        if len(qop) == 0: continue
        q5 = (qop.iloc[-1]["close"] - qop.iloc[0]["open"]) / qop.iloc[0]["open"]
        # QQQ open bar
        ob_mask = (qday.index.hour == 9) & (qday.index.minute == 30)
        qob = qday[ob_mask]
        if len(qob) == 0: continue
        qqq_open = qob.iloc[0]["open"]
        e50 = get_ema(ema50, d)
        if e50 is None: continue
        if not (qqq_open > e50 and q5 >= 0.001): continue

        day_had_trade = False
        for sym, grps in sym_grps.items():
            sday = grps.get(d)
            if sday is None or len(sday) == 0: continue
            # Stock opening 5m
            so_mask = (sday.index.hour == 9) & (sday.index.minute >= 30) & (sday.index.minute <= 34)
            so = sday[so_mask]
            if len(so) == 0: continue
            s5  = (so.iloc[-1]["close"] - so.iloc[0]["open"]) / so.iloc[0]["open"]
            s5p = s5 * 100
            if not (0.50 <= s5p < 0.60): continue
            # Entry 09:35
            en_mask = (sday.index.hour == 9) & (sday.index.minute == 35)
            en = sday[en_mask]
            if len(en) == 0: continue
            # Exit 10:20
            ex_mask = (sday.index.hour == 10) & (sday.index.minute == 20)
            ex = sday[ex_mask]
            if len(ex) == 0: continue
            ep = en.iloc[0]["open"]; xp = ex.iloc[0]["open"]
            pnl = (xp - ep) / ep * 100
            ts2 = pd.Timestamp(d)
            trades.append({
                "date":    d,
                "symbol":  sym,
                "sector":  SYM_TO_SECTOR.get(sym, "Other"),
                "pnl":     pnl,
                "qqq_5m":  round(q5*100, 3),
                "month":   ts2.to_period("M"),
                "quarter": ts2.to_period("Q"),
                "year":    ts2.year,
            })
            day_had_trade = True
        if day_had_trade:
            active_days += 1

    return trades, active_days

# ── Stats helper ─────────────────────────────────────────────────────
def stats(rows):
    if isinstance(rows, list):
        if not rows: return None
        df = pd.DataFrame(rows)
    else:
        df = rows
    if len(df) == 0: return None
    w = df[df["pnl"]>0]; l = df[df["pnl"]<=0]
    wr = len(w)/len(df)
    aw = w["pnl"].mean()   if len(w) else 0
    al = abs(l["pnl"].mean()) if len(l) else 0
    ev = wr*aw - (1-wr)*al
    pf = w["pnl"].sum()/abs(l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 0
    tot= df["pnl"].sum()
    cum= df["pnl"].cumsum()
    dd = (cum.expanding().max()-cum).max()
    return dict(n=len(df), wr=wr, aw=aw, al=al, ev=ev, pf=pf, tot=tot, dd=dd, df=df)

def sep(w=88): print("="*w)
def line(w=88): print("-"*w)
def hdr(t): sep(); print(f"  {t}"); sep()

# ── Load data ────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
missing  = []
for sym in ["QQQ"] + ALL_SYMBOLS:
    df = load(sym)
    if df is not None:
        all_data[sym] = df
    else:
        missing.append(sym)

print(f"Loaded: {len(all_data)} symbols")
if missing:
    print(f"Missing cache ({len(missing)}): {missing[:20]}{'...' if len(missing)>20 else ''}")
print("Converting to ET timezone...")
all_data_et = {sym: df.tz_convert("America/New_York") for sym, df in all_data.items()}
print()

ema50 = build_ema50(all_data["QQQ"].copy())

def ts(s): return pd.to_datetime(s).tz_localize("UTC")

# Date ranges
periods = {
    "2024": (ts("2024-01-01"), ts("2024-12-31")),
    "2025": (ts("2025-01-01"), ts("2025-12-31")),
    "2026": (ts("2026-01-01"), ts("2026-06-09")),
}

print("Collecting trades (this will take a few minutes)...")
year_trades = {}
year_active = {}
for yr, (s, e) in periods.items():
    print(f"  Running {yr}...", flush=True)
    t, ad = collect(all_data_et, ema50, s, e)
    year_trades[yr] = t
    year_active[yr] = ad
    print(f"    {yr}: {len(t)} trades on {ad} active days")

all_trades = year_trades["2024"] + year_trades["2025"] + year_trades["2026"]
if all_trades:
    df_all = pd.DataFrame(all_trades)
else:
    df_all = pd.DataFrame(columns=["date","symbol","sector","pnl","qqq_5m","month","quarter","year"])
total_active = sum(year_active.values())
print(f"\nTotal: {len(all_trades)} trades across {total_active} active days\n")

# ════════════════════════════════════════════════════════════════════
# SECTION 1: OVERALL + YEAR-BY-YEAR
# ════════════════════════════════════════════════════════════════════
hdr("BOOF 29 — 3-YEAR RESULTS  (Long Only | 0.50-0.60% | Entry 9:35 | Exit 10:20)")
print(f"  {'Period':<12} {'Trades':>8} {'T/Day':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}  Verdict")
line()
for yr in ["2024","2025","2026","COMBINED"]:
    if yr == "COMBINED":
        t = all_trades; ad = total_active
        line()
    else:
        t = year_trades[yr]; ad = year_active[yr]
    s = stats(t)
    if not s: continue
    tpd = s["n"]/ad if ad>0 else 0
    v = "PASS" if s["pf"]>=1.5 and s["ev"]>0 else ("PASS" if s["pf"]>=1.2 else ("EDGE" if s["pf"]>=1.0 else "FAIL"))
    print(f"  {yr:<12} {s['n']:>8} {tpd:>7.2f} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%  {v}")
sep()

# ════════════════════════════════════════════════════════════════════
# SECTION 2: SECTOR BREAKDOWN
# ════════════════════════════════════════════════════════════════════
hdr("SECTOR BREAKDOWN  (3 years combined)")
print(f"  {'Sector':<22} {'Trades':>8} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}")
line()
sec_rows = []
for sec in SECTORS:
    sub = df_all[df_all["sector"]==sec]
    s   = stats(sub)
    if not s: continue
    sec_rows.append((sec, s))
for sec, s in sorted(sec_rows, key=lambda x: -x[1]["tot"]):
    print(f"  {sec:<22} {s['n']:>8} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")
sep()

# ════════════════════════════════════════════════════════════════════
# SECTION 3: TOP 20 / BOTTOM 20 SYMBOLS
# ════════════════════════════════════════════════════════════════════
hdr("SYMBOL BREAKDOWN — TOP 20")
sym_rows = []
for sym, grp in df_all.groupby("symbol"):
    w = grp[grp["pnl"]>0]; l = grp[grp["pnl"]<=0]
    pf = w["pnl"].sum()/abs(l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 0
    sym_rows.append({
        "sym":    sym,
        "sec":    SYM_TO_SECTOR.get(sym,"?"),
        "n":      len(grp),
        "wr":     len(w)/len(grp)*100,
        "pf":     pf,
        "avg":    grp["pnl"].mean(),
        "total":  grp["pnl"].sum(),
    })
sym_df = pd.DataFrame(sym_rows).sort_values("total", ascending=False)
total_pnl = df_all["pnl"].sum()

print(f"  {'Symbol':>8} {'Sector':<22} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9} {'Contrib%':>9}")
line()
for _, r in sym_df.head(20).iterrows():
    contrib = r["total"]/total_pnl*100
    print(f"  {r['sym']:>8} {r['sec']:<22} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}% {contrib:>+8.1f}%")

sep()
hdr("SYMBOL BREAKDOWN — BOTTOM 20")
print(f"  {'Symbol':>8} {'Sector':<22} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9} {'Contrib%':>9}")
line()
for _, r in sym_df.tail(20).iloc[::-1].iterrows():
    contrib = r["total"]/total_pnl*100
    print(f"  {r['sym']:>8} {r['sec']:<22} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}% {contrib:>+8.1f}%")
sep()

# Concentration
t5  = sym_df.head(5)["total"].sum()
t10 = sym_df.head(10)["total"].sum()
t20 = sym_df.head(20)["total"].sum()
print(f"  Top  5 symbols: {t5:+.2f}%  ({t5/total_pnl*100:.0f}% of total P&L)")
print(f"  Top 10 symbols: {t10:+.2f}%  ({t10/total_pnl*100:.0f}% of total P&L)")
print(f"  Top 20 symbols: {t20:+.2f}%  ({t20/total_pnl*100:.0f}% of total P&L)")
sep()

# ════════════════════════════════════════════════════════════════════
# SECTION 4: MONTHLY BREAKDOWN
# ════════════════════════════════════════════════════════════════════
hdr("MONTHLY BREAKDOWN  (3 years)")
print(f"  {'Month':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9}  {'Cum':>9}")
line()
cum2 = 0
for m in sorted(df_all["month"].unique()):
    mdf = df_all[df_all["month"]==m]; mt = mdf["pnl"].sum(); cum2 += mt
    w   = mdf[mdf["pnl"]>0]; l = mdf[mdf["pnl"]<=0]
    mwr = len(w)/len(mdf)*100
    mpf = w["pnl"].sum()/abs(l["pnl"].sum()) if len(l)>0 and l["pnl"].sum()!=0 else 0
    flag = "  RED" if mt < 0 else ""
    print(f"  {str(m):<10} {len(mdf):>7} {mwr:>5.1f}% {mpf:>6.2f} {mt:>+8.2f}%  {cum2:>+8.2f}%{flag}")
sep()

# ════════════════════════════════════════════════════════════════════
# SECTION 5: SECTOR x YEAR CROSS-TABLE
# ════════════════════════════════════════════════════════════════════
hdr("SECTOR x YEAR CROSS-TABLE  (Total P&L %)")
years = ["2024","2025","2026"]
print(f"  {'Sector':<22}" + "".join(f" {yr:>10}" for yr in years) + f"  {'3yr Total':>10}")
line()
for sec in SECTORS:
    row = f"  {sec:<22}"
    total_sec = 0
    for yr in years:
        sub = df_all[(df_all["sector"]==sec) & (df_all["year"]==int(yr))]
        val = sub["pnl"].sum() if len(sub)>0 else 0
        total_sec += val
        row += f" {val:>+9.2f}%"
    row += f"  {total_sec:>+9.2f}%"
    print(row)
sep()

OUT.flush(); OUT.close()
_p("\nDone -> boof29_3year_results.txt")
