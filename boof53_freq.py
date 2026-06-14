"""BOOF53 Trade Frequency — trades per day / per week by level + symbol"""
import pandas as pd

df = pd.read_csv("boof53_clean_all.csv")
df = df[df["sym"] != "SPY"]
bounced = df[df["bounced"] == True]

TRADING_DAYS  = df["date"].nunique()
TRADING_WEEKS = TRADING_DAYS / 5

syms = sorted(bounced["sym"].unique())
print(f"Dataset : {TRADING_DAYS} trading days  (~{TRADING_WEEKS:.1f} weeks)")
print(f"Symbols : {syms}")
print()

rows = [
    ("PML  1st",   "PML",    "1st", "long"),
    ("PDL  1st",   "PDL",    "1st", "long"),
    ("1H_Sup 1st", "1H_Sup", "1st", "long"),
    ("4H_Sup 1st", "4H_Sup", "1st", "long"),
    ("PMH  1st",   "PMH",    "1st", "short"),
    ("PDH  1st",   "PDH",    "1st", "short"),
    ("1H_Res 1st", "1H_Res", "1st", "short"),
    ("4H_Res 1st", "4H_Res", "1st", "short"),
    (None, None, None, None),
    ("PML  2nd",   "PML",    "2nd", "long"),
    ("1H_Sup 2nd", "1H_Sup", "2nd", "long"),
    ("PMH  2nd",   "PMH",    "2nd", "short"),
    ("1H_Res 2nd", "1H_Res", "2nd", "short"),
    ("4H_Res 2nd", "4H_Res", "2nd", "short"),
]

W = 82
print(f"  {'Level':<14} {'Side':<7} {'Trades':>7}  {'Days':>5}  "
      f"{'T/Day':>6}  {'T/Week':>7}  {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
print(f"  {'-'*W}")

for item in rows:
    label, lname, tl, side = item
    if label is None:
        print(f"  {'--- 2nd touch ---'}")
        continue
    s = bounced[(bounced["level"]==lname) & (bounced["touch_lbl"]==tl)]
    if len(s) < 3:
        print(f"  {label:<14} {side:<7} {'<3':>7}")
        continue
    n   = len(s)
    nd  = s["date"].nunique()
    tpd = n / TRADING_DAYS
    tpw = n / TRADING_WEEKS
    m30 = s["mfe30"].mean()
    h50 = s["hit_>=0.50%"].mean() * 100
    h75 = s["hit_>=0.75%"].mean() * 100
    mark = " <<<" if h50>=45 else ("  <<" if h50>=30 else "")
    print(f"  {label:<14} {side:<7} {n:>7}  {nd:>5}  "
          f"{tpd:>6.2f}  {tpw:>7.2f}  {m30:>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")

# Combined: all 1st-touch best setups together
print(f"\n  {'--- COMBINED: PML/1H_Res/4H_Res 1st touch ---'}")
combined = bounced[
    (bounced["touch_lbl"]=="1st") &
    (bounced["level"].isin(["PML","1H_Res","4H_Res","1H_Sup","4H_Sup"]))
]
n   = len(combined)
tpd = n / TRADING_DAYS
tpw = n / TRADING_WEEKS
h50 = combined["hit_>=0.50%"].mean()*100
h75 = combined["hit_>=0.75%"].mean()*100
print(f"  {'ALL HIGH-Q 1st':<14} {'both':<7} {n:>7}  "
      f"{combined['date'].nunique():>5}  "
      f"{tpd:>6.2f}  {tpw:>7.2f}  "
      f"{combined['mfe30'].mean():>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%")

# Per-symbol breakdown for the three top setups
print(f"\n{'='*W}")
print(f"  PER-SYMBOL BREAKDOWN — top setups")
print(f"{'='*W}")
for label, lname, tl in [
    ("PML 1st",    "PML",    "1st"),
    ("1H_Res 1st", "1H_Res", "1st"),
    ("4H_Res 1st", "4H_Res", "1st"),
    ("PMH 1st",    "PMH",    "1st"),
]:
    s = bounced[(bounced["level"]==lname) & (bounced["touch_lbl"]==tl)]
    print(f"\n  {label}  (total N={len(s)}, {len(s)/TRADING_WEEKS:.2f} T/wk across all syms)")
    print(f"  {'Sym':<6} {'N':>5}  {'T/Wk':>6}  {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*50}")
    sym_rows = []
    for sym in syms:
        ss = s[s["sym"]==sym]
        if len(ss) < 3:
            continue
        sym_rows.append((sym, len(ss), len(ss)/TRADING_WEEKS,
                         ss["mfe30"].mean(),
                         ss["hit_>=0.50%"].mean()*100,
                         ss["hit_>=0.75%"].mean()*100))
    for sym, n2, tpw2, m30, h50, h75 in sorted(sym_rows, key=lambda x: -x[2]):
        mark = " <<<" if h50>=45 else ("  <<" if h50>=30 else "")
        print(f"  {sym:<6} {n2:>5}  {tpw2:>6.2f}  {m30:>6.3f}%  {h50:>8.1f}%  {h75:>8.1f}%{mark}")
