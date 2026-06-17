"""
boof53_retest.py
Compares two signal modes on 1-yr 1-min data:
  MODE A: Fresh 1st touch only (current live logic)
  MODE B: Fresh 1st touch + re-test after level is crossed and price returns

Same 10 symbols, Version H routing, 0.5% gap filter.
"""
import pandas as pd, numpy as np, pytz, os

ET       = pytz.timezone("America/New_York")
NEAR_PCT = 0.0015   # within 0.15% = touching
BOUNCE   = 0.0015   # bounce >= 0.15% to confirm
TP_PCT   = 0.0050
SL_PCT   = 0.0025
MAX_BARS = 60
GAP_MIN  = 0.005
RETEST_CLEAR = 0.005  # price must drop 0.5% below level before re-test allowed

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

# ── Data helpers ──────────────────────────────────────────────────────────────

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
    pm["date"]  = pd.to_datetime(pm["date"])
    rth["date"] = pd.to_datetime(rth["date"])
    pm_agg = pm.groupby("date").agg(pm_high=("high","max")).reset_index()
    pc     = rth.groupby("date")["close"].last().reset_index()
    pc.columns = ["date","prev_close"]
    pc["next_date"] = pc["date"] + pd.Timedelta(days=1)
    pdh    = rth.groupby("date")["high"].max().reset_index()
    pdh.columns = ["date","pdh"]
    rth_open = rth.groupby("date")["open"].first().reset_index()
    rth_open.columns = ["date","rth_open"]
    stats = rth_open.merge(pc[["next_date","prev_close"]], left_on="date", right_on="next_date", how="left")
    stats = stats.merge(pdh.rename(columns={"date":"prev_date","pdh":"pdh"}), left_on="date",
                        right_on=pd.to_datetime(stats["date"]) - pd.Timedelta(days=1) if False else "prev_date", how="left")
    stats = rth_open.copy()
    dates = sorted(rth["date"].unique())
    rows  = []
    for i, d in enumerate(dates):
        d_ts = pd.Timestamp(d)
        prev = [x for x in dates[:i] if pd.Timestamp(x) < d_ts]
        if not prev: continue
        prev_d = prev[-1]
        prev_close = rth[rth["date"]==prev_d]["close"].iloc[-1]
        pdh_val    = rth[rth["date"]==prev_d]["high"].max()
        rth_open_v = rth[rth["date"]==d]["open"].iloc[0]
        pm_rows    = pm[pm["date"]==pd.Timestamp(d)]
        pm_high    = pm_rows["high"].max() if not pm_rows.empty else None
        gap_pct    = (rth_open_v - prev_close) / prev_close if prev_close else 0
        rows.append({"date": d, "prev_close": prev_close, "pdh": pdh_val,
                     "pm_high": pm_high, "rth_open": rth_open_v, "gap_pct": gap_pct})
    return pd.DataFrame(rows)

def build_pivot_levels(bars, lb, wing):
    if len(bars) < lb: return []
    window = bars[-lb:]
    highs  = [b["h"] for b in window]
    levels = []
    for i in range(wing, len(highs)-wing):
        if all(highs[i] >= highs[i-j] for j in range(1,wing+1)) and \
           all(highs[i] >= highs[i+j] for j in range(1,wing+1)):
            levels.append(highs[i])
    seen = []; deduped = []
    for lv in sorted(levels, reverse=True):
        if not any(abs(lv-s)/lv < 0.002 for s in seen):
            seen.append(lv); deduped.append(lv)
    return deduped

# ── State machine ─────────────────────────────────────────────────────────────

def run_sm_a(bars_today, levels):
    """Mode A: fresh 1st touch only."""
    trades = []
    sm = {round(lv,4): {"state":"IDLE","extreme":None,"touch_num":0} for lv in levels}
    i = 0
    while i < len(bars_today):
        bar = bars_today[i]
        h, c = bar["h"], bar["c"]
        for lv, s in sm.items():
            touching = h >= lv * (1 - NEAR_PCT)
            if s["state"] == "IDLE":
                if touching:
                    s["state"] = "IN"; s["extreme"] = c; s["touch_num"] = 1
            elif s["state"] == "IN":
                if touching:
                    s["extreme"] = min(s["extreme"], c)
                else:
                    bounced = s["extreme"] is not None and (lv - s["extreme"]) / lv >= BOUNCE
                    if bounced and s["touch_num"] == 1:
                        s["state"] = "FIRED"
                        # enter next bar
                        if i+1 < len(bars_today):
                            entry = bars_today[i+1]["o"]
                            tp = entry * (1 - TP_PCT)
                            sl = entry * (1 + SL_PCT)
                            result = sim_trade(bars_today[i+1:], entry, tp, sl)
                            trades.append(result)
                    else:
                        s["state"] = "DEAD"
        i += 1
    return trades

def run_sm_b(bars_today, levels):
    """Mode B: fresh 1st touch + re-test after crossing back below."""
    trades = []
    sm = {round(lv,4): {"state":"IDLE","extreme":None,"touch_num":0,"lowest_since_dead":None} for lv in levels}
    i = 0
    while i < len(bars_today):
        bar = bars_today[i]
        h, l, c = bar["h"], bar["l"], bar["c"]
        for lv, s in sm.items():
            touching = h >= lv * (1 - NEAR_PCT)
            if s["state"] == "IDLE":
                if touching:
                    s["state"] = "IN"; s["extreme"] = c; s["touch_num"] += 1
            elif s["state"] == "IN":
                if touching:
                    s["extreme"] = min(s["extreme"], c)
                else:
                    bounced = s["extreme"] is not None and (lv - s["extreme"]) / lv >= BOUNCE
                    if bounced and s["touch_num"] == 1:
                        s["state"] = "FIRED"
                        if i+1 < len(bars_today):
                            entry = bars_today[i+1]["o"]
                            tp = entry * (1 - TP_PCT)
                            sl = entry * (1 + SL_PCT)
                            result = sim_trade(bars_today[i+1:], entry, tp, sl)
                            trades.append(result)
                    else:
                        s["state"] = "DEAD"
                        s["lowest_since_dead"] = c
            elif s["state"] == "DEAD":
                if s["lowest_since_dead"] is None or l < s["lowest_since_dead"]:
                    s["lowest_since_dead"] = l
                if s["lowest_since_dead"] is not None and \
                   (lv - s["lowest_since_dead"]) / lv >= RETEST_CLEAR:
                    s["state"] = "IDLE"
                    s["extreme"] = None
                    s["touch_num"] = 0
                    s["lowest_since_dead"] = None
        i += 1
    return trades


def run_sm_c(bars_today, levels):
    """Mode C: was_below_level gate — touch only counts if price was below level first."""
    trades = []
    sm = {round(lv,4): {"state":"IDLE","extreme":None,"was_below":False} for lv in levels}
    i = 0
    while i < len(bars_today):
        bar = bars_today[i]
        h, c = bar["h"], bar["c"]
        for lv, s in sm.items():
            # track whether price has been below the level
            if c < lv:
                s["was_below"] = True
            touching = s["was_below"] and h >= lv * (1 - NEAR_PCT)
            if s["state"] == "IDLE":
                if touching:
                    s["state"] = "IN"; s["extreme"] = c
            elif s["state"] == "IN":
                if h >= lv * (1 - NEAR_PCT):
                    s["extreme"] = min(s["extreme"], c)
                else:
                    bounced = s["extreme"] is not None and (lv - s["extreme"]) / lv >= BOUNCE
                    if bounced:
                        s["state"] = "FIRED"
                        if i+1 < len(bars_today):
                            entry = bars_today[i+1]["o"]
                            tp = entry * (1 - TP_PCT)
                            sl = entry * (1 + SL_PCT)
                            result = sim_trade(bars_today[i+1:], entry, tp, sl)
                            trades.append(result)
                    else:
                        s["state"] = "DEAD"
                        s["was_below"] = False  # reset — must go below again
        i += 1
    return trades

def sim_trade(bars, entry, tp, sl):
    for j, b in enumerate(bars[:MAX_BARS]):
        if b["l"] <= tp:
            return {"pnl": TP_PCT, "exit": "tp", "bars": j+1}
        if b["h"] >= sl:
            return {"pnl": -SL_PCT, "exit": "sl", "bars": j+1}
    if bars:
        exit_px = bars[min(MAX_BARS-1, len(bars)-1)]["c"]
        pnl = (entry - exit_px) / entry
        return {"pnl": pnl, "exit": "timeout", "bars": MAX_BARS}
    return {"pnl": 0, "exit": "no_bars", "bars": 0}

# ── Main ──────────────────────────────────────────────────────────────────────

def summarise(trades, label):
    if not trades:
        print(f"  {label}: 0 trades")
        return
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    loss = [p for p in pnls if p <= 0]
    wr   = len(wins)/len(pnls)*100
    gw   = sum(wins) if wins else 0
    gl   = abs(sum(loss)) if loss else 1e-9
    pf   = gw/gl
    ev   = np.mean(pnls)*100
    print(f"  {label:30s}  N={len(trades):4d}  WR={wr:5.1f}%  PF={pf:.2f}  EV={ev:+.3f}%/trade")

print("=" * 70)
print("BOOF53 Re-test Backtest  |  1yr  |  GAP>=0.5%  |  TP=0.5% SL=0.25%")
print("=" * 70)

for sym, (rtype, lb, wing) in ROUTING.items():
    fname = f"boof51_{sym}_1m.csv"
    if not os.path.exists(fname):
        print(f"\n{sym}: no data file — skipping")
        continue
    rth, pm = load_sym(sym)
    day_stats = build_day_stats(rth, pm)
    all_a, all_b, all_c = [], [], []
    rth_bars_acc = []

    for _, row in day_stats.iterrows():
        d         = row["date"]
        gap_pct   = row["gap_pct"]
        prev_close= row["prev_close"]
        pdh       = row["pdh"]
        pm_high   = row["pm_high"]
        rth_open  = row["rth_open"]

        if gap_pct < GAP_MIN:
            day_bars = rth[rth["date"]==d][["open","high","low","close"]].rename(
                columns={"open":"o","high":"h","low":"l","close":"c"}).to_dict("records")
            rth_bars_acc.extend(day_bars)
            continue

        # Build level
        if rtype == "PMH":
            levels = [pm_high] if pm_high and not np.isnan(pm_high) else ([pdh] if pdh else [])
        elif rtype == "PDH":
            levels = [pdh] if pdh else []
        else:
            levels = build_pivot_levels(rth_bars_acc, lb, wing)

        day_bars = rth[rth["date"]==d][["open","high","low","close"]].rename(
            columns={"open":"o","high":"h","low":"l","close":"c"}).to_dict("records")

        if levels:
            all_a.extend(run_sm_a(day_bars, levels))
            all_b.extend(run_sm_b(day_bars, levels))
            all_c.extend(run_sm_c(day_bars, levels))

        rth_bars_acc.extend(day_bars)

    print(f"\n{sym} [{rtype}]")
    summarise(all_a, "Mode A: fresh touch only (current)")
    summarise(all_b, f"Mode B: + re-test (clear {RETEST_CLEAR*100:.1f}% below)")
    summarise(all_c, "Mode C: was_below_level gate")

print("\nDone.")
