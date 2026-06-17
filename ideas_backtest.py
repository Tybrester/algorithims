"""
4-Idea Backtest
Idea 1: Retest entry (break level -> pull back to level -> hold -> buy)
Idea 2: Time filter (early 9:30-10:00 vs mid 10:00-14:00 vs late 14:00-16:00)
Idea 3: RVOL > 1.5 filter
Idea 4: Fixed hold time exits (30m, 1h, 2h, 3h)

Universe: MCap>100B, Vol>5M, ATR<5%, Gap>1%
Base scenario: TP=1%/SL=0.5% (best from previous run)
"""
import os, warnings
import pandas as pd
import numpy as np
from datetime import timedelta
warnings.filterwarnings("ignore")

DATA_DIR  = "data/1m"
TP        = 0.010
SL        = 0.005
RETEST_TOLERANCE = 0.002   # price must come within 0.2% of level to count as retest
RETEST_BARS      = 15      # max bars after break to wait for retest
RVOL_WINDOW      = 20      # days to compute avg volume for RVOL

# Filtered universe from previous run
UNIVERSE = [
    'AAPL','ABT','AMZN','APH','AXP','BAC','BKNG','CAT','CSCO','CVX',
    'FCX','GOOGL','HON','IBM','INTU','JNJ','JPM','KO','MDT','META',
    'MSFT','NFLX','NEE','NVDA','PG','RTX','SCHW','T','TSLA',
    'TXN','UNH','V','VZ','WMT','XOM','LRCX','GOOGL','GS','AVGO',
    'PLTR','GE','PCAR','TXN','UNP','CME','HON','BLK','ORCL','NOC'
]
UNIVERSE = list(set(UNIVERSE))

def rr_result(fut, ep):
    tp_price = ep * (1 + TP)
    sl_price = ep * (1 - SL)
    for _, bar in fut.iterrows():
        if bar["high"] >= tp_price: return "TP"
        if bar["low"]  <= sl_price: return "SL"
    return "EOD"

def fixed_hold_ret(fut, ep, minutes):
    bars = fut.iloc[:minutes]
    if len(bars) == 0:
        return None
    return float((bars.iloc[-1]["close"] - ep) / ep * 100)

def run_symbol(sym, df):
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    df.columns = [c.lower() for c in df.columns]

    df["_date"] = df.index.date
    grouped = {d: g.drop(columns="_date") for d, g in df.groupby("_date")}
    dates   = sorted(grouped.keys())

    # precompute daily avg volume for RVOL (rolling 20 sessions)
    daily_vol = {}
    for d, g in grouped.items():
        s = g.between_time("09:30","15:59")
        daily_vol[d] = s["volume"].sum() if len(s) else 0

    vol_series = pd.Series(daily_vol).sort_index()

    rows = []
    for i, cur_date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]

        prev_day  = grouped.get(prev_date, pd.DataFrame())
        prev_sess = prev_day.between_time("09:30","15:59") if len(prev_day) else prev_day
        pdh = prev_sess["high"].max() if len(prev_sess) else None

        cur_day = grouped.get(cur_date, pd.DataFrame())
        pre     = cur_day.between_time("04:00","09:29") if len(cur_day) else cur_day
        pmh     = pre["high"].max() if len(pre) else None

        sess = cur_day.between_time("09:30","15:59") if len(cur_day) else cur_day
        if len(sess) < 30:
            continue

        prev_close = prev_sess["close"].iloc[-1] if len(prev_sess) else None
        open_price = sess["open"].iloc[0]         if len(sess)      else None
        if prev_close is None or open_price is None:
            continue

        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct <= 1.0:
            continue

        gap_bucket = "gap_1_2" if gap_pct < 2.0 else "gap_2plus"

        # RVOL: today's volume vs 20-day avg
        idx_loc   = vol_series.index.get_loc(cur_date)
        past_vols = vol_series.iloc[max(0, idx_loc - RVOL_WINDOW):idx_loc]
        avg_vol   = past_vols.mean() if len(past_vols) > 0 else 0
        today_vol = daily_vol.get(cur_date, 0)
        rvol      = today_vol / avg_vol if avg_vol > 0 else 0

        # ── Find first break before noon ─────────────────────────────────────
        sess_morning = sess.between_time("09:30","12:00")
        break_bar    = None
        level_hit    = None
        level_val    = None

        for j in range(1, len(sess_morning)):
            prev_c = sess_morning.iloc[j-1]["close"]
            cur_c  = sess_morning.iloc[j]["close"]
            broke_pdh = (pdh is not None) and (prev_c <= pdh) and (cur_c > pdh)
            broke_pmh = (pmh is not None) and (prev_c <= pmh) and (cur_c > pmh)
            if broke_pdh or broke_pmh:
                ts  = sess_morning.index[j]
                pos = sess.index.get_loc(ts)
                if isinstance(pos, slice): pos = pos.start
                break_bar = pos
                if broke_pdh and broke_pmh:
                    level_hit, level_val = "BOTH", min(pdh, pmh)
                elif broke_pdh:
                    level_hit, level_val = "PDH", pdh
                else:
                    level_hit, level_val = "PMH", pmh
                break

        if break_bar is None:
            continue

        break_time = sess.index[break_bar]
        hour       = break_time.hour
        minute     = break_time.minute
        if hour < 10:
            time_bucket = "early"     # 9:30-10:00
        elif hour < 14:
            time_bucket = "mid"       # 10:00-14:00
        else:
            time_bucket = "late"      # 14:00-16:00

        # ── Idea 1: Retest entry ──────────────────────────────────────────────
        # After break, wait up to RETEST_BARS bars for price to pull back
        # within RETEST_TOLERANCE of level, then close back above it
        retest_ep      = None
        retest_bar_idx = None

        after_break = sess.iloc[break_bar+1 : break_bar+1+RETEST_BARS*3]
        state = "waiting_pullback"
        for k in range(len(after_break)):
            bar = after_break.iloc[k]
            if state == "waiting_pullback":
                # did it pull back to within tolerance of level?
                if bar["low"] <= level_val * (1 + RETEST_TOLERANCE):
                    state = "waiting_hold"
            elif state == "waiting_hold":
                # did it close back above level?
                if bar["close"] > level_val:
                    retest_ep      = bar["close"]
                    retest_bar_idx = break_bar + 1 + k
                    break
                # if it closes far below, retest failed
                if bar["close"] < level_val * (1 - RETEST_TOLERANCE * 2):
                    break

        # ── Standard (immediate) entry ────────────────────────────────────────
        std_ep  = sess.iloc[break_bar]["close"]
        std_fut = sess.iloc[break_bar+1:].copy()
        std_res = rr_result(std_fut, std_ep)
        std_ret = (TP*100) if std_res=="TP" else ((-SL*100) if std_res=="SL" else
                   float((sess.iloc[-1]["close"]-std_ep)/std_ep*100) if len(std_fut) else 0)

        # fixed hold returns for standard entry
        h30  = fixed_hold_ret(std_fut, std_ep, 30)
        h60  = fixed_hold_ret(std_fut, std_ep, 60)
        h120 = fixed_hold_ret(std_fut, std_ep, 120)
        h180 = fixed_hold_ret(std_fut, std_ep, 180)

        # ── Retest entry stats ────────────────────────────────────────────────
        if retest_ep is not None:
            rt_fut = sess.iloc[retest_bar_idx+1:].copy()
            rt_res = rr_result(rt_fut, retest_ep)
            rt_ret = (TP*100) if rt_res=="TP" else ((-SL*100) if rt_res=="SL" else
                      float((sess.iloc[-1]["close"]-retest_ep)/retest_ep*100) if len(rt_fut) else 0)
        else:
            rt_res = None
            rt_ret = None

        rows.append({
            "sym":         sym,
            "date":        str(cur_date),
            "gap_pct":     round(gap_pct, 3),
            "gap_bucket":  gap_bucket,
            "level":       level_hit,
            "time_bucket": time_bucket,
            "break_time":  break_time.strftime("%H:%M"),
            "rvol":        round(rvol, 2),
            # standard entry
            "std_result":  std_res,
            "std_ret":     round(std_ret, 4),
            # hold time
            "ret_30m":     round(h30, 3)  if h30  is not None else None,
            "ret_1h":      round(h60, 3)  if h60  is not None else None,
            "ret_2h":      round(h120, 3) if h120 is not None else None,
            "ret_3h":      round(h180, 3) if h180 is not None else None,
            # retest entry
            "retest_found":int(retest_ep is not None),
            "rt_result":   rt_res,
            "rt_ret":      round(rt_ret, 4) if rt_ret is not None else None,
        })
    return rows

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"Running 4-idea backtest on {len(UNIVERSE)} symbols...\n")
all_rows = []
for i, sym in enumerate(sorted(UNIVERSE), 1):
    fname = os.path.join(DATA_DIR, f"{sym}.parquet")
    if not os.path.exists(fname):
        continue
    try:
        raw  = pd.read_parquet(fname)
        rows = run_symbol(sym, raw)
        all_rows.extend(rows)
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: {len(rows)} days")
    except Exception as e:
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: ERROR {e}")

df = pd.DataFrame(all_rows)
df.to_csv("ideas_backtest_results.csv", index=False)
print(f"\nTotal: {len(df)} trades | {df.sym.nunique()} symbols\n")

# ── Helper ────────────────────────────────────────────────────────────────────
def rr_stats(sub, res_col, ret_col, label):
    if len(sub) == 0:
        return
    tp_n  = (sub[res_col]=="TP").sum()
    sl_n  = (sub[res_col]=="SL").sum()
    n     = len(sub)
    wr    = tp_n/(tp_n+sl_n)*100 if tp_n+sl_n else 0
    ev    = sub[ret_col].mean()
    wins  = sub[sub[ret_col]>0][ret_col].sum()
    loss  = sub[sub[ret_col]<0][ret_col].abs().sum()
    pf    = wins/loss if loss else 999.0
    tot   = sub[ret_col].sum()
    print(f"  {label:<30} N={n:>4}  TP={tp_n/n*100:>5.1f}%  SL={sl_n/n*100:>5.1f}%  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%")

# ── IDEA 1: Retest entry ──────────────────────────────────────────────────────
print("="*80)
print("IDEA 1 — RETEST ENTRY (break -> pullback to level -> hold above -> buy)")
print("="*80)
retest_found = df[df.retest_found == 1].dropna(subset=["rt_ret"])
print(f"  Retest found: {len(retest_found)}/{len(df)} ({len(retest_found)/len(df)*100:.1f}% of breakouts)")
rr_stats(df,          "std_result", "std_ret", "Standard entry (all)")
rr_stats(retest_found,"rt_result",  "rt_ret",  "Retest entry (retest found)")
rr_stats(df[df.retest_found==1], "std_result","std_ret","Standard on same days as retest")

# ── IDEA 2: Time filter ───────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("IDEA 2 — TIME FILTER")
print("="*80)
for tb, lbl in [("early","Early  9:30-10:00"),("mid","Mid   10:00-14:00"),("late","Late  14:00-16:00")]:
    rr_stats(df[df.time_bucket==tb], "std_result","std_ret", lbl)

# ── IDEA 3: RVOL filter ───────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("IDEA 3 — RELATIVE VOLUME FILTER")
print("="*80)
for rmin, rmax, lbl in [(0,1.0,"RVOL < 1.0"),(1.0,1.5,"RVOL 1.0-1.5"),(1.5,2.0,"RVOL 1.5-2.0"),(2.0,99,"RVOL > 2.0")]:
    sub = df[(df.rvol >= rmin) & (df.rvol < rmax)]
    rr_stats(sub, "std_result","std_ret", lbl)

# combined: RVOL > 1.5
print()
rr_stats(df[df.rvol >= 1.5], "std_result","std_ret","RVOL >= 1.5 (combined)")
rr_stats(df[df.rvol <  1.5], "std_result","std_ret","RVOL <  1.5 (combined)")

# ── IDEA 4: Hold time study ───────────────────────────────────────────────────
print(f"\n{'='*80}")
print("IDEA 4 — FIXED HOLD TIME EXITS")
print("="*80)
for col, lbl in [("ret_30m","30 min"),("ret_1h","1 hour"),("ret_2h","2 hour"),("ret_3h","3 hour")]:
    sub = df.dropna(subset=[col])
    wins = (sub[col]>0).sum()
    n    = len(sub)
    ev   = sub[col].mean()
    med  = sub[col].median()
    w    = sub[sub[col]>0][col].sum()
    l    = sub[sub[col]<0][col].abs().sum()
    pf   = w/l if l else 999.0
    tot  = sub[col].sum()
    print(f"  {lbl:<10}  N={n:>4}  WR={wins/n*100:>5.1f}%  AvgRet={ev:>+6.3f}%  Median={med:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%")

# ── Best combo: Early + RVOL>1.5 ─────────────────────────────────────────────
print(f"\n{'='*80}")
print("BEST COMBOS")
print("="*80)
for tb in ["early","mid","late"]:
    for rv_min in [0, 1.5]:
        lbl = f"Time={tb} + RVOL>={rv_min}"
        sub = df[(df.time_bucket==tb) & (df.rvol >= rv_min)]
        rr_stats(sub, "std_result","std_ret", lbl)

print(f"\n{'='*80}")
print("RETEST + EARLY + RVOL>1.5")
print("="*80)
sub = retest_found[(retest_found.time_bucket=="early") & (retest_found.rvol >= 1.5)]
rr_stats(sub, "rt_result","rt_ret","Retest + Early + RVOL>=1.5")
sub2 = retest_found[(retest_found.time_bucket=="early")]
rr_stats(sub2,"rt_result","rt_ret","Retest + Early (any RVOL)")
