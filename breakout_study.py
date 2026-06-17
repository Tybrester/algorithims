"""
Breakout Study — PDH & PMH
Question: After price breaks above the level, how far does it go?
Measures max gain at 30m, 1hr, 2hr, 3hr, EOD from breakout bar.
No TP/SL — just raw price discovery after the break.
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

DATA_DIR = "data/1m"

def run(sym, df):
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    df.columns = [c.lower() for c in df.columns]

    # pre-group by date for speed
    df["_date"] = df.index.date
    grouped = {d: g.drop(columns="_date") for d, g in df.groupby("_date")}
    df = df.drop(columns="_date")

    dates = sorted(grouped.keys())
    rows = []

    for i, cur_date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]

        # PDH
        prev_day  = grouped.get(prev_date, pd.DataFrame())
        prev_sess = prev_day.between_time("09:30","15:59") if len(prev_day) else prev_day
        pdh = prev_sess["high"].max() if len(prev_sess) else None

        # PMH
        cur_day = grouped.get(cur_date, pd.DataFrame())
        pre     = cur_day.between_time("04:00","09:29") if len(cur_day) else cur_day
        pmh     = pre["high"].max() if len(pre) else None

        # session bars
        sess = cur_day.between_time("09:30","15:59") if len(cur_day) else cur_day
        if len(sess) < 30:
            continue

        # gap context
        prev_close = prev_sess["close"].iloc[-1] if len(prev_sess) else None
        open_price = sess["open"].iloc[0] if len(sess) else None
        gap_pct    = ((open_price - prev_close) / prev_close * 100) if (prev_close and open_price) else None

        for level_name, level in [("PDH", pdh), ("PMH", pmh)]:
            if level is None or np.isnan(level):
                continue

            # find first bar that closes above level before noon
            entry_bar = None
            sess_morning = sess.between_time("09:30", "12:00")
            for j in range(1, len(sess_morning)):
                if sess_morning.iloc[j-1]["close"] <= level and sess_morning.iloc[j]["close"] > level:
                    # find position in full session
                    ts = sess_morning.index[j]
                    entry_bar = sess.index.get_loc(ts)
                    if isinstance(entry_bar, slice):
                        entry_bar = entry_bar.start
                    break

            if entry_bar is None:
                continue

            ep  = sess.iloc[entry_bar]["close"]
            et  = sess.index[entry_bar]
            fut = sess.iloc[entry_bar+1:].copy()

            def _mg(mins, _f=fut, _ep=ep, _et=et):
                w = _f[_f.index <= _et + pd.Timedelta(minutes=mins)]
                return float((w["high"].max() - _ep) / _ep * 100) if len(w) else np.nan

            def _rt(mins, _f=fut, _ep=ep, _et=et):
                w = _f[_f.index <= _et + pd.Timedelta(minutes=mins)]
                return float((w.iloc[-1]["close"] - _ep) / _ep * 100) if len(w) else np.nan

            eod_ret = float((sess.iloc[-1]["close"] - ep) / ep * 100)
            eod_max = float((sess.iloc[entry_bar:]["high"].max() - ep) / ep * 100)

            # R:R scenarios — bar by bar, which hits first
            def rr_result(tp_pct, sl_pct, _f=fut, _ep=ep):
                tp = _ep * (1 + tp_pct)
                sl = _ep * (1 - sl_pct)
                for _, bar in _f.iterrows():
                    if bar["high"] >= tp:
                        return True   # TP hit first
                    if bar["low"] <= sl:
                        return False  # SL hit first
                return None  # neither hit by EOD

            rr_1_05  = rr_result(0.01, 0.005)   # +1% TP / -0.5% SL
            rr_2_1   = rr_result(0.02, 0.01)    # +2% TP / -1% SL

            open_above_level = (open_price is not None) and (open_price > level)
            rows.append({
                "sym":        sym,
                "date":       str(cur_date),
                "level":      level_name,
                "entry_time": et.strftime("%H:%M"),
                "gap_pct":    round(gap_pct, 3) if gap_pct is not None else None,
                "gapped_up":  (gap_pct is not None) and (gap_pct > 0.1),
                "open_above": open_above_level,
                "max_30m":    round(_mg(30),  3),
                "max_1hr":    round(_mg(60),  3),
                "max_2hr":    round(_mg(120), 3),
                "max_3hr":    round(_mg(180), 3),
                "max_eod":    round(eod_max,  3),
                "ret_30m":    round(_rt(30),  3),
                "ret_1hr":    round(_rt(60),  3),
                "ret_2hr":    round(_rt(120), 3),
                "ret_3hr":    round(_rt(180), 3),
                "ret_eod":    round(eod_ret,  3),
                "rr_1_05":    rr_1_05,
                "rr_2_1":     rr_2_1,
            })
    return rows

# ── Run ───────────────────────────────────────────────────────────────────────
files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")])
print(f"Studying breakouts across {len(files)} symbols...\n")

all_rows = []
for i, fname in enumerate(files, 1):
    sym = fname.replace(".parquet","")
    try:
        df = pd.read_parquet(os.path.join(DATA_DIR, fname))
        if len(df) < 500:
            continue
        rows = run(sym, df)
        all_rows.extend(rows)
        print(f"[{i}/{len(files)}] {sym}: {len(rows)} breakouts")
    except Exception as e:
        import traceback
        print(f"[{i}/{len(files)}] {sym}: ERROR {e}")
        traceback.print_exc()

df = pd.DataFrame(all_rows)
df.to_csv("breakout_study.csv", index=False)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"BREAKOUT STUDY — {len(df)} total breakouts, {df.sym.nunique()} symbols")
print(f"{'='*65}")

for level in ["PDH","PMH"]:
    sub = df[df.level == level]
    if len(sub) == 0:
        continue
    print(f"\n── {level} ({len(sub)} breakouts) ──────────────────────────────")
    print(f"  {'Metric':<14} {'30min':>8} {'1hr':>8} {'2hr':>8} {'3hr':>8} {'EOD':>8}")
    print(f"  {'-'*54}")
    for label, col in [("Max Gain %","max"), ("Close Ret %","ret")]:
        cols = [f"{col}_30m", f"{col}_1hr", f"{col}_2hr", f"{col}_3hr", f"{col}_eod"]
        vals = [sub[c].median() for c in cols]
        print(f"  {'Median '+label:<14} " + "  ".join(f"{v:>+6.2f}%" for v in vals))
        vals2 = [sub[c].mean() for c in cols]
        print(f"  {'Mean '+label:<14} " + "  ".join(f"{v:>+6.2f}%" for v in vals2))
    # win rate at each horizon
    print(f"  {'Win Rate':<14} ", end="")
    for col in ["ret_30m","ret_1hr","ret_2hr","ret_3hr","ret_eod"]:
        wr = (sub[col] > 0).mean() * 100
        print(f"  {wr:>5.1f}%", end="")
    print()
    # how far does it go
    print(f"\n  How far does it go (% of breakouts reaching target):")
    for pct in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
        hit_rate = (sub["max_eod"] >= pct).mean() * 100
        print(f"    Reaches +{pct:.1f}%:  {hit_rate:.1f}%")

    # gap slices
    print(f"\n  ── Gapped UP into breakout vs flat open ──")
    print(f"  {'Slice':<22} {'N':>5}  {'AvgRet1hr':>10}  {'AvgRet3hr':>10}  {'WR3hr':>7}  {'AvgMaxEOD':>10}")
    print(f"  {'-'*68}")
    for label, mask in [
        ("Gapped up >0.1%",   sub["gapped_up"] == True),
        ("Flat/down open",     sub["gapped_up"] == False),
        ("Open ABOVE level",   sub["open_above"] == True),
        ("Open BELOW level",   sub["open_above"] == False),
    ]:
        sl = sub[mask]
        if len(sl) < 5:
            continue
        avg1  = sl["ret_1hr"].mean()
        avg3  = sl["ret_3hr"].mean()
        wr3   = (sl["ret_3hr"] > 0).mean() * 100
        maxe  = sl["max_eod"].mean()
        print(f"  {label:<22} {len(sl):>5}  {avg1:>+9.2f}%  {avg3:>+9.2f}%  {wr3:>6.1f}%  {maxe:>+9.2f}%")

    # gap size buckets
    print(f"\n  ── Gap size vs outcome ──")
    print(f"  {'Gap bucket':<18} {'N':>5}  {'AvgRet3hr':>10}  {'WR3hr':>7}  {'AvgMaxEOD':>10}")
    print(f"  {'-'*55}")
    bins = [(-99,-0.1,"Gap down"),(-0.1,0.1,"Flat"),
            (0.1,0.5,"Gap +0.1-0.5%"),(0.5,1.0,"Gap +0.5-1%"),
            (1.0,2.0,"Gap +1-2%"),(2.0,99,"Gap >2%")]
    for lo, hi, lbl in bins:
        sl = sub[(sub["gap_pct"] >= lo) & (sub["gap_pct"] < hi)]
        if len(sl) < 5:
            continue
        avg3 = sl["ret_3hr"].mean()
        wr3  = (sl["ret_3hr"] > 0).mean() * 100
        maxe = sl["max_eod"].mean()
        print(f"  {lbl:<18} {len(sl):>5}  {avg3:>+9.2f}%  {wr3:>6.1f}%  {maxe:>+9.2f}%")

    # R:R scenarios
    print(f"\n  ── R:R Scenarios (hits TP before SL?) ──")
    for rr_col, lbl in [("rr_1_05","+1% TP / -0.5% SL  (2:1 R:R)"), ("rr_2_1","+2% TP / -1.0% SL  (2:1 R:R)")]:
        valid = sub[sub[rr_col].notna()]
        tp_hit = (valid[rr_col] == True).sum()
        sl_hit = (valid[rr_col] == False).sum()
        neither = sub[rr_col].isna().sum()
        wr = tp_hit / (tp_hit + sl_hit) * 100 if (tp_hit + sl_hit) > 0 else 0
        ev = (wr/100 * float(rr_col.split('_')[1])) - ((1-wr/100) * float(rr_col.split('_')[2]))
        print(f"  {lbl}")
        print(f"    TP hit: {tp_hit} ({tp_hit/(tp_hit+sl_hit+neither)*100:.1f}%)  SL hit: {sl_hit} ({sl_hit/(tp_hit+sl_hit+neither)*100:.1f}%)  Neither EOD: {neither} ({neither/(tp_hit+sl_hit+neither)*100:.1f}%)")
        print(f"    Win rate (TP vs SL only): {wr:.1f}%  |  EV per trade: {ev:+.4f}%")

print(f"\nSaved to breakout_study.csv")
