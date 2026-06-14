"""
BOOF53 Multi-Symbol Study — CLEAN (no look-ahead bias)

Level definitions:
  PDH/PDL  = prior RTH session high/low (09:30-16:00) only
  PMH/PML  = current-day premarket (04:00-09:29) only
  1H/4H    = pivot swing highs/lows from prior RTH bars only
              pivot confirmed only using left-side bars (no future confirmation)

Pivot method:
  A bar is a swing high if it is the highest high in [i-wing .. i] — right-edge only.
  No look-forward. Confirmed the moment it prints.

Symbols: QQQ, NVDA, TSLA, AMD, META, AAPL, MSFT, AMZN, PLTR, IWM  (SPY excluded)
"""
import pandas as pd
import numpy as np
import pytz
import os

ET       = pytz.timezone("America/New_York")
SYMBOLS  = ["QQQ","NVDA","TSLA","AMD","META","AAPL","MSFT","AMZN","PLTR","IWM"]
NEAR_PCT = 0.0015
OVERLAP  = 0.0020
BOUNCE   = 0.0015          # default bounce threshold for main tables
BOUNCES  = [0.0010, 0.0015, 0.0020, 0.0030]
TARGETS  = [0.0050, 0.0075]
T_LABELS = [">=0.50%",">=0.75%"]


# ── Data loading ────────────────────────────────────────────────────────────

def load_sym(sym):
    """Return (rth_df, pm_df) — strictly separated, tz-aware."""
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = df.sort_values("time").reset_index(drop=True)
    hm = df["time"].dt.strftime("%H:%M")
    rth = df[(hm >= "09:30") & (hm <= "16:00")].copy()
    pm  = df[(hm >= "04:00") & (hm <  "09:30")].copy()
    rth["date"] = rth["time"].dt.date
    pm["date"]  = pm["time"].dt.date
    return rth, pm


# ── Level builders ──────────────────────────────────────────────────────────

def build_pdhl(rth_df):
    """PDH/PDL from prior RTH session only."""
    rth_df = rth_df.copy()
    rth_df["date"] = pd.to_datetime(rth_df["date"])
    dates = sorted(rth_df["date"].unique())
    prev = {}
    for i in range(1, len(dates)):
        d = dates[i]; p = dates[i-1]
        g = rth_df[rth_df["date"] == p]
        if not g.empty:
            prev[d] = {"pdh": g["high"].max(), "pdl": g["low"].min()}
    return prev

def build_pm_levels(pm_df, rth_df):
    """
    PMH/PML from current-day premarket (04:00-09:29).
    Also computes gap_pct = (rth_open - prev_rth_close) / prev_rth_close.
    Returns DataFrame indexed by date (Timestamp).
    """
    pm_df  = pm_df.copy();  pm_df["date"]  = pd.to_datetime(pm_df["date"])
    rth_df = rth_df.copy(); rth_df["date"] = pd.to_datetime(rth_df["date"])

    # PMH / PML per day
    pm_agg = pm_df.groupby("date").agg(pm_high=("high","max"), pm_low=("low","min")).reset_index()

    # Previous RTH close
    prev_close = rth_df.groupby("date")["close"].last().reset_index()
    prev_close.columns = ["date","prev_close"]
    prev_close["next_date"] = prev_close["date"] + pd.Timedelta(days=1)

    # RTH open (first bar at 09:30)
    rth_open = rth_df.groupby("date")["open"].first().reset_index()
    rth_open.columns = ["date","rth_open"]

    stats = pm_agg.merge(
        prev_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    ).merge(rth_open, on="date", how="left")

    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    stats = stats.dropna(subset=["gap_pct","pm_high"])
    return stats.set_index("date")

def build_pivots_clean(rth_df, lookback, wing):
    """
    Build S/R pivot levels from prior RTH bars only.
    NO look-ahead: a swing high at bar i is confirmed only using bars [i-wing .. i].
    i.e., H[i] == max(H[i-wing : i+1])  — left-side confirmation only.
    hist is strictly rt_df["date"] < d (prior days, RTH only).
    """
    rth_df = rth_df.sort_values("time").reset_index(drop=True)
    rth_df["date"] = pd.to_datetime(rth_df["date"])
    sr = {}
    dates = sorted(rth_df["date"].unique())

    for d in dates:
        hist = rth_df[rth_df["date"] < d].tail(lookback)
        if len(hist) < max(wing + 1, lookback // 4):
            continue
        H = hist["high"].values
        L = hist["low"].values
        levels = []

        # Left-side only: bar i is a swing high if H[i] == max(H[i-wing : i+1])
        for i in range(wing, len(hist)):
            window_h = H[i-wing : i+1]
            window_l = L[i-wing : i+1]
            if H[i] == window_h.max():
                levels.append((H[i], "res"))
            if L[i] == window_l.min():
                levels.append((L[i], "sup"))

        if not levels:
            continue

        # Cluster nearby levels (within OVERLAP)
        levels = sorted(levels, key=lambda x: x[0])
        cl = [list(levels[0])]
        for lv, lt in levels[1:]:
            if abs(lv - cl[-1][0]) / cl[-1][0] < OVERLAP:
                cl[-1][0] = (cl[-1][0] + lv) / 2
            else:
                cl.append([lv, lt])

        sr[d] = [(c[0], c[1]) for c in cl]

    return sr


# ── Excursion ───────────────────────────────────────────────────────────────

def exc(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values
    res = {}
    for bars, key in [(15,"mfe15"), (30,"mfe30"), (60,"mfe60")]:
        end = min(ei+bars, n-1); sl = slice(ei, end+1)
        res[key] = float(max((H[sl]-ep)/ep*100)) if side=="long" \
              else float(max((ep-L[sl])/ep*100))
    end60 = min(ei+60, n-1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end60+1] >= ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end60+1] <= ep*(1-tgt)))
    return res


# ── Touch scanner ───────────────────────────────────────────────────────────

def scan_level(ddf, level, direction, min_bounce):
    """
    Scan RTH bars for touches of `level`.
    Records every touch that bounces >= min_bounce.
    Entry price = open of bar (i+1), where bar i is the first bar that
    closes fully outside the zone.  This gives one fully-closed confirmation
    bar before entry — no same-bar ambiguity.
    """
    n = len(ddf)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    results = []; state = "IDLE"; ext = None; touch_num = 0; i = 0

    while i < n - 3:
        cl = C[i]; hi = H[i]; lo = L[i]

        if direction == "sup":
            touching = lo <= level * (1 + NEAR_PCT)
            if state == "IDLE":
                if touching:
                    state = "IN"; ext = cl; touch_num += 1
            elif state == "IN":
                if touching:
                    ext = max(ext, cl)
                else:
                    bounced = ext is not None and (ext - level) / level >= min_bounce
                    ei = i + 1  # confirmed exit bar = i; entry on next bar open
                    ep = ddf.iloc[ei]["open"]
                    results.append({
                        "touch_num": min(touch_num, 3),
                        "bounced": bounced,
                        "ep": ep,
                        **exc(ddf, ei, ep, "long")
                    })
                    state = "IDLE"; ext = None
        else:
            touching = hi >= level * (1 - NEAR_PCT)
            if state == "IDLE":
                if touching:
                    state = "IN"; ext = cl; touch_num += 1
            elif state == "IN":
                if touching:
                    ext = min(ext, cl)
                else:
                    bounced = ext is not None and (level - ext) / level >= min_bounce
                    ei = i + 1  # confirmed exit bar = i; entry on next bar open
                    ep = ddf.iloc[ei]["open"]
                    results.append({
                        "touch_num": min(touch_num, 3),
                        "bounced": bounced,
                        "ep": ep,
                        **exc(ddf, ei, ep, "short")
                    })
                    state = "IDLE"; ext = None
        i += 1

    return results


# ── Per-symbol scan ─────────────────────────────────────────────────────────

def run_symbol(sym, min_bounce=BOUNCE):
    if not os.path.exists(f"boof51_{sym}_1m.csv"):
        return pd.DataFrame()

    rth_df, pm_df = load_sym(sym)

    # Handle symbols with no premarket data (QQQ file only has RTH)
    if pm_df.empty:
        # Build PM stats from first 15m of RTH as fallback proxy
        # (clearly label so we know)
        pm_proxy = rth_df.copy()
        pm_stats = build_pm_levels(pm_proxy, rth_df)
        has_pm = False
    else:
        pm_stats = build_pm_levels(pm_df, rth_df)
        has_pm = True

    if pm_stats.empty:
        return pd.DataFrame()

    pdhl     = build_pdhl(rth_df)
    sr_1h    = build_pivots_clean(rth_df, lookback=60,  wing=3)
    sr_4h    = build_pivots_clean(rth_df, lookback=240, wing=5)

    rth_df = rth_df.copy()
    rth_df["date"] = pd.to_datetime(rth_df["date"])
    records = []

    for date, ddf in rth_df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm_stats.index:
            continue

        day        = pm_stats.loc[date_ts]
        gap        = day["gap_pct"]
        gap_regime = "Gap Down" if gap < -0.5 else ("Gap Up" if gap > 0.5 else "Flat")
        ddf        = ddf.reset_index(drop=True)

        pmh = day["pm_high"]; pml = day["pm_low"]
        pd_info = pdhl.get(date_ts, {})
        pdh = pd_info.get("pdh", np.nan)
        pdl = pd_info.get("pdl", np.nan)

        dk    = date_ts.date()
        lv1h  = sr_1h.get(date_ts, sr_1h.get(dk, []))
        lv4h  = sr_4h.get(date_ts, sr_4h.get(dk, []))

        long_levels  = [(pml, "PML")]
        short_levels = [(pmh, "PMH")]
        if not pd.isna(pdl): long_levels.append((pdl,  "PDL"))
        if not pd.isna(pdh): short_levels.append((pdh, "PDH"))
        for lv, lt in lv1h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv, "1H_Sup" if lt=="sup" else "1H_Res"))
        for lv, lt in lv4h:
            (long_levels if lt=="sup" else short_levels).append(
                (lv, "4H_Sup" if lt=="sup" else "4H_Res"))

        for level, lname in long_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf, level, "sup", min_bounce):
                tl = "1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({
                    "sym": sym, "side": "long", "level": lname,
                    "gap_regime": gap_regime, "gap_pct": round(gap, 3),
                    "touch_lbl": tl, "bounced": e["bounced"],
                    "date": str(date_ts.date()),
                    **{k: v for k, v in e.items() if k not in ("touch_num","bounced","ep")}
                })

        for level, lname in short_levels:
            if pd.isna(level): continue
            for e in scan_level(ddf, level, "res", min_bounce):
                tl = "1st" if e["touch_num"]==1 else ("2nd" if e["touch_num"]==2 else "3rd+")
                records.append({
                    "sym": sym, "side": "short", "level": lname,
                    "gap_regime": gap_regime, "gap_pct": round(gap, 3),
                    "touch_lbl": tl, "bounced": e["bounced"],
                    "date": str(date_ts.date()),
                    **{k: v for k, v in e.items() if k not in ("touch_num","bounced","ep")}
                })

    return pd.DataFrame(records)


# ── Reporting ────────────────────────────────────────────────────────────────

def row_stats(s):
    if s.empty or len(s) < 3: return None
    return (len(s), s["date"].nunique(),
            s["mfe15"].mean(), s["mfe30"].mean(), s["mfe60"].mean(),
            s["hit_>=0.50%"].mean()*100, s["hit_>=0.75%"].mean()*100)

def prow(label, s, w=20, min_n=3):
    r = row_stats(s)
    if r is None: print(f"  {label:<{w}} {'<'+str(min_n):>4}"); return
    n, nd, m15, m30, m60, h50, h75 = r
    mark = " <<<" if h50>=40 else ("  <<" if h50>=28 else "")
    print(f"  {label:<{w}} {n:>5} {nd:>4}d  "
          f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")

def report(all_df):
    W   = 92
    HDR = (f"  {'Label':<20} {'N':>5} {'Days':>5}  "
           f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    SEP = f"  {'-'*88}"

    base = all_df[all_df["bounced"] == True]

    # ── 1. Symbol summary ───────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  SYMBOL SUMMARY  |  CLEAN (RTH-only pivots, left-edge confirmation)")
    print(f"  bounce>={BOUNCE*100:.2f}%  |  all touches")
    print(f"{'='*W}")
    print(f"  {'Symbol':<8} {'Side':<7} {'N':>5} {'Days':>5}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}  {'>=0.75%':>7}")
    print(f"  {'-'*88}")
    sym_rows = []
    for sym in SYMBOLS:
        df = base[base["sym"]==sym]
        if df.empty: continue
        for side in ["long","short"]:
            s = df[df["side"]==side]
            r = row_stats(s)
            if r is None: continue
            n,nd,m15,m30,m60,h50,h75 = r
            sym_rows.append((sym,side,n,nd,m15,m30,m60,h50,h75))
            mark = " <<<" if h50>=40 else ("  <<" if h50>=28 else "")
            print(f"  {sym:<8} {side:<7} {n:>5} {nd:>4}d  "
                  f"{m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%  {h75:>6.1f}%{mark}")

    print(f"\n  RANKED BY MFE30 (min 5 trades)")
    print(f"  {'Symbol':<8} {'Side':<7} {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*46}")
    for row in sorted(sym_rows, key=lambda x: -x[6]):
        sym,side,n,nd,m15,m30,m60,h50,h75 = row
        if n < 5: continue
        mark = " <<<" if h50>=40 else ("  <<" if h50>=28 else "")
        print(f"  {sym:<8} {side:<7} {m30:>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── 2. Level type ranking across all symbols ────────────────────────────
    print(f"\n{'='*W}")
    print(f"  LEVEL RANKING — ALL SYMBOLS COMBINED  |  bounce>={BOUNCE*100:.2f}%")
    print(f"{'='*W}")

    for side, lnames in [("long",  ["PML","PDL","1H_Sup","4H_Sup"]),
                         ("short", ["PMH","PDH","1H_Res","4H_Res"])]:
        s_base = base[base["side"]==side]
        print(f"\n  {'LONG — Support' if side=='long' else 'SHORT — Resistance'}")
        print(HDR); print(SEP)
        prow("ALL", s_base)
        print(SEP)
        for lname in lnames:
            prow(lname, s_base[s_base["level"]==lname])
        print(SEP)

        # By touch count
        print(f"  BY TOUCH COUNT")
        for tl in ["1st","2nd","3rd+"]:
            prow(f"Touch {tl}", s_base[s_base["touch_lbl"]==tl])
        print(SEP)

        # Level × touch cross-tab
        print(f"\n  LEVEL × TOUCH (min N=5)")
        print(f"  {'Level':<10} {'Touch':<7} {'N':>5}  "
              f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
        print(f"  {'-'*52}")
        for lname in lnames:
            for tl in ["1st","2nd","3rd+"]:
                s = s_base[(s_base["level"]==lname) & (s_base["touch_lbl"]==tl)]
                if len(s) < 5: continue
                h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
                mark = " <<<" if h50>=40 else ("  <<" if h50>=28 else "")
                print(f"  {lname:<10} {tl:<7} {len(s):>5}  "
                      f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    # ── 3. Bounce threshold comparison ─────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  BOUNCE THRESHOLD COMPARISON — ALL SYMBOLS")
    print(f"{'='*W}")
    print(f"  {'Bounce':<10} {'Side':<7} {'N':>6}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*55}")
    for bounce in BOUNCES:
        for side in ["long","short"]:
            # filter: mfe in % vs bounce in decimal — first bar MFE proxy
            s = all_df[(all_df["side"]==side) & (all_df["mfe15"] >= bounce*100)]
            if len(s) < 5: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            blbl = f">={bounce*100:.2f}%"
            print(f"  {blbl:<10} {side:<7} {len(s):>6}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%")
        print()

    # ── 4. Gap regime ────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print(f"  GAP REGIME × SIDE — ALL SYMBOLS  |  bounce>={BOUNCE*100:.2f}%")
    print(f"{'='*W}")
    print(f"  {'Side':<7} {'Regime':<12} {'N':>5}  "
          f"{'MFE30':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*55}")
    for side in ["long","short"]:
        for regime in ["Gap Down","Flat","Gap Up"]:
            s = base[(base["side"]==side) & (base["gap_regime"]==regime)]
            if len(s) < 5: continue
            h50=s["hit_>=0.50%"].mean()*100; h75=s["hit_>=0.75%"].mean()*100
            mark = " <<<" if h50>=35 else ("  <<" if h50>=25 else "")
            print(f"  {side:<7} {regime:<12} {len(s):>5}  "
                  f"{s['mfe30'].mean():>6.3f}%   {h50:>8.1f}%  {h75:>8.1f}%{mark}")

    print(f"\n  NOTE: Pivots built from prior RTH bars only (09:30-16:00).")
    print(f"  NOTE: Swing high/low confirmed on left edge only — no future bars used.")
    print(f"  NOTE: PDH/PDL = prior RTH session only. PMH/PML = current premarket only.")


if __name__ == "__main__":
    print(f"BOOF53 CLEAN — {len(SYMBOLS)} symbols", flush=True)
    frames = []
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        df = run_symbol(sym)
        print(f"{len(df)} touches  "
              f"(bounced={df['bounced'].sum() if not df.empty else 0})", flush=True)
        frames.append(df)

    all_df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    print(f"\n  Total: {len(all_df):,} touches  "
          f"bounced(>={BOUNCE*100:.2f}%): {all_df['bounced'].sum():,}", flush=True)

    report(all_df)
    all_df.to_csv("boof53_clean_all.csv", index=False)
    print(f"\n  Saved boof53_clean_all.csv")
