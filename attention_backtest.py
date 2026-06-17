"""
Attention Backtest — 2 years (2024-2026)
Signal: Google Trends interest spike > 50% over 4wk vs prior 8wk
        + price already up > 5% over same 4 weeks
Question: How did those stocks perform 1wk / 2wk / 1mo / 3mo forward?

Uses:
  - pytrends for attention proxy (free, historical)
  - yfinance for price data (free, historical)
"""
import pandas as pd
import numpy as np
import time
import warnings
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
    import yfinance as yf

try:
    from pytrends.request import TrendReq
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pytrends", "-q"])
    from pytrends.request import TrendReq

# ── Universe — mix of large/mid caps with known retail attention ──────────────
SYMBOLS = sorted(pd.read_csv("attention_20260615_2157.csv")["sym"].unique().tolist())

START = "2024-01-01"
END   = "2026-06-01"

ATTN_THRESH  = 0.50   # 50% attention growth
PRICE_THRESH = 0.05   # 5% price growth over same 4 weeks

# ── Fetch Google Trends weekly data ───────────────────────────────────────────
def fetch_trends_for_sym(pt, sym):
    """Returns weekly interest DataFrame for a symbol, 2 years back."""
    try:
        pt.build_payload([sym], timeframe=f"{START} {END}", geo="US")
        df = pt.interest_over_time()
        if df.empty or sym not in df.columns:
            return None
        return df[[sym]].rename(columns={sym: "interest"})
    except Exception as e:
        return None

# ── Fetch price data ──────────────────────────────────────────────────────────
def fetch_prices(sym):
    try:
        df = yf.download(sym, start=START, end=END, interval="1wk",
                         progress=False, auto_adjust=True)
        if df.empty: return None
        # flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Close"]].rename(columns={"Close": "price"})
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except:
        return None

# ── Signal detection ──────────────────────────────────────────────────────────
def find_signals(trends_df, price_df):
    """
    For each week, check:
      - attention_4wk vs attention_8_4wk growth > ATTN_THRESH
      - price_4wk growth > PRICE_THRESH
    Returns list of signal weeks.
    """
    if trends_df is None or price_df is None: return []
    t = trends_df.copy()
    t.index = pd.to_datetime(t.index).tz_localize(None)
    t.index = t.index - pd.to_timedelta(t.index.dayofweek, unit='d')  # snap to Monday
    p = price_df.copy()
    p.index = pd.to_datetime(p.index).tz_localize(None)
    p.index = p.index - pd.to_timedelta(p.index.dayofweek, unit='d')  # snap to Monday
    df = t.join(p, how="inner").dropna()
    if len(df) < 16: return []

    signals = []
    for i in range(8, len(df) - 13):   # need 13 weeks forward for 3mo
        # Attention: last 4wk vs prior 4wk
        attn_4wk     = df["interest"].iloc[i-4:i].mean()
        attn_prior   = df["interest"].iloc[i-8:i-4].mean()
        if attn_prior < 5: continue    # ignore obscure stocks with near-zero interest
        attn_growth  = (attn_4wk - attn_prior) / (attn_prior + 1)

        # Price: last 4wk return
        p_now  = df["price"].iloc[i]
        p_4wk  = df["price"].iloc[i-4]
        if p_4wk <= 0: continue
        price_growth = (p_now - p_4wk) / p_4wk

        if attn_growth >= ATTN_THRESH and price_growth >= PRICE_THRESH:
            # Forward returns
            try:
                fwd_1wk  = (df["price"].iloc[i+1]  - p_now) / p_now
                fwd_2wk  = (df["price"].iloc[i+2]  - p_now) / p_now
                fwd_4wk  = (df["price"].iloc[i+4]  - p_now) / p_now
                fwd_13wk = (df["price"].iloc[i+13] - p_now) / p_now
                signals.append({
                    "date":        df.index[i].date(),
                    "attn_growth": round(attn_growth * 100, 1),
                    "price_growth":round(price_growth * 100, 1),
                    "attn_4wk":    round(attn_4wk, 1),
                    "fwd_1wk":     round(fwd_1wk  * 100, 2),
                    "fwd_2wk":     round(fwd_2wk  * 100, 2),
                    "fwd_1mo":     round(fwd_4wk  * 100, 2),
                    "fwd_3mo":     round(fwd_13wk * 100, 2),
                })
            except IndexError:
                pass

    return signals

# ── Control group — random weeks (no signal) ─────────────────────────────────
def find_controls(trends_df, price_df, n_signals):
    """Random weeks with no attention or price signal."""
    if trends_df is None or price_df is None: return []
    t = trends_df.copy()
    t.index = pd.to_datetime(t.index).tz_localize(None)
    t.index = t.index - pd.to_timedelta(t.index.dayofweek, unit='d')
    p = price_df.copy()
    p.index = pd.to_datetime(p.index).tz_localize(None)
    p.index = p.index - pd.to_timedelta(p.index.dayofweek, unit='d')
    df = t.join(p, how="inner").dropna()
    if len(df) < 16: return []
    controls = []
    indices = list(range(8, len(df) - 13))
    np.random.shuffle(indices)
    for i in indices[:n_signals*3]:
        p_now = df["price"].iloc[i]
        if p_now <= 0: continue
        try:
            controls.append({
                "fwd_1wk":  (df["price"].iloc[i+1]  - p_now) / p_now * 100,
                "fwd_2wk":  (df["price"].iloc[i+2]  - p_now) / p_now * 100,
                "fwd_1mo":  (df["price"].iloc[i+4]  - p_now) / p_now * 100,
                "fwd_3mo":  (df["price"].iloc[i+13] - p_now) / p_now * 100,
            })
        except IndexError:
            pass
    return controls

# ── Main ──────────────────────────────────────────────────────────────────────
print(f"\nAttention Backtest — {START} to {END}")
print(f"Signal: Attention growth > {ATTN_THRESH*100:.0f}% AND price growth > {PRICE_THRESH*100:.0f}% over 4 weeks")
print(f"Universe: {len(SYMBOLS)} symbols\n")

pt = TrendReq(hl="en-US", tz=300, timeout=(10,30), retries=3, backoff_factor=0.5)

all_signals  = []
all_controls = []
sym_results  = []

for sym in SYMBOLS:
    print(f"  {sym}...", end=" ", flush=True)
    trends = fetch_trends_for_sym(pt, sym)
    prices = fetch_prices(sym)
    sigs   = find_signals(trends, prices)
    ctrls  = find_controls(trends, prices, len(sigs))
    all_signals  += sigs
    all_controls += ctrls
    print(f"{len(sigs)} signals")
    for s in sigs: s["sym"] = sym
    if sigs:
        df_s = pd.DataFrame(sigs)
        sym_results.append({
            "sym":       sym,
            "signals":   len(sigs),
            "avg_1wk":   round(df_s["fwd_1wk"].mean(), 2),
            "avg_2wk":   round(df_s["fwd_2wk"].mean(), 2),
            "avg_1mo":   round(df_s["fwd_1mo"].mean(), 2),
            "avg_3mo":   round(df_s["fwd_3mo"].mean(), 2),
            "wr_1mo":    round((df_s["fwd_1mo"] > 0).mean() * 100, 1),
        })
    time.sleep(1.2)   # respect rate limits

# ── Results ───────────────────────────────────────────────────────────────────
print(f"\n{'='*75}")
print(f"RESULTS — {len(all_signals)} signal events  |  {len(all_controls)} control events")
print(f"{'='*75}")

if all_signals:
    sig_df  = pd.DataFrame(all_signals)
    ctrl_df = pd.DataFrame(all_controls)

    periods = ["fwd_1wk","fwd_2wk","fwd_1mo","fwd_3mo"]
    labels  = ["1 Week","2 Weeks","1 Month","3 Months"]

    print(f"\n{'Period':<12} {'Signal Avg':>12} {'Control Avg':>12} {'Signal WR':>10} {'Control WR':>11} {'Edge':>8}")
    print("-"*65)
    for col, lbl in zip(periods, labels):
        s_avg = sig_df[col].mean()
        c_avg = ctrl_df[col].mean() if not ctrl_df.empty else 0
        s_wr  = (sig_df[col] > 0).mean() * 100
        c_wr  = (ctrl_df[col] > 0).mean() * 100 if not ctrl_df.empty else 50
        edge  = s_avg - c_avg
        print(f"{lbl:<12} {s_avg:>+11.2f}%  {c_avg:>+11.2f}%  {s_wr:>9.1f}%  {c_wr:>10.1f}%  {edge:>+7.2f}%")

    print(f"\nSignal stats:")
    print(f"  Avg attention growth at signal: {sig_df['attn_growth'].mean():.1f}%")
    print(f"  Avg price growth at signal:     {sig_df['price_growth'].mean():.1f}%")
    print(f"  Signals per symbol avg:         {len(all_signals)/len(SYMBOLS):.1f}")

    print(f"\nPer-symbol breakdown:")
    print(f"  {'Sym':<6} {'N':>4}  {'1wk':>7}  {'2wk':>7}  {'1mo':>7}  {'3mo':>7}  {'1mo WR':>7}")
    print(f"  {'-'*55}")
    for r in sorted(sym_results, key=lambda x: x["avg_1mo"], reverse=True):
        flag = " ✅" if r["avg_1mo"] > 2 and r["wr_1mo"] > 55 else (" ❌" if r["avg_1mo"] < -2 else "")
        print(f"  {r['sym']:<6} {r['signals']:>4}  {r['avg_1wk']:>+6.2f}%  {r['avg_2wk']:>+6.2f}%  {r['avg_1mo']:>+6.2f}%  {r['avg_3mo']:>+6.2f}%  {r['wr_1mo']:>6.1f}%{flag}")

    # All individual signals
    print(f"\nAll {len(all_signals)} signals:")
    print(sig_df[["sym","date","attn_growth","price_growth","fwd_1wk","fwd_2wk","fwd_1mo","fwd_3mo"]].to_string(index=False))

    sig_df.to_csv("attention_backtest_results.csv", index=False)
    print(f"\nSaved to attention_backtest_results.csv")
else:
    print("No signals found — try loosening thresholds")
