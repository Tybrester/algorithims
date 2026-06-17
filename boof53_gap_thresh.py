"""
boof53_gap_thresh.py
Gap threshold test: none / 0.1% / 0.2% / 0.3% / 0.5%
10 symbols, Version H routing, 1-yr cached data.
"""
import pandas as pd, numpy as np, pytz

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60

# 10 symbols covering all routing types
ROUTING = {
    "APP":   ("PMH", None, None),
    "SMCI":  ("PMH", None, None),
    "HIMS":  ("PMH", None, None),
    "META":  ("PDH", None, None),
    "AFRM":  ("PDH", None, None),
    "TSLA":  ("PIV",  10,  2),
    "HOOD":  ("PIV",  10,  2),
    "AMD":   ("PIV",  30,  3),
    "COIN":  ("PIV",  30,  3),
    "PLTR":  ("PIV", 240,  8),
}

GAP_THRESHOLDS = [
    ("No gap filter", -99.0),
    (">= 0.1%",        0.10),
    (">= 0.2%",        0.20),
    (">= 0.3%",        0.30),
    (">= 0.5%",        0.50),
]

# ── Data helpers ─────────────────────────────────────────────────────────────

def load_sym(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm <= "16:00")].copy()
    pm  = df[(hm >= "04:00") & (hm <  "09:30")].copy()
    rth["date"] = rth["time"].dt.date
    pm["date"]  = pm["time"].dt.date
    return rth, pm

def build_day_stats(rth, pm):
    """Returns df indexed by date with pm_high, pdh, prev_close, rth_open, gap_pct."""
    pm["date"] = pd.to_datetime(pm["date"])
    rth["date"] = pd.to_datetime(rth["date"])
    pm_agg = pm.groupby("date").agg(pm_high=("high","max")).reset_index()
    pc = rth.groupby("date")["close"].last().reset_index()
    pc.columns = ["date","prev_close"]
    pc["next_date"] = pc["date"] + pd.Timedelta(days=1)
    pdh = rth.groupby("date")["high"].max().reset_index()
    pdh.columns = ["date","pdh"]
    pdh["next_date"] = pdh["date"] + pd.Timedelta(days=1)
    ro = rth.groupby("date")["open"].first().reset_index()
    ro.columns = ["date","rth_open"]
    stats = (ro
             .merge(pc[["next_date","prev_close"]].rename(columns={"next_date":"date"}), on="date", how="left")
             .merge(pdh[["next_date","pdh"]].rename(columns={"next_date":"date"}), on="date", how="left")
             .merge(pm_agg, on="date", how="left"))
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["prev_close","rth_open"]).set_index("date")

def build_pivots(rth, lookback, wing):
    rth = rth.sort_values("time").reset_index(drop=True)
    rth["date"] = pd.to_datetime(rth["date"])
    sr = {}
    for d in sorted(rth["date"].unique()):
        hist = rth[rth["date"] < d].tail(lookback)
        if len(hist) < max(wing + 1, lookback // 4):
            continue
        H = hist["high"].values
        raw = []
        for i in range(wing, len(hist)):
            if H[i] == H[i-wing:i+1].max():
                raw.append(H[i])
        if not raw:
            continue
        raw = sorted(raw)
        cl = [raw[0]]
        for lv in raw[1:]:
            if abs(lv - cl[-1]) / cl[-1] < OVERLAP:
                cl[-1] = (cl[-1] + lv) / 2
            else:
                cl.append(lv)
        sr[d] = cl
    return sr

def race(ddf, ei, ep):
    tp_px = ep * (1 - TP_PCT)
    sl_px = ep * (1 + SL_PCT)
    for i in range(ei, min(ei + MAX_BARS, len(ddf) - 1) + 1):
        if ddf.iloc[i]["high"] >= sl_px: return "SL"
        if ddf.iloc[i]["low"]  <= tp_px: return "TP"
    return "X"

# ── Main scanner ─────────────────────────────────────────────────────────────

def scan_sym(sym, gap_min):
    rtype, lb, wing = ROUTING[sym]
    rth, pm = load_sym(sym)
    day_stats = build_day_stats(rth, pm)
    pivots = build_pivots(rth, lb, wing) if rtype == "PIV" else {}
    records = []

    for date, ddf in rth.groupby(pd.to_datetime(rth["date"])):
        if date not in day_stats.index:
            continue
        day = day_stats.loc[date]
        gap = day["gap_pct"]
        if gap < gap_min:
            continue

        ddf = ddf.reset_index(drop=True)
        n = len(ddf)

        # Build levels for this day
        if rtype == "PMH":
            if pd.isna(day.get("pm_high")): continue
            levels = [day["pm_high"]]
        elif rtype == "PDH":
            if pd.isna(day.get("pdh")): continue
            levels = [day["pdh"]]
        else:  # PIV
            dk = date.date() if hasattr(date, "date") else date
            levels = pivots.get(date, pivots.get(dk, []))
            if not levels: continue

        H = ddf["high"].values
        C = ddf["close"].values

        for level in levels:
            if pd.isna(level): continue
            state = "IDLE"; ext = None; touch_num = 0
            for i in range(n - 2):
                touching = H[i] >= level * (1 - NEAR_PCT)
                if state == "IDLE":
                    if touching:
                        state = "IN"; ext = C[i]; touch_num += 1
                elif state == "IN":
                    if touching:
                        ext = min(ext, C[i])
                    else:
                        bounced = ext is not None and (level - ext) / level >= BOUNCE
                        if bounced and touch_num == 1:
                            ei = i + 1
                            ep = ddf.iloc[ei]["open"]
                            out = race(ddf, ei, ep)
                            pnl = TP_PCT * 100 if out == "TP" else (-SL_PCT * 100 if out == "SL" else 0.0)
                            records.append({"sym": sym, "date": date, "gap_pct": gap, "outcome": out, "pnl": pnl})
                        state = "IDLE"; ext = None
    return pd.DataFrame(records)

def stats(df, weeks):
    if len(df) < 3: return None
    n  = len(df)
    tp = (df["outcome"] == "TP").sum()
    sl = (df["outcome"] == "SL").sum()
    wr = tp / n * 100
    pf = (tp * TP_PCT * 100) / (sl * SL_PCT * 100) if sl > 0 else 999.0
    ev = df["pnl"].mean()
    tpw = n / weeks
    return dict(n=n, tpw=tpw, wr=wr, tp=tp, sl=sl, pf=pf, ev=ev)

def prow(label, m, w=18):
    if m is None:
        print(f"  {label:<{w}}  (insufficient data)")
        return
    mk = " <<<" if m["pf"] >= 2.0 else (" <<" if m["pf"] >= 1.5 else (" <" if m["pf"] >= 1.2 else ""))
    print(f"  {label:<{w}}  N={m['n']:>4}  T/Wk={m['tpw']:>4.1f}  "
          f"WR={m['wr']:>5.1f}%  TP/SL={m['tp']}/{m['sl']}  PF={m['pf']:>5.3f}  EV={m['ev']:>+6.4f}%{mk}")

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    SYMS = list(ROUTING.keys())
    print(f"Scanning {len(SYMS)} symbols across {len(GAP_THRESHOLDS)} gap thresholds...")

    # Collect all data once per symbol (no filter)
    all_records = {}
    for sym in SYMS:
        print(f"  {sym}", end=" ", flush=True)
        df = scan_sym(sym, gap_min=-99.0)
        all_records[sym] = df
    print()

    # Figure out date range for weeks
    all_df = pd.concat(all_records.values(), ignore_index=True)
    if all_df.empty:
        print("No data found — check CSV files exist.")
        exit()
    weeks = max(1.0, (all_df["date"].max() - all_df["date"].min()).days / 7)
    print(f"Date range: {all_df['date'].min().date()} → {all_df['date'].max().date()}  ({weeks:.1f} weeks)\n")

    HDR = f"  {'Gap Filter':<18}  {'N':>4}  {'T/Wk':>5}  {'WR':>6}  {'TP/SL':>7}  {'PF':>6}  {'EV/trade':>8}"
    SEP = "  " + "-" * 72

    print("=" * 76)
    print(f"  GAP THRESHOLD TEST  |  10 symbols  |  TP+0.50% / SL-0.25%")
    print("=" * 76)
    print(HDR); print(SEP)

    for label, gap_min in GAP_THRESHOLDS:
        frames = []
        for sym in SYMS:
            df = all_records[sym]
            if not df.empty:
                frames.append(df[df["gap_pct"] >= gap_min])
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        prow(label, stats(combined, weeks))

    print(SEP)

    # Per-symbol breakdown at 0.5% (current) vs no filter
    print(f"\n  PER-SYMBOL: No filter vs >= 0.5%")
    print(HDR); print(SEP)
    for sym in SYMS:
        df = all_records[sym]
        if df.empty: continue
        m_all  = stats(df, weeks)
        m_half = stats(df[df["gap_pct"] >= 0.5], weeks)
        prow(f"  {sym} (all)",    m_all)
        prow(f"  {sym} (>=0.5%)", m_half)
        print(SEP)
