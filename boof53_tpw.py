"""Quick T/Week summary from saved CSV"""
import pandas as pd

df     = pd.read_csv("boof53_leaderboard_all.csv")
b      = df[(df["bounced"]==True) & (df["touch_lbl"]=="1st")]
WEEKS  = df["date"].nunique() / 5

SYMBOLS = sorted(df["sym"].unique())

rows = []
for sym in SYMBOLS:
    s = b[b["sym"]==sym]
    if len(s) < 3: continue
    long_n  = len(s[s["side"]=="long"])
    short_n = len(s[s["side"]=="short"])
    total   = long_n + short_n
    rows.append({
        "sym":       sym,
        "total":     total,
        "long_n":    long_n,
        "short_n":   short_n,
        "t_wk":      total  / WEEKS,
        "l_wk":      long_n / WEEKS,
        "s_wk":      short_n/ WEEKS,
        "mfe30":     s["mfe30"].mean(),
        "h50":       s["hit_>=0.50%"].mean()*100,
        "h75":       s["hit_>=0.75%"].mean()*100,
    })

rows = sorted(rows, key=lambda x: -x["t_wk"])

print(f"\n  {'='*82}")
print(f"  TRADES PER WEEK — 1st touch, bounce>=0.15%, all levels")
print(f"  {df['date'].nunique()} trading days  (~{WEEKS:.1f} weeks)")
print(f"  {'='*82}")
print(f"  {'Sym':<6} {'Total/Wk':>9}  {'Long/Wk':>8}  {'Short/Wk':>9}  "
      f"{'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
print(f"  {'-'*78}")

total_tpw = 0
for r in rows:
    mark = " <<<" if r["h50"]>=55 else ("  <<" if r["h50"]>=40 else "")
    print(f"  {r['sym']:<6} {r['t_wk']:>9.2f}  {r['l_wk']:>8.2f}  {r['s_wk']:>9.2f}  "
          f"{r['mfe30']:>6.3f}%  {r['h50']:>8.1f}%  {r['h75']:>8.1f}%{mark}")
    total_tpw += r["t_wk"]

print(f"  {'-'*78}")
print(f"  {'ALL':<6} {total_tpw:>9.2f}  {'':>8}  {'':>9}")

# Tier totals
tier1 = ["RKLB","HIMS","MU","APP","SMCI","ARM","TEM","HOOD","COIN","PLTR","ORCL","CRM","AMD","AVGO"]
tier2 = ["TSLA","NVDA","ADBE","LLY","UNH","META","AMZN","GOOGL","NFLX"]
tier3 = ["MSFT","WMT","JPM","AAPL","COST","IWM"]

print(f"\n  TIER SUMMARY")
print(f"  {'Tier':<30} {'T/Wk':>7}  {'Avg MFE30':>10}  {'Avg >=0.50%':>12}")
print(f"  {'-'*65}")
for label, tier in [("Tier 1 (elite, 14 syms)", tier1),
                    ("Tier 2 (strong, 9 syms)", tier2),
                    ("Tier 3 (weak, 6 syms)",   tier3)]:
    ts = b[b["sym"].isin(tier)]
    tpw = sum(r["t_wk"] for r in rows if r["sym"] in tier)
    print(f"  {label:<30} {tpw:>7.1f}  {ts['mfe30'].mean():>10.3f}%  "
          f"{ts['hit_>=0.50%'].mean()*100:>12.1f}%")
