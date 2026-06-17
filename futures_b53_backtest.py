"""
Futures BOOF53 Backtest — ES & NQ
===================================
Levels  : Globex High/Low, Prior RTH High/Low, OR15 High/Low, VWAP
Setups  : Reject (fade level), Breakout (break + retest level)
Exits   : ES  TP8/SL4  and  TP12/SL6  (points)
          NQ  TP25/SL12 and TP40/SL20 (points)
Output  : Setup | Level | Time Window | N | WR | PF | EV | MaxDD
Data    : Databento GLBX.MDP3 ohlcv-1m, cached to parquet
"""

import os, datetime, itertools
import pandas as pd
import numpy as np
import databento as db

# ── CONFIG ─────────────────────────────────────────────────────────────────────
API_KEY    = "db-XQu7u6hK8LA7rw5kPYdFNbmdMdNwU"
START      = "2025-06-01"
END        = "2026-06-01"
CACHE_ES   = "futures_cache_ES.parquet"
CACHE_NQ   = "futures_cache_NQ.parquet"

EXIT_CONFIGS = {
    "ES": [("TP8_SL4",  8,  4), ("TP12_SL6", 12, 6)],
    "NQ": [("TP25_SL12", 25, 12), ("TP40_SL20", 40, 20)],
}

NEAR_PCT   = 0.0010   # 0.10% to count as "touching" level
BOUNCE_PCT = 0.0005   # 0.05% minimum bounce/break to confirm

RTH_START  = datetime.time(9, 30)
RTH_END    = datetime.time(16, 0)
GLOBEX_START = datetime.time(18, 0)   # prior day Globex open

# ── FETCH / CACHE ──────────────────────────────────────────────────────────────
def fetch_or_load(sym_code, cache_path):
    if os.path.exists(cache_path):
        print(f"Loading {sym_code} from cache: {cache_path}")
        df = pd.read_parquet(cache_path)
        return df

    print(f"Fetching {sym_code} from Databento ({START} -> {END})...")
    client = db.Historical(API_KEY)
    data   = client.timeseries.get_range(
        dataset   = "GLBX.MDP3",
        symbols   = [sym_code],
        schema    = "ohlcv-1m",
        start     = START,
        end       = END,
        stype_in  = "continuous",
    )
    df = data.to_df()
    df.index = pd.to_datetime(df.index).tz_convert("America/New_York")
    df = df.rename(columns={"open":"o","high":"h","low":"l","close":"c","volume":"v"})
    df = df[["o","h","l","c","v"]]
    df.to_parquet(cache_path)
    print(f"  Saved to {cache_path}  rows={len(df)}")
    return df


# ── VWAP ───────────────────────────────────────────────────────────────────────
def compute_vwap(day_df):
    tp  = (day_df["h"] + day_df["l"] + day_df["c"]) / 3
    cum_tpv = (tp * day_df["v"]).cumsum()
    cum_v   = day_df["v"].cumsum()
    return cum_tpv / cum_v.replace(0, np.nan)


# ── LEVEL BUILDER ──────────────────────────────────────────────────────────────
def build_levels(day_df, prev_rth_high, prev_rth_low, globex_high, globex_low, or15_high, or15_low, vwap_series):
    levels = {}
    if globex_high:   levels["GlobexHigh"] = globex_high
    if globex_low:    levels["GlobexLow"]  = globex_low
    if prev_rth_high: levels["PriorRTHHigh"] = prev_rth_high
    if prev_rth_low:  levels["PriorRTHLow"]  = prev_rth_low
    if or15_high:     levels["OR15High"] = or15_high
    if or15_low:      levels["OR15Low"]  = or15_low
    return levels


# ── SIGNAL DETECTION ───────────────────────────────────────────────────────────
def detect_signals(rth_df, levels, vwap_series):
    """
    Returns list of signals:
      {bar_idx, level_name, level_price, setup, entry_bar_idx, entry_price}
    setup = 'reject' or 'breakout'
    """
    signals = []
    used_levels = set()

    bars = rth_df.reset_index()
    n    = len(bars)

    level_state  = {k: "idle"  for k in levels}
    level_extreme = {k: None   for k in levels}

    for i in range(1, n - 1):
        bar = bars.iloc[i]
        hi  = bar["h"]; lo = bar["l"]; cl = bar["c"]
        t   = bar["ts_event"] if "ts_event" in bar else bar.name

        # Add VWAP as a dynamic level each bar
        vwap_val = vwap_series.iloc[i] if i < len(vwap_series) else None

        all_levels = dict(levels)
        if vwap_val and not np.isnan(vwap_val):
            all_levels["VWAP"] = vwap_val

        for lname, lpx in all_levels.items():
            if lname in used_levels:
                continue

            near   = lpx * NEAR_PCT
            st     = level_state.get(lname, "idle")

            # ── REJECT setup: price touches level from above, bounces down
            touching = (abs(hi - lpx) <= near) or (hi >= lpx >= lo)

            if st == "idle" and touching:
                level_state[lname]   = "touch"
                level_extreme[lname] = hi

            elif st == "touch":
                if hi > level_extreme[lname]:
                    level_extreme[lname] = hi
                bounce_down = (level_extreme[lname] - cl) / level_extreme[lname]
                if bounce_down >= BOUNCE_PCT and i + 1 < n:
                    entry_bar   = bars.iloc[i + 1]
                    entry_price = entry_bar["o"]
                    signals.append({
                        "bar_idx":    i,
                        "level_name": lname,
                        "level_px":   lpx,
                        "setup":      "reject",
                        "entry_idx":  i + 1,
                        "entry_px":   entry_price,
                        "direction":  "short",
                    })
                    used_levels.add(lname)
                    level_state[lname] = "done"
                    continue
                # Reset if price moves too far above
                if lo > lpx * (1 + NEAR_PCT * 2):
                    level_state[lname] = "idle"

            # ── BREAKOUT setup: price breaks above level, retests from above
            broke_above = cl > lpx * (1 + NEAR_PCT) and lo < lpx * (1 + NEAR_PCT * 3)
            if lname + "_bo" not in used_levels:
                retest_state = level_state.get(lname + "_bo", "idle")
                if retest_state == "idle" and broke_above:
                    level_state[lname + "_bo"] = "broke"
                elif retest_state == "broke":
                    retest_near = (abs(lo - lpx) <= near * 2)
                    if retest_near and i + 1 < n:
                        entry_bar   = bars.iloc[i + 1]
                        entry_price = entry_bar["o"]
                        signals.append({
                            "bar_idx":    i,
                            "level_name": lname,
                            "level_px":   lpx,
                            "setup":      "breakout",
                            "entry_idx":  i + 1,
                            "entry_px":   entry_price,
                            "direction":  "long",
                        })
                        used_levels.add(lname + "_bo")
                        level_state[lname + "_bo"] = "done"

    return signals


# ── SIMULATE EXITS ─────────────────────────────────────────────────────────────
def simulate_exit(rth_df, entry_idx, direction, tp_pts, sl_pts):
    bars = rth_df.reset_index()
    entry_px = bars.iloc[entry_idx]["o"]
    if direction == "short":
        tp_px = entry_px - tp_pts
        sl_px = entry_px + sl_pts
    else:
        tp_px = entry_px + tp_pts
        sl_px = entry_px - sl_pts

    for i in range(entry_idx, len(bars)):
        bar = bars.iloc[i]
        if direction == "short":
            if bar["l"] <= tp_px: return "TP", tp_pts,  i - entry_idx
            if bar["h"] >= sl_px: return "SL", -sl_pts, i - entry_idx
        else:
            if bar["h"] >= tp_px: return "TP", tp_pts,  i - entry_idx
            if bar["l"] <= sl_px: return "SL", -sl_pts, i - entry_idx

    # EOD exit at last close
    eod_px  = bars.iloc[-1]["c"]
    eod_pnl = (entry_px - eod_px) if direction == "short" else (eod_px - entry_px)
    return "EOD", eod_pnl, len(bars) - entry_idx


# ── TIME BUCKET ────────────────────────────────────────────────────────────────
def time_bucket(t):
    hm = t.hour * 60 + t.minute
    if hm < 9*60+45:   return "09:30-09:45"
    if hm < 10*60:     return "09:45-10:00"
    if hm < 10*60+30:  return "10:00-10:30"
    if hm < 11*60:     return "10:30-11:00"
    if hm < 12*60:     return "11:00-12:00"
    if hm < 14*60:     return "12:00-14:00"
    return "14:00-close"


# ── MAIN BACKTEST ──────────────────────────────────────────────────────────────
def run_backtest(sym, df, exit_configs):
    df = df.sort_index()
    all_trades = []
    days = sorted(df.index.normalize().unique())

    prev_rth_high = None
    prev_rth_low  = None
    globex_high   = None
    globex_low    = None

    for day in days:
        day_dt = pd.Timestamp(day)
        if day_dt.weekday() >= 5: continue

        day_mask = df.index.normalize() == day_dt.normalize()
        day_df   = df[day_mask]
        if len(day_df) < 20: continue

        # ── Globex session (prior 18:00 -> 09:29)
        globex_mask = (day_df.index.time >= datetime.time(18, 0)) | \
                      (day_df.index.time < RTH_START)
        globex_df   = day_df[globex_mask]
        if len(globex_df) > 0:
            globex_high = globex_df["h"].max()
            globex_low  = globex_df["l"].min()

        # ── RTH session
        rth_mask = (day_df.index.time >= RTH_START) & (day_df.index.time < RTH_END)
        rth_df   = day_df[rth_mask]
        if len(rth_df) < 10: continue

        # ── OR15 (first 15 min of RTH)
        or15_df   = rth_df[rth_df.index.time < datetime.time(9, 45)]
        or15_high = or15_df["h"].max() if len(or15_df) > 0 else None
        or15_low  = or15_df["l"].min() if len(or15_df) > 0 else None

        # ── VWAP
        vwap_series = compute_vwap(rth_df)

        # ── Build levels
        levels = build_levels(
            rth_df, prev_rth_high, prev_rth_low,
            globex_high, globex_low,
            or15_high, or15_low, vwap_series
        )

        # ── Detect signals
        signals = detect_signals(rth_df, levels, vwap_series)

        # ── Simulate exits for each exit config
        for sig in signals:
            entry_idx = sig["entry_idx"]
            if entry_idx >= len(rth_df): continue
            entry_time = rth_df.index[min(entry_idx, len(rth_df)-1)]
            tb = time_bucket(entry_time)

            for cfg_name, tp_pts, sl_pts in exit_configs:
                result, pnl, bars_held = simulate_exit(
                    rth_df, entry_idx, sig["direction"], tp_pts, sl_pts
                )
                all_trades.append({
                    "date":       str(day_dt.date()),
                    "sym":        sym,
                    "level":      sig["level_name"],
                    "setup":      sig["setup"],
                    "direction":  sig["direction"],
                    "exit_cfg":   cfg_name,
                    "tp":         tp_pts,
                    "sl":         sl_pts,
                    "entry_px":   sig["entry_px"],
                    "result":     result,
                    "pnl_pts":    pnl,
                    "bars_held":  bars_held,
                    "time_bucket": tb,
                })

        # ── Save RTH high/low for next day
        prev_rth_high = rth_df["h"].max()
        prev_rth_low  = rth_df["l"].min()

    return pd.DataFrame(all_trades)


# ── STATS ──────────────────────────────────────────────────────────────────────
def calc_stats(trades_df):
    if len(trades_df) == 0:
        return pd.DataFrame()

    rows = []
    groups = trades_df.groupby(["sym","setup","level","time_bucket","exit_cfg"])

    for (sym, setup, level, tb, cfg), grp in groups:
        n      = len(grp)
        wins   = grp["pnl_pts"] > 0
        wr     = wins.mean()
        gross_w = grp.loc[wins, "pnl_pts"].sum()
        gross_l = abs(grp.loc[~wins, "pnl_pts"].sum())
        pf     = gross_w / gross_l if gross_l > 0 else float("inf")
        ev     = grp["pnl_pts"].mean()

        # Max drawdown on cumulative PnL
        cum    = grp["pnl_pts"].cumsum()
        roll_max = cum.cummax()
        dd     = (cum - roll_max).min()

        rows.append({
            "Sym":         sym,
            "Setup":       setup,
            "Level":       level,
            "TimeWindow":  tb,
            "ExitCfg":     cfg,
            "N":           n,
            "WR%":         round(wr * 100, 1),
            "PF":          round(pf, 2),
            "EV_pts":      round(ev, 2),
            "MaxDD_pts":   round(dd, 2),
        })

    out = pd.DataFrame(rows)
    out = out.sort_values(["Sym","PF"], ascending=[True, False])
    return out


# ── RUN ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results_all = []

    for sym, cache in [("ES.c.0", CACHE_ES), ("NQ.c.0", CACHE_NQ)]:
        short_sym = "ES" if "ES" in sym else "NQ"
        df = fetch_or_load(sym, cache)
        print(f"\n{short_sym}: {len(df)} rows loaded")

        trades = run_backtest(short_sym, df, EXIT_CONFIGS[short_sym])
        print(f"  {short_sym}: {len(trades)} trades generated")

        csv_path = f"futures_trades_{short_sym}.csv"
        trades.to_csv(csv_path, index=False)
        print(f"  Saved trades -> {csv_path}")

        stats = calc_stats(trades)
        results_all.append(stats)

    final = pd.concat(results_all, ignore_index=True)
    final.to_csv("futures_b53_results.csv", index=False)

    print("\n" + "="*90)
    print(final.to_string(index=False))
    print("="*90)
    print("\nSaved -> futures_b53_results.csv")
