"""
Bucket Analysis — what do attention signal winners have in common?
Bucket A: Top 20 by avg 1mo return
Bucket B: Middle 20%
Bucket C: Bottom 20%
Compare: market cap, float, sector, ATR%, avg gap%
"""
import pandas as pd
import numpy as np
import yfinance as yf
import time
import warnings
warnings.filterwarnings("ignore")

results = pd.read_csv("attention_backtest_results.csv")
g = results.groupby("sym").agg(
    N=("fwd_1mo","count"),
    avg_1mo=("fwd_1mo","mean"),
    avg_3mo=("fwd_3mo","mean"),
    wr_1mo=("fwd_1mo", lambda x: (x>0).mean()*100),
).reset_index()
g = g[g.N >= 2].sort_values("avg_1mo", ascending=False).reset_index(drop=True)

n = len(g)
top20    = g.head(20)["sym"].tolist()
bot20pct = int(n * 0.20)
mid_start = int(n * 0.40)
mid_end   = int(n * 0.60)
mid20    = g.iloc[mid_start:mid_end]["sym"].tolist()
bot20    = g.tail(bot20pct)["sym"].tolist()

print(f"Total symbols: {n}")
print(f"Bucket A (top 20):   {top20}")
print(f"Bucket B (mid 20%):  {mid20}")
print(f"Bucket C (bot 20%):  {bot20}\n")

all_syms = list(set(top20 + mid20 + bot20))

def get_info(sym):
    try:
        t = yf.Ticker(sym)
        info = t.info
        hist = t.history(period="3mo", interval="1d", auto_adjust=True)

        mktcap   = info.get("marketCap", 0) or 0
        shares_float = info.get("floatShares", 0) or 0
        sector   = info.get("sector", "Unknown") or "Unknown"
        industry = info.get("industry", "Unknown") or "Unknown"
        beta     = info.get("beta", None)

        # ATR% (14-day avg true range as % of price)
        atr_pct = None
        if len(hist) >= 15:
            hi = hist["High"].values
            lo = hist["Low"].values
            cl = hist["Close"].values
            trs = [max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1])) for i in range(1, len(hi))]
            atr = np.mean(trs[-14:])
            atr_pct = round(atr / cl[-1] * 100, 2)

        # Avg gap% (open vs prior close)
        avg_gap = None
        if len(hist) >= 10:
            opens  = hist["Open"].values
            closes = hist["Close"].values
            gaps   = [(opens[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(opens))]
            avg_gap = round(np.mean(np.abs(gaps[-20:])), 2)

        price = cl[-1] if len(hist) > 0 else 0

        return {
            "sym":       sym,
            "mktcap_B":  round(mktcap / 1e9, 2),
            "float_M":   round(shares_float / 1e6, 1),
            "sector":    sector,
            "industry":  industry,
            "beta":      beta,
            "atr_pct":   atr_pct,
            "avg_gap_pct": avg_gap,
            "price":     round(price, 2),
        }
    except Exception as e:
        return {"sym": sym, "mktcap_B": 0, "float_M": 0, "sector": "Error",
                "industry": "Error", "beta": None, "atr_pct": None, "avg_gap_pct": None, "price": 0}

print("Fetching fundamentals...")
rows = []
for i, sym in enumerate(all_syms):
    print(f"  {sym}...", end=" ", flush=True)
    rows.append(get_info(sym))
    time.sleep(0.3)
print()

fund = pd.DataFrame(rows)
fund = fund.merge(g[["sym","avg_1mo","avg_3mo","wr_1mo","N"]], on="sym")

def label(sym):
    if sym in top20: return "A_top"
    if sym in mid20: return "B_mid"
    if sym in bot20: return "C_bot"
    return "?"
fund["bucket"] = fund["sym"].apply(label)

# ── Summary by bucket ─────────────────────────────────────────────────────────
print(f"\n{'='*75}")
print(f"BUCKET COMPARISON")
print(f"{'='*75}")

metrics = ["mktcap_B","float_M","atr_pct","avg_gap_pct","beta","avg_1mo","wr_1mo"]
labels  = ["MktCap $B","Float M","ATR%","AvgGap%","Beta","Avg1mo%","WR1mo%"]

print(f"\n{'Metric':<14} {'A (Top20)':>12} {'B (Mid20%)':>12} {'C (Bot20%)':>12}")
print("-"*52)
for col, lbl in zip(metrics, labels):
    a = fund[fund.bucket=="A_top"][col].median()
    b = fund[fund.bucket=="B_mid"][col].median()
    c = fund[fund.bucket=="C_bot"][col].median()
    print(f"{lbl:<14} {a:>12.2f} {b:>12.2f} {c:>12.2f}")

# ── Sector breakdown ──────────────────────────────────────────────────────────
print(f"\n{'─'*55}")
print("SECTOR DISTRIBUTION")
print(f"{'─'*55}")
for bucket, label_str in [("A_top","A Top20"),("B_mid","B Mid20%"),("C_bot","C Bot20%")]:
    sub = fund[fund.bucket==bucket]
    sec_counts = sub["sector"].value_counts()
    print(f"\n{label_str}:")
    for sec, cnt in sec_counts.items():
        print(f"  {sec:<35} {cnt}")

# ── Per-symbol detail ─────────────────────────────────────────────────────────
print(f"\n{'─'*90}")
print("PER-SYMBOL DETAIL")
print(f"{'─'*90}")
print(f"{'Sym':<6} {'Bkt':>4}  {'1mo':>7}  {'MktCap':>8}  {'Float':>7}  {'ATR%':>5}  {'Gap%':>5}  {'Beta':>5}  {'Sector'}")
print("-"*95)
for bucket in ["A_top","B_mid","C_bot"]:
    sub = fund[fund.bucket==bucket].sort_values("avg_1mo", ascending=False)
    print(f"── {'Top 20' if bucket=='A_top' else 'Mid 20%' if bucket=='B_mid' else 'Bot 20%'} ──")
    for _, r in sub.iterrows():
        beta_s = f"{r.beta:.1f}" if r.beta else "  -"
        atr_s  = f"{r.atr_pct:.1f}" if r.atr_pct else "  -"
        gap_s  = f"{r.avg_gap_pct:.1f}" if r.avg_gap_pct else "  -"
        print(f"{r.sym:<6} {r.bucket:>5}  {r.avg_1mo:>+6.2f}%  {r.mktcap_B:>7.1f}B  {r.float_M:>6.0f}M  {atr_s:>5}  {gap_s:>5}  {beta_s:>5}  {r.sector}")

fund.to_csv("attention_bucket_analysis.csv", index=False)
print(f"\nSaved to attention_bucket_analysis.csv")
