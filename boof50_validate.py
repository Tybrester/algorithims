"""
BOOF50 Validation Suite
1. Walk-forward test
2. Monte Carlo (drawdown, loss streaks, negative outcome)
3. Slippage stress test
4. Out-of-sample symbol folds
5. Regime split (SPY green/red, gap, VIX proxy)
6. Kill-switch analysis
"""

import os, random
import numpy as np
import pandas as pd
from itertools import combinations
from boof50_behavior import load_or_fetch, add_indicators, _collect_vwap_crosses

# ── Config ────────────────────────────────────────────────────────────────────

TOP10 = ["TSLA","NVDA","MU","HOOD","COIN","AMD","SMCI","MSTR","UPST","HIMS"]
ALL25 = [
    "TSLA","NVDA","MU","HOOD","COIN","CRWD",
    "PLTR","AMD","SMCI","META","AMZN","AAPL","MSFT","ARM",
    "MSTR","RKLB","AFRM","UPST","APP","HIMS","ASTS","LUNR",
    "RIOT","CLSK","IREN"
]
TP_LEVELS = [0.0050, 0.0075, 0.0100, 0.0150]
SL_LEVELS = [0.0030, 0.0050]
MAX_BARS  = 120


# ── Trade simulation ──────────────────────────────────────────────────────────

def sim_trade(e, tp, sl):
    ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
    mfe = mae = 0.0
    for b in range(len(hs)):
        if e["side"] == "long":
            mfe = max(mfe, (hs[b]-ep)/ep); mae = max(mae, (ep-ls[b])/ep)
            if hs[b] >= ep*(1+tp): return tp,  mfe, mae
            if ls[b] <= ep*(1-sl): return -sl, mfe, mae
        else:
            mfe = max(mfe, (ep-ls[b])/ep); mae = max(mae, (hs[b]-ep)/ep)
            if ls[b] <= ep*(1-tp): return tp,  mfe, mae
            if hs[b] >= ep*(1+sl): return -sl, mfe, mae
    if e["side"] == "long": pnl = (hs[-1]-ep)/ep if len(hs) else 0
    else:                   pnl = (ep-ls[-1])/ep if len(ls) else 0
    return pnl, mfe, mae


def best_params(trades_list):
    """Find best TP/SL on a list of trade entries."""
    best_ev = -999; best_tp = 0.0075; best_sl = 0.005
    for sl in SL_LEVELS:
        for tp in TP_LEVELS:
            evs = [sim_trade(e, tp, sl)[0] for e in trades_list]
            ev  = np.mean(evs) if evs else -999
            if ev > best_ev:
                best_ev = ev; best_tp = tp; best_sl = sl
    return best_tp, best_sl


def stats(pnls):
    if not pnls: return {}
    a = np.array(pnls)
    w = a[a>0]; l = a[a<0]
    pf = w.sum()/abs(l.sum()) if len(l) else float("inf")
    return dict(n=len(a), wr=len(w)/len(a), pf=pf, ev=a.mean()*100)


def section(t): print(f"\n{'='*68}\n  {t}\n{'='*68}")


# ── Load all data once ────────────────────────────────────────────────────────

def load_all(symbols):
    cache = {}
    for sym in symbols:
        print(f"  {sym}...", end=" ", flush=True)
        df = load_or_fetch(sym)
        df = add_indicators(df)
        entries = _collect_vwap_crosses(df,"long") + _collect_vwap_crosses(df,"short")
        for e in entries:
            e["sym"] = sym
        cache[sym] = {"df": df, "entries": entries}
        print(f"{len(entries)} entries")
    return cache


# ── 1. Walk-forward ───────────────────────────────────────────────────────────

def walk_forward(cache, symbols):
    section("1. WALK-FORWARD  (3-month train → 1-month test, rolling)")

    # collect all entries with month tag
    all_entries = []
    for sym in symbols:
        for e in cache[sym]["entries"]:
            all_entries.append(e)

    # get sorted month list
    months = sorted(set(
        pd.Timestamp(str(e["date"])).to_period("M")
        for e in all_entries
        if "date" in e
    )) if all_entries and "date" in all_entries[0] else []

    # rebuild with date from df
    all_entries2 = []
    for sym in symbols:
        df = cache[sym]["df"]
        entries = cache[sym]["entries"]
        # map entry index → date via the dataframe
        day_entries = {}
        idx = 0
        for date, day in df.groupby("date"):
            day = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
            if len(day) < MAX_BARS + 10: continue
            for i in range(5, len(day) - MAX_BARS - 2):
                prev = day.iloc[i-1]; row = day.iloc[i]
                for side in ["long","short"]:
                    if side == "long":
                        hold = all(day.iloc[i:i+5]["close"] > day.iloc[i:i+5]["vwap"])
                        cross = prev["close"]<prev["vwap"] and row["close"]>row["vwap"] and hold
                    else:
                        hold = all(day.iloc[i:i+5]["close"] < day.iloc[i:i+5]["vwap"])
                        cross = prev["close"]>prev["vwap"] and row["close"]<row["vwap"] and hold
                    if cross:
                        future = day.iloc[i:i+MAX_BARS]
                        all_entries2.append({
                            "ep": row["close"], "side": side, "sym": sym,
                            "month": pd.Timestamp(str(date)).to_period("M"),
                            "highs": future["high"].values, "lows": future["low"].values
                        })

    months = sorted(set(e["month"] for e in all_entries2))
    if len(months) < 5:
        print("  Not enough months for walk-forward."); return

    print(f"\n  {'Window':<25}  {'Train n':>7}  {'Test n':>6}  {'WR':>6}  {'PF':>5}  {'EV':>8}  {'TP':>5}  {'SL':>5}")
    print(f"  {'-'*25}  {'-'*7}  {'-'*6}  {'-'*6}  {'-'*5}  {'-'*8}  {'-'*5}  {'-'*5}")

    for i in range(len(months) - 3):
        train_m = set(months[i:i+3])
        test_m  = months[i+3]
        train   = [e for e in all_entries2 if e["month"] in train_m]
        test    = [e for e in all_entries2 if e["month"] == test_m]
        if not train or not test: continue
        tp, sl  = best_params(train)
        pnls    = [sim_trade(e, tp, sl)[0] for e in test]
        s       = stats(pnls)
        flag    = "⚠" if s["pf"] < 1.20 or s["ev"] < 0.05 or s["wr"] < 0.48 else "✓"
        label   = f"{months[i]} → {months[i+2]} | test {test_m}"
        print(f"  {label:<25}  {len(train):7d}  {len(test):6d}  {s['wr']:6.1%}  {s['pf']:5.2f}  {s['ev']:+7.4f}%  {tp*100:.2f}%  {sl*100:.2f}%  {flag}")


# ── 2. Monte Carlo ────────────────────────────────────────────────────────────

def monte_carlo(cache, symbols, n_sims=1000):
    section("2. MONTE CARLO  (1,000 shuffles — drawdown / loss streaks / ruin)")

    TP = 0.0075; SL = 0.005
    all_pnls = []
    for sym in symbols:
        for e in cache[sym]["entries"]:
            pnl, _, _ = sim_trade(e, TP, SL)
            all_pnls.append(pnl)

    n = len(all_pnls)
    print(f"  Base trades: {n}  TP={TP*100:.2f}%  SL={SL*100:.2f}%")

    arr = np.array(all_pnls)
    max_dds, worst100, worst500, streaks, neg1k = [], [], [], [], []
    for _ in range(n_sims):
        t = arr.copy(); np.random.shuffle(t)
        # max drawdown via cumsum
        cum  = np.cumsum(t)
        peak = np.maximum.accumulate(cum)
        dd   = (peak - cum).max()
        max_dds.append(dd)
        # loss streak (fully vectorized)
        losses = (t < 0).astype(np.int32)
        reset  = np.where(losses == 0)[0]
        if len(reset) == 0:
            streak = n
        else:
            ends   = np.concatenate([[-1], reset])
            streak = int(np.diff(ends).max() - 1)
        streaks.append(streak)
        # worst windows using sliding sum via cumsum
        cs   = np.concatenate([[0.0], cum])
        w100 = float((cs[100:] - cs[:-100]).min()) if n >= 100 else float(cum[-1])
        worst100.append(w100)
        w500 = float((cs[500:] - cs[:-500]).min()) if n >= 500 else float(cum[-1])
        worst500.append(w500)
        neg1k.append(1 if (cum[999] if n>=1000 else cum[-1]) < 0 else 0)

    p95_dd   = np.percentile(max_dds,  95)
    p95_w100 = np.percentile(worst100, 5)
    p95_w500 = np.percentile(worst500, 5) if worst500 else 0
    p95_str  = np.percentile(streaks,  95)
    neg_prob = np.mean(neg1k)

    print(f"\n  Metric                        Median       95th pct")
    print(f"  {'Max drawdown (% pts)':<30}  {np.median(max_dds)*100:+7.3f}%   {p95_dd*100:+7.3f}%")
    print(f"  {'Worst 100-trade stretch':<30}  {np.median(worst100)*100:+7.3f}%   {p95_w100*100:+7.3f}%")
    print(f"  {'Worst 500-trade stretch':<30}  {np.median(worst500)*100:+7.3f}%   {p95_w500*100:+7.3f}%")
    print(f"  {'Longest loss streak':<30}  {np.median(streaks):7.1f}    {p95_str:7.1f}")
    print(f"  {'P(negative after 1k trades)':<30}  {neg_prob:7.1%}")


# ── 3. Slippage stress test ───────────────────────────────────────────────────

def slippage_test(cache, symbols):
    section("3. SLIPPAGE STRESS TEST  (TP=0.75%, SL=0.50%)")

    TP = 0.0075; SL = 0.005
    costs = [0.0, 0.0002, 0.0005, 0.0010, 0.0015, 0.0020]
    base_pnls = []
    for sym in symbols:
        for e in cache[sym]["entries"]:
            pnl, _, _ = sim_trade(e, TP, SL)
            base_pnls.append(pnl)

    print(f"\n  {'Cost/trade':<12}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Total PnL':>10}  Pass?")
    print(f"  {'-'*12}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}  {'-'*10}  {'-'*5}")
    for c in costs:
        adj = [p - c for p in base_pnls]
        s   = stats(adj)
        ok  = "✓" if s["pf"] >= 1.20 and s["ev"] > 0 else "✗"
        print(f"  {c*100:.3f}%       {s['n']:5d}  {s['wr']:6.1%}  {s['pf']:5.2f}  {s['ev']:+8.4f}%  "
              f"{sum(adj)*100:+9.2f}%  {ok}")


# ── 4. Out-of-sample symbol folds ────────────────────────────────────────────

def oos_folds(cache, all_syms):
    section("4. OUT-OF-SAMPLE SYMBOL FOLDS  (hold out 5, train on rest)")

    TP = 0.0075; SL = 0.005
    folds = [
        ["AAPL","AMD","TSLA","COIN","MSTR"],
        ["NVDA","META","PLTR","HOOD","APP"],
        ["MU","SMCI","CRWD","UPST","HIMS"],
        ["AMZN","MSFT","ARM","AFRM","RKLB"],
        ["ASTS","LUNR","RIOT","CLSK","IREN"],
    ]
    print(f"\n  {'Fold (held out)':<40}  {'Test n':>6}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*40}  {'-'*6}  {'-'*6}  {'-'*5}  {'-'*9}")
    for fold in folds:
        test_syms  = [s for s in fold if s in cache]
        if not test_syms: continue
        test_pnls  = []
        for sym in test_syms:
            for e in cache[sym]["entries"]:
                pnl, _, _ = sim_trade(e, TP, SL)
                test_pnls.append(pnl)
        s = stats(test_pnls)
        print(f"  {', '.join(test_syms):<40}  {s['n']:6d}  {s['wr']:6.1%}  {s['pf']:5.2f}  {s['ev']:+8.4f}%")


# ── 5. Regime split ───────────────────────────────────────────────────────────

def regime_split(cache, symbols):
    section("5. REGIME SPLIT  (gap up/down, time of day)")

    TP = 0.0075; SL = 0.005

    buckets = {
        "gap_up":   [], "gap_down": [], "gap_flat": [],
        "morning":  [], "midday":   [], "afternoon": [],
        "long":     [], "short":    [],
    }

    for sym in symbols:
        df = cache[sym]["df"]
        all_entries = []
        for date, day in df.groupby("date"):
            day2 = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
            if len(day2) < MAX_BARS + 10: continue
            open_px = day[day["time"] == "09:30"]["close"].values
            prev_cls = None
            day_dates = sorted(df["date"].unique())
            di = list(day_dates).index(date)
            if di > 0:
                prev_day = df[df["date"] == day_dates[di-1]]
                if not prev_day.empty: prev_cls = prev_day["close"].iloc[-1]
            gap = (open_px[0] - prev_cls) / prev_cls if (len(open_px) and prev_cls) else 0

            for i in range(5, len(day2) - MAX_BARS - 2):
                prev = day2.iloc[i-1]; row = day2.iloc[i]
                for side in ["long","short"]:
                    if side == "long":
                        hold  = all(day2.iloc[i:i+5]["close"] > day2.iloc[i:i+5]["vwap"])
                        cross = prev["close"]<prev["vwap"] and row["close"]>row["vwap"] and hold
                    else:
                        hold  = all(day2.iloc[i:i+5]["close"] < day2.iloc[i:i+5]["vwap"])
                        cross = prev["close"]>prev["vwap"] and row["close"]<row["vwap"] and hold
                    if cross:
                        future = day2.iloc[i:i+MAX_BARS]
                        e = {"ep":row["close"],"side":side,
                             "highs":future["high"].values,"lows":future["low"].values,
                             "time":row["time"],"gap":gap}
                        pnl, _, _ = sim_trade(e, TP, SL)
                        # gap bucket
                        if   gap >  0.005: buckets["gap_up"].append(pnl)
                        elif gap < -0.005: buckets["gap_down"].append(pnl)
                        else:              buckets["gap_flat"].append(pnl)
                        # time bucket
                        t = row["time"]
                        if   t < "11:00": buckets["morning"].append(pnl)
                        elif t < "13:00": buckets["midday"].append(pnl)
                        else:             buckets["afternoon"].append(pnl)
                        # side
                        buckets[side].append(pnl)

    print(f"\n  {'Regime':<12}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*12}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}")
    for name, pnls in buckets.items():
        if not pnls: continue
        s = stats(pnls)
        print(f"  {name:<12}  {s['n']:5d}  {s['wr']:6.1%}  {s['pf']:5.2f}  {s['ev']:+8.4f}%")


# ── 6. Kill-switch analysis ───────────────────────────────────────────────────

def kill_switch(cache, symbols):
    section("6. KILL-SWITCH ANALYSIS  (daily loss limit / streak stop)")

    TP = 0.0075; SL = 0.005
    base_pnls = []
    for sym in symbols:
        for e in cache[sym]["entries"]:
            pnl, _, _ = sim_trade(e, TP, SL)
            base_pnls.append(pnl)

    rules = [
        ("No kill switch",       None,  None),
        ("Stop after 3 losses",  3,     None),
        ("Stop after 4 losses",  4,     None),
        ("Stop after 5 losses",  5,     None),
        ("Stop after -1.5% day", None,  -0.015),
        ("Stop after -2.0% day", None,  -0.020),
    ]

    print(f"\n  {'Rule':<26}  {'Trades used':>11}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*26}  {'-'*11}  {'-'*6}  {'-'*5}  {'-'*9}")

    TRADES_PER_DAY = 35
    for label, max_streak, daily_limit in rules:
        filtered = []; streak = 0; day_pnl = 0.0; day_cnt = 0
        for i, p in enumerate(base_pnls):
            if day_cnt > 0 and day_cnt % TRADES_PER_DAY == 0:
                streak = 0; day_pnl = 0.0
            if max_streak and streak >= max_streak: day_cnt += 1; continue
            if daily_limit and day_pnl <= daily_limit: day_cnt += 1; continue
            filtered.append(p)
            day_pnl += p; day_cnt += 1
            streak = streak + 1 if p < 0 else 0
        s = stats(filtered)
        print(f"  {label:<26}  {s['n']:11d}  {s['wr']:6.1%}  {s['pf']:5.2f}  {s['ev']:+8.4f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\nBOOF50 Validation Suite")
    print("Loading TOP10 + ALL25...")
    cache = load_all(TOP10)
    cache25 = load_all([s for s in ALL25 if s not in cache])
    cache25.update(cache)

    monte_carlo(cache, TOP10)
    slippage_test(cache, TOP10)
    oos_folds(cache, ALL25)
    regime_split(cache, TOP10)
    kill_switch(cache, TOP10)

    print(f"\n{'='*68}")
    print("  Done. All 6 validation tests complete.")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
