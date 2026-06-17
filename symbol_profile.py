"""
Symbol Profile — fundamentals + backtest performance
Shows beta, ATR%, gap freq, market cap, sector, price, volume
Cross-referenced with gap breakout backtest results
"""
import os, warnings, time
import pandas as pd
import numpy as np
import yfinance as yf
warnings.filterwarnings("ignore")

DATA_DIR = "data/1m"
SCENARIO = "TP1.5_SL0.5"  # main scenario to rank by

df = pd.read_csv("gap_breakout_results.csv")

# ── Compute per-symbol backtest stats ────────────────────────────────────────
rows = []
for sym, g in df.groupby("sym"):
    rc = f"{SCENARIO}_result"
    rv = f"{SCENARIO}_ret"
    tp_n = (g[rc] == "TP").sum()
    sl_n = (g[rc] == "SL").sum()
    wr   = tp_n / (tp_n + sl_n) * 100 if (tp_n + sl_n) > 0 else 0
    ev   = g[rv].mean()
    n    = len(g)
    gap_freq_all = n  # total qualifying gap days
    rows.append({"sym": sym, "trades": n, "tp": tp_n, "sl": sl_n, "wr": round(wr,1), "ev": round(ev,4)})

bt = pd.DataFrame(rows).set_index("sym")

# ── Compute ATR%, avg gap%, gap frequency from raw data ──────────────────────
print("Computing ATR%, gap%, gap frequency from 1m data...")
mkt_rows = []
files = [f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")]
for fname in files:
    sym = fname.replace(".parquet", "")
    try:
        raw = pd.read_parquet(os.path.join(DATA_DIR, fname))
        raw.index = pd.to_datetime(raw.index)
        if raw.index.tz is None:
            raw.index = raw.index.tz_localize("America/New_York")
        else:
            raw.index = raw.index.tz_convert("America/New_York")
        raw.columns = [c.lower() for c in raw.columns]

        # daily OHLC
        sess = raw.between_time("09:30","15:59")
        daily = sess.resample("D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

        if len(daily) < 10:
            continue

        # ATR% (14-day)
        daily["tr"] = np.maximum(daily["high"] - daily["low"],
                      np.maximum(abs(daily["high"] - daily["close"].shift(1)),
                                 abs(daily["low"]  - daily["close"].shift(1))))
        atr     = daily["tr"].rolling(14).mean().iloc[-1]
        atr_pct = atr / daily["close"].iloc[-1] * 100

        # gap% per day
        daily["prev_close"] = daily["close"].shift(1)
        daily["gap_pct"]    = (daily["open"] - daily["prev_close"]) / daily["prev_close"] * 100
        avg_gap_pct = daily["gap_pct"].abs().mean()

        # gap frequency >1%
        gap_freq = (daily["gap_pct"].abs() > 1.0).sum()
        gap_freq_pct = gap_freq / len(daily) * 100

        # avg daily volume and price
        avg_vol   = daily["volume"].mean()
        avg_price = daily["close"].mean()

        mkt_rows.append({
            "sym":          sym,
            "atr_pct":      round(atr_pct, 2),
            "avg_gap_pct":  round(avg_gap_pct, 2),
            "gap_days_pct": round(gap_freq_pct, 1),
            "avg_volume":   int(avg_vol),
            "avg_price":    round(avg_price, 2),
        })
    except Exception as e:
        pass

mkt = pd.DataFrame(mkt_rows).set_index("sym")

# ── Fetch beta, market cap, sector from yfinance ─────────────────────────────
print(f"Fetching fundamentals for {len(mkt)} symbols...")
fund_rows = []
for sym in mkt.index:
    try:
        info = yf.Ticker(sym).info
        fund_rows.append({
            "sym":        sym,
            "beta":       info.get("beta", None),
            "market_cap": info.get("marketCap", None),
            "sector":     info.get("sector", "Unknown"),
        })
        time.sleep(0.08)
    except:
        fund_rows.append({"sym": sym, "beta": None, "market_cap": None, "sector": "Unknown"})

fund = pd.DataFrame(fund_rows).set_index("sym")

# ── Merge everything ──────────────────────────────────────────────────────────
full = mkt.join(fund, how="left").join(bt, how="left")
full["market_cap_b"] = (full["market_cap"] / 1e9).round(1)
full = full.drop(columns=["market_cap"])
full["verdict"] = full["ev"].apply(lambda x: "KEEP" if (x is not None and x > 0) else "DROP")
full = full.sort_values("ev", ascending=False)

# ── Print full table ──────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"SYMBOL PROFILE — ranked by EV ({SCENARIO})")
print(f"{'='*110}")
print(f"{'Sym':<7} {'Sector':<22} {'Beta':>5} {'ATR%':>5} {'GapF%':>6} {'AvgGap':>7} {'AvgVol':>10} {'Price':>7} {'MCap$B':>7} {'N':>4} {'WR':>6} {'EV':>7} {'Verdict'}")
print("-"*110)
for sym, r in full.iterrows():
    beta   = f"{r.beta:.2f}"    if pd.notna(r.get('beta'))         else "  N/A"
    atr    = f"{r.atr_pct:.2f}" if pd.notna(r.get('atr_pct'))      else " N/A"
    gf     = f"{r.gap_days_pct:.1f}" if pd.notna(r.get('gap_days_pct')) else "N/A"
    ag     = f"{r.avg_gap_pct:.2f}" if pd.notna(r.get('avg_gap_pct')) else "N/A"
    vol    = f"{int(r.avg_volume):>10,}" if pd.notna(r.get('avg_volume')) else "       N/A"
    price  = f"{r.avg_price:.2f}" if pd.notna(r.get('avg_price'))   else "  N/A"
    mc     = f"{r.market_cap_b:.1f}" if pd.notna(r.get('market_cap_b')) else " N/A"
    n      = f"{int(r.trades)}" if pd.notna(r.get('trades'))        else "  0"
    wr     = f"{r.wr:.1f}%"     if pd.notna(r.get('wr'))            else "  N/A"
    ev     = f"{r.ev:+.3f}%"    if pd.notna(r.get('ev'))            else "  N/A"
    sector = str(r.get('sector','Unknown'))[:22]
    verdict = str(r.get('verdict',''))
    print(f"{sym:<7} {sector:<22} {beta:>5} {atr:>5} {gf:>6} {ag:>7} {vol:>10} {price:>7} {mc:>7} {n:>4} {wr:>6} {ev:>7}  {verdict}")

# ── Save ──────────────────────────────────────────────────────────────────────
full.to_csv("symbol_profile.csv")
print(f"\nSaved to symbol_profile.csv")

# ── Filter summary ────────────────────────────────────────────────────────────
keep = full[full.verdict == "KEEP"]
drop = full[full.verdict == "DROP"]
print(f"\n{'='*70}")
print(f"FILTER SUMMARY ({SCENARIO})")
print(f"{'='*70}")
print(f"KEEP ({len(keep)} symbols): {', '.join(keep.index.tolist())}")
print(f"\nDROP ({len(drop)} symbols): {', '.join(drop.index.tolist())}")

print(f"\n-- KEEP avg profile --")
print(f"  Beta:        {keep.beta.mean():.2f}")
print(f"  ATR%:        {keep.atr_pct.mean():.2f}%")
print(f"  Gap Freq:    {keep.gap_days_pct.mean():.1f}% of days gap >1%")
print(f"  Avg Gap%:    {keep.avg_gap_pct.mean():.2f}%")
print(f"  Avg Vol:     {keep.avg_volume.mean():,.0f}")
print(f"  Avg Price:   ${keep.avg_price.mean():.2f}")
print(f"  Avg MCap:    ${keep.market_cap_b.mean():.1f}B")

print(f"\n-- DROP avg profile --")
print(f"  Beta:        {drop.beta.mean():.2f}")
print(f"  ATR%:        {drop.atr_pct.mean():.2f}%")
print(f"  Gap Freq:    {drop.gap_days_pct.mean():.1f}% of days gap >1%")
print(f"  Avg Gap%:    {drop.avg_gap_pct.mean():.2f}%")
print(f"  Avg Vol:     {drop.avg_volume.mean():,.0f}")
print(f"  Avg Price:   ${drop.avg_price.mean():.2f}")
print(f"  Avg MCap:    ${drop.market_cap_b.mean():.1f}B")
