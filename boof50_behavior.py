"""
BOOF50 — Behavior Explorer
Runs 7 research questions on any symbol using cached or live Alpaca SIP data.
"""

import os
import numpy as np
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY    = "AKPDLKERTEC2OG42UROO65QMW7"
API_SECRET = "MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM"
SYMBOL     = "TSLA"
START      = "2025-06-13"
END        = "2026-06-13"
TZ         = "America/New_York"

client = StockHistoricalDataClient(API_KEY, API_SECRET)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_or_fetch(symbol: str) -> pd.DataFrame:
    cache = f"boof32_data_{symbol}.csv"
    if os.path.exists(cache):
        print(f"Loading cache: {cache}")
        df = pd.read_csv(cache, dtype_backend="numpy_nullable")
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(TZ)
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        for col in ["vwap","trade_count"]:
            if col in df.columns:
                df = df.drop(columns=[col])
        df = df.sort_values("timestamp").reset_index(drop=True)
        earliest = pd.Timestamp(df["timestamp"].min()).tz_convert(TZ)
        target   = pd.Timestamp(START, tz=TZ)
        if earliest > target + pd.Timedelta(days=1):
            print(f"  Cache starts {earliest.date()}, fetching back to {target.date()} via SIP...")
            extra = _fetch(symbol, target, earliest)
            if extra is not None and not extra.empty:
                df = pd.concat([extra, df], ignore_index=True)
                df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
                df.to_csv(cache, index=False)
                print(f"  Extended: {df['timestamp'].min().date()} → {df['timestamp'].max().date()}")
    else:
        print(f"No cache found, fetching {symbol} from Alpaca...")
        df = _fetch(symbol, pd.Timestamp(START, tz=TZ), pd.Timestamp(END, tz=TZ))

    df["date"] = df["timestamp"].dt.date
    df["time"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def _fetch(symbol, start, end) -> pd.DataFrame:
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        feed="sip",
    )
    bars = client.get_stock_bars(req).df
    if bars.empty:
        return bars
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.reset_index()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"]).dt.tz_convert(TZ)
    for col in ["vwap","trade_count"]:
        if col in bars.columns:
            bars = bars.drop(columns=[col])
    return bars.sort_values("timestamp").reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    typical       = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]      = typical * df["volume"]
    df["cum_pv"]  = df.groupby("date")["pv"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"]    = df["cum_pv"] / df["cum_vol"]
    avg_vol       = df.groupby("date")["volume"].transform(lambda x: x.rolling(20, min_periods=1).mean())
    df["rvol"]    = df["volume"] / avg_vol
    df["dist_vwap"]  = (df["close"] - df["vwap"])  / df["vwap"]
    df["dist_open"]  = df.groupby("date")["close"].transform(lambda x: (x - x.iloc[0]) / x.iloc[0])
    df["dist_high"]  = df.groupby("date")["high"].transform("cummax")
    df["dist_low"]   = df.groupby("date")["low"].transform("cummin")
    df["dist_from_high"] = (df["close"] - df["dist_high"])  / df["dist_high"]
    df["dist_from_low"]  = (df["close"] - df["dist_low"])   / df["dist_low"]
    return df


# ── Helpers ───────────────────────────────────────────────────────────────────

def price_at(day: pd.DataFrame, t: str):
    row = day[day["time"] == t]
    return float(row.iloc[0]["close"]) if not row.empty else None


def row_at(day: pd.DataFrame, t: str):
    row = day[day["time"] == t]
    return row.iloc[0] if not row.empty else None


def ret(a, b):
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a


def summarize(name: str, vals: list, indent: int = 2):
    vals = [x for x in vals if x is not None and not np.isnan(x)]
    pad  = " " * indent
    if not vals:
        print(f"{pad}{name}: no data")
        return
    arr  = np.array(vals)
    wins = arr[arr > 0]
    print(f"{pad}{name}")
    print(f"{pad}  n={len(arr):4d}  WR={len(wins)/len(arr)*100:5.1f}%  "
          f"Avg={arr.mean()*100:+.3f}%  Median={np.median(arr)*100:+.3f}%  "
          f"Best={arr.max()*100:+.3f}%  Worst={arr.min()*100:+.3f}%")


def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ── Research Q1 + Q2: Opening Drive ──────────────────────────────────────────

def q1_q2_opening_drive(df: pd.DataFrame):
    section("Q1/Q2  OPENING DRIVE  (9:30 → 9:45 move, then 11:00 / 1:00 / close)")

    buckets = {
        ">+1.0%":       {"11:00": [], "13:00": [], "close": []},
        "+0.5%-+1.0%":  {"11:00": [], "13:00": [], "close": []},
        "flat":         {"11:00": [], "13:00": [], "close": []},
        "-0.5%--1.0%":  {"11:00": [], "13:00": [], "close": []},
        "<-1.0%":       {"11:00": [], "13:00": [], "close": []},
    }

    for date, day in df.groupby("date"):
        open_px = price_at(day, "09:30")
        px_945  = price_at(day, "09:45")
        px_1100 = price_at(day, "11:00")
        px_1300 = price_at(day, "13:00")
        px_cls  = day["close"].iloc[-1]

        r_945 = ret(open_px, px_945)
        if r_945 is None:
            continue

        if   r_945 > 0.010: bk = ">+1.0%"
        elif r_945 > 0.005: bk = "+0.5%-+1.0%"
        elif r_945 < -0.010: bk = "<-1.0%"
        elif r_945 < -0.005: bk = "-0.5%--1.0%"
        else: bk = "flat"

        sign = -1 if bk in ("<-1.0%", "-0.5%--1.0%") else 1
        r11 = ret(px_945, px_1100); buckets[bk]["11:00"].append(sign * r11 if r11 is not None else None)
        r13 = ret(px_945, px_1300); buckets[bk]["13:00"].append(sign * r13 if r13 is not None else None)
        rc  = ret(px_945, px_cls);  buckets[bk]["close"].append(sign * rc  if rc  is not None else None)

    for bk, times in buckets.items():
        print(f"\n  9:45 bucket: {bk}  (sign-adjusted continuation)")
        for t, vals in times.items():
            summarize(f"→ {t}", vals, indent=4)


# ── Research Q3: VWAP Reclaim / Failure ──────────────────────────────────────

def q3_vwap_reclaim_failure(df: pd.DataFrame):
    section("Q3  VWAP RECLAIM / FAILURE  (cross + hold 5 bars, then 30/60/120m)")

    reclaim = {"30m": [], "60m": [], "120m": []}
    failure = {"30m": [], "60m": [], "120m": []}

    for date, day in df.groupby("date"):
        day = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
        if len(day) < 130:
            continue
        for i in range(5, len(day) - 120):
            prev = day.iloc[i - 1]
            row  = day.iloc[i]
            # confirm hold 5 bars above/below VWAP
            hold_above = all(day.iloc[i:i+5]["close"] > day.iloc[i:i+5]["vwap"])
            hold_below = all(day.iloc[i:i+5]["close"] < day.iloc[i:i+5]["vwap"])

            if prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and hold_above:
                ep = row["close"]
                for bars, label in [(30,"30m"),(60,"60m"),(120,"120m")]:
                    if i + bars < len(day):
                        reclaim[label].append(ret(ep, day.iloc[i + bars]["close"]))

            if prev["close"] > prev["vwap"] and row["close"] < row["vwap"] and hold_below:
                ep = row["close"]
                for bars, label in [(30,"30m"),(60,"60m"),(120,"120m")]:
                    if i + bars < len(day):
                        failure[label].append(-ret(ep, day.iloc[i + bars]["close"]))

    print("\n  VWAP Reclaim (long continuation):")
    for lbl, vals in reclaim.items():
        summarize(f"→ {lbl}", vals, indent=4)
    print("\n  VWAP Failure (short continuation):")
    for lbl, vals in failure.items():
        summarize(f"→ {lbl}", vals, indent=4)


# ── Research Q4: Trend Days ───────────────────────────────────────────────────

def q4_trend_days(df: pd.DataFrame):
    section("Q4  TREND DAYS  (10:00 above/below open + VWAP → 13:00 / close)")

    bull = {"13:00": [], "close": []}
    bear = {"13:00": [], "close": []}

    for date, day in df.groupby("date"):
        open_px  = price_at(day, "09:30")
        px_1000  = price_at(day, "10:00")
        px_1300  = price_at(day, "13:00")
        row_1000 = row_at(day, "10:00")
        px_cls   = day["close"].iloc[-1]

        if open_px is None or px_1000 is None or row_1000 is None:
            continue

        vwap_1000 = float(row_1000["vwap"])

        if px_1000 > open_px and px_1000 > vwap_1000:
            r13 = ret(px_1000, px_1300); bull["13:00"].append(r13)
            rc  = ret(px_1000, px_cls);  bull["close"].append(rc)

        if px_1000 < open_px and px_1000 < vwap_1000:
            r13 = ret(px_1000, px_1300); bear["13:00"].append(-r13 if r13 is not None else None)
            rc  = ret(px_1000, px_cls);  bear["close"].append(-rc  if rc  is not None else None)

    print("\n  Bullish trend day (10:00 > open + VWAP, long continuation):")
    for lbl, vals in bull.items(): summarize(f"→ {lbl}", vals, indent=4)
    print("\n  Bearish trend day (10:00 < open + VWAP, short continuation):")
    for lbl, vals in bear.items(): summarize(f"→ {lbl}", vals, indent=4)


# ── Research Q5: Failed Breakouts ────────────────────────────────────────────

def q5_failed_breakouts(df: pd.DataFrame):
    section("Q5  FAILED BREAKOUTS  (new high, fails back under → 30m/60m short)")

    r30, r60 = [], []

    for date, day in df.groupby("date"):
        day = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
        if len(day) < 70:
            continue
        rolling_high = day["high"].cummax()
        for i in range(5, len(day) - 60):
            if (day.iloc[i]["high"] >= rolling_high.iloc[i - 1] * 1.001 and
                    day.iloc[i]["close"] < rolling_high.iloc[i - 1]):
                ep = day.iloc[i]["close"]
                v30 = ret(ep, day.iloc[i + 30]["close"]); r30.append(-v30 if v30 is not None else None)
                v60 = ret(ep, day.iloc[i + 60]["close"]); r60.append(-v60 if v60 is not None else None)

    summarize("Failed breakout → 30m short", r30)
    summarize("Failed breakout → 60m short", r60)


# ── Research Q6: Opening Range Break ─────────────────────────────────────────

def q6_opening_range_break(df: pd.DataFrame):
    section("Q6  OPENING RANGE BREAK  (9:30-10:00 range, first break after 10:00)")

    high_30m, high_60m = [], []
    low_30m,  low_60m  = [], []

    for date, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        or_bars = day[(day["time"] >= "09:30") & (day["time"] <= "10:00")]
        after   = day[(day["time"] >  "10:00") & (day["time"] <= "13:00")].reset_index(drop=True)

        if or_bars.empty or len(after) < 60:
            continue

        or_high = or_bars["high"].max()
        or_low  = or_bars["low"].min()
        broke   = False

        for i in range(len(after) - 60):
            if broke:
                break
            row = after.iloc[i]
            if row["high"] > or_high:
                ep = row["close"]
                high_30m.append(ret(ep, after.iloc[i + 30]["close"]))
                high_60m.append(ret(ep, after.iloc[i + 60]["close"]))
                broke = True
            elif row["low"] < or_low:
                ep = row["close"]
                v30 = ret(ep, after.iloc[i + 30]["close"]); low_30m.append(-v30 if v30 is not None else None)
                v60 = ret(ep, after.iloc[i + 60]["close"]); low_60m.append(-v60 if v60 is not None else None)
                broke = True

    print("\n  Break OR high (long continuation):")
    summarize("→ 30m", high_30m, indent=4)
    summarize("→ 60m", high_60m, indent=4)
    print("\n  Break OR low (short continuation):")
    summarize("→ 30m", low_30m,  indent=4)
    summarize("→ 60m", low_60m,  indent=4)


# ── Research Q7: Afternoon Continuation ──────────────────────────────────────

def q7_afternoon_continuation(df: pd.DataFrame):
    section("Q7  AFTERNOON CONTINUATION  (2:00 PM conditions → close)")

    bull_close, bear_close = [], []

    for date, day in df.groupby("date"):
        px_1400  = price_at(day, "14:00")
        row_1400 = row_at(day, "14:00")
        px_cls   = day["close"].iloc[-1]
        open_px  = price_at(day, "09:30")

        if px_1400 is None or row_1400 is None or open_px is None:
            continue

        vwap_1400 = float(row_1400["vwap"])
        move      = ret(open_px, px_1400)

        if move is None:
            continue

        if px_1400 > vwap_1400 and move > 0.01:
            bull_close.append(ret(px_1400, px_cls))

        if px_1400 < vwap_1400 and move < -0.01:
            v = ret(px_1400, px_cls); bear_close.append(-v if v is not None else None)

    print("\n  2:00 above VWAP + up >1% from open → close (long):")
    summarize("→ close", bull_close, indent=4)
    print("\n  2:00 below VWAP + down >1% from open → close (short):")
    summarize("→ close", bear_close, indent=4)


# ── Q8: VWAP Reclaim TP/SL hit rate study ────────────────────────────────────

def _tp_sl_table(entries, n, label):
    TP_LEVELS = [0.0050, 0.0075, 0.0100, 0.0150]
    SL_LEVELS = [0.0030, 0.0050]
    MAX_BARS  = 120

    print(f"\n  Total {label} entries: {n}\n")
    print(f"  {'SL':<8}", end="")
    for tp in TP_LEVELS:
        print(f"  TP={tp*100:.2f}% hit   SL first   Neither  |  EV", end="")
    print()
    print(f"  {'-'*8}", end="")
    for _ in TP_LEVELS:
        print(f"  {'-'*43}", end="")
    print()

    for sl in SL_LEVELS:
        print(f"  SL={sl*100:.2f}%", end="")
        for tp in TP_LEVELS:
            tp_first = sl_first = neither = 0
            evs = []
            for e in entries:
                ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
                hit_tp = hit_sl = False
                for b in range(len(hs)):
                    if not hit_tp and not hit_sl:
                        if e["side"] == "long":
                            if hs[b] >= ep * (1 + tp): hit_tp = True; break
                            if ls[b] <= ep * (1 - sl): hit_sl = True; break
                        else:
                            if ls[b] <= ep * (1 - tp): hit_tp = True; break
                            if hs[b] >= ep * (1 + sl): hit_sl = True; break
                if hit_tp:
                    tp_first += 1; evs.append(tp)
                elif hit_sl:
                    sl_first += 1; evs.append(-sl)
                else:
                    neither += 1
                    if e["side"] == "long":
                        evs.append((hs[-1] - ep) / ep if len(hs) else 0)
                    else:
                        evs.append((ep - ls[-1]) / ep if len(ls) else 0)
            ev = np.mean(evs) * 100 if evs else 0
            print(f"  {tp_first/n:6.1%} tp  {sl_first/n:6.1%} sl  {neither/n:6.1%} ne  |  {ev:+.3f}%", end="")
        print()
    print(f"\n  Columns: TP hit first | SL hit first | Neither (held to bar {MAX_BARS})")


def _collect_vwap_crosses(df, side):
    MAX_BARS = 120
    entries = []
    for date, day in df.groupby("date"):
        day = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
        if len(day) < MAX_BARS + 10:
            continue
        for i in range(5, len(day) - MAX_BARS - 2):
            prev = day.iloc[i - 1]
            row  = day.iloc[i]
            if side == "long":
                hold = all(day.iloc[i:i+5]["close"] > day.iloc[i:i+5]["vwap"])
                cross = prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and hold
            else:
                hold = all(day.iloc[i:i+5]["close"] < day.iloc[i:i+5]["vwap"])
                cross = prev["close"] > prev["vwap"] and row["close"] < row["vwap"] and hold
            if cross:
                future = day.iloc[i:i + MAX_BARS]
                entries.append({"ep": row["close"], "side": side,
                                 "highs": future["high"].values, "lows": future["low"].values})
    return entries


def q8_vwap_reclaim_tp_sl(df: pd.DataFrame):
    section("Q8  VWAP RECLAIM LONG — TP / SL Hit Rate Study")
    entries = _collect_vwap_crosses(df, "long")
    _tp_sl_table(entries, len(entries), "VWAP reclaim long")


def q9_vwap_failure_tp_sl(df: pd.DataFrame):
    section("Q9  VWAP FAILURE SHORT — TP / SL Hit Rate Study")
    entries = _collect_vwap_crosses(df, "short")
    _tp_sl_table(entries, len(entries), "VWAP failure short")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\nBOOF50 Behavior Explorer — {SYMBOL}")
    df = load_or_fetch(SYMBOL)
    df = add_indicators(df)
    print(f"  {len(df)} bars  |  {df['date'].nunique()} trading days  |  "
          f"{df['timestamp'].min().date()} → {df['timestamp'].max().date()}\n")

    q8_vwap_reclaim_tp_sl(df)
    q9_vwap_failure_tp_sl(df)

    print(f"\n{'='*70}")
    print(f"  Done.")
    print(f"{'='*70}\n")


def multi_symbol_study():
    symbols = ["PLTR", "AMD", "SMCI", "META", "AMZN", "AAPL", "MSFT", "ARM",
               "MSTR", "RKLB", "AFRM", "UPST", "APP", "HIMS", "ASTS", "LUNR",
               "RIOT", "CLSK", "IREN"]
    TP_LEVELS = [0.0050, 0.0075, 0.0100, 0.0150]
    SL_LEVELS = [0.0030, 0.0050]

    summary = []

    for sym in symbols:
        global SYMBOL
        SYMBOL = sym
        print(f"\nLoading {sym}...")
        df = load_or_fetch(sym)
        df = add_indicators(df)
        print(f"  {df['date'].nunique()} days  {df['timestamp'].min().date()} → {df['timestamp'].max().date()}")

        for side in ["long", "short"]:
            entries = _collect_vwap_crosses(df, side)
            n = len(entries)
            if n == 0:
                continue
            best_ev = -999; best_tp = None; best_sl = None
            for sl in SL_LEVELS:
                for tp in TP_LEVELS:
                    evs = []
                    for e in entries:
                        ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
                        hit_tp = hit_sl = False
                        for b in range(len(hs)):
                            if side == "long":
                                if hs[b] >= ep*(1+tp): hit_tp=True; break
                                if ls[b] <= ep*(1-sl): hit_sl=True; break
                            else:
                                if ls[b] <= ep*(1-tp): hit_tp=True; break
                                if hs[b] >= ep*(1+sl): hit_sl=True; break
                        if hit_tp:   evs.append(tp)
                        elif hit_sl: evs.append(-sl)
                        else:
                            if side == "long": evs.append((hs[-1]-ep)/ep if len(hs) else 0)
                            else:              evs.append((ep-ls[-1])/ep if len(ls) else 0)
                    ev = np.mean(evs)*100
                    if ev > best_ev:
                        best_ev = ev; best_tp = tp; best_sl = sl
            summary.append(dict(symbol=sym, side=side, n=n,
                                 best_ev=best_ev, best_tp=best_tp, best_sl=best_sl))

    print(f"\n{'='*75}")
    print(f"  MULTI-SYMBOL VWAP CROSS SUMMARY")
    print(f"{'='*75}")
    print(f"  {'Symbol':<6}  {'Side':<5}  {'n':>4}  {'Best EV':>9}  {'Best TP':>7}  {'Best SL':>7}")
    print(f"  {'-'*6}  {'-'*5}  {'-'*4}  {'-'*9}  {'-'*7}  {'-'*7}")

    # pivot for side-by-side display
    by_sym = {}
    for r in summary:
        by_sym.setdefault(r["symbol"], {})[r["side"]] = r

    for sym in symbols:
        d = by_sym.get(sym, {})
        lg = d.get("long",  {})
        sh = d.get("short", {})
        lev = lg.get("best_ev", 0); sev = sh.get("best_ev", 0)
        ltp = lg.get("best_tp", 0); stp = sh.get("best_tp", 0)
        lsl = lg.get("best_sl", 0); ssl = sh.get("best_sl", 0)
        ln  = lg.get("n", 0);       sn  = sh.get("n", 0)
        print(f"  {sym:<6}  {'LONG':<5}  {ln:>4}  {lev:>+8.3f}%  {ltp*100:>6.2f}%  {lsl*100:>6.2f}%")
        print(f"  {sym:<6}  {'SHORT':<5}  {sn:>4}  {sev:>+8.3f}%  {stp*100:>6.2f}%  {ssl*100:>6.2f}%")
        print()


def combined_backtest():
    symbols = [
        "TSLA","AMD","APP","COIN","HOOD",
        "SMCI","UPST","META","MSFT","NVDA",
        "MSTR","PLTR","CRWD","AAPL","AMZN"
    ]
    SL = 0.005
    TP = 0.0075  # use 0.75% as universal baseline (best for most)
    MAX_BARS = 120
    all_trades = []

    for sym in symbols:
        global SYMBOL
        SYMBOL = sym
        print(f"  {sym}...", end=" ", flush=True)
        df = load_or_fetch(sym)
        df = add_indicators(df)
        entries = _collect_vwap_crosses(df, "long") + _collect_vwap_crosses(df, "short")
        print(f"{len(entries)} entries")

        for e in entries:
            ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
            hit_tp = hit_sl = False
            mfe = mae = 0.0
            for b in range(len(hs)):
                if e["side"] == "long":
                    mfe = max(mfe, (hs[b] - ep) / ep)
                    mae = max(mae, (ep - ls[b]) / ep)
                    if not hit_tp and not hit_sl:
                        if hs[b] >= ep * (1 + TP): hit_tp = True; break
                        if ls[b] <= ep * (1 - SL): hit_sl = True; break
                else:
                    mfe = max(mfe, (ep - ls[b]) / ep)
                    mae = max(mae, (hs[b] - ep) / ep)
                    if not hit_tp and not hit_sl:
                        if ls[b] <= ep * (1 - TP): hit_tp = True; break
                        if hs[b] >= ep * (1 + SL): hit_sl = True; break

            if hit_tp:   pnl = TP
            elif hit_sl: pnl = -SL
            else:
                if e["side"] == "long": pnl = (hs[-1] - ep) / ep if len(hs) else 0
                else:                   pnl = (ep - ls[-1]) / ep if len(ls) else 0

            all_trades.append({"symbol": sym, "side": e["side"], "pnl": pnl, "mfe": mfe, "mae": mae})

    df_t = pd.DataFrame(all_trades)
    x    = df_t["pnl"]
    wins = x[x > 0]; losses = x[x < 0]
    gw   = wins.sum(); gl = abs(losses.sum())
    pf   = gw / gl if gl > 0 else float("inf")

    print(f"\n{'='*65}")
    print(f"  COMBINED BACKTEST — {len(symbols)} symbols, VWAP cross both sides")
    print(f"  SL={SL*100:.2f}%  TP={TP*100:.2f}%  Max hold={MAX_BARS} bars")
    print(f"{'='*65}")
    print(f"  Total trades : {len(x)}")
    print(f"  Win rate     : {len(wins)/len(x):.1%}")
    print(f"  Profit factor: {pf:.3f}")
    print(f"  Avg EV       : {x.mean()*100:+.4f}%")
    print(f"  Total PnL    : {x.sum()*100:+.2f}%")
    print(f"  Avg MFE      : {df_t['mfe'].mean()*100:+.3f}%")
    print(f"  Avg MAE      : {df_t['mae'].mean()*100:+.3f}%")
    print(f"  Best trade   : {x.max()*100:+.3f}%")
    print(f"  Worst trade  : {x.min()*100:+.3f}%")

    print(f"\n  Per-symbol breakdown (sorted by EV):")
    print(f"  {'Symbol':<6}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'MFE':>7}  {'MAE':>7}")
    for sym, g in df_t.groupby("symbol"):
        px = g["pnl"]; pw = px[px>0]; pl = px[px<0]
        spf = pw.sum()/abs(pl.sum()) if len(pl) else float("inf")
        print(f"  {sym:<6}  {len(px):4d}  {len(pw)/len(px):6.1%}  {spf:5.2f}  "
              f"{px.mean()*100:+8.4f}%  {g['mfe'].mean()*100:+6.3f}%  {g['mae'].mean()*100:+6.3f}%")


if __name__ == "__main__":
    combined_backtest()
