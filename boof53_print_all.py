"""Print full leaderboard for all symbols from saved CSV"""
import pandas as pd

df = pd.read_csv("boof53_leaderboard_all.csv")
bounced = df[df["bounced"] == True]
first   = bounced[bounced["touch_lbl"] == "1st"]

DAYS  = df["date"].nunique()
WEEKS = DAYS / 5

SYMBOLS = sorted(df["sym"].unique())

def sym_row(sym, s):
    if len(s) < 3: return None
    return {
        "sym":   sym,
        "n":     len(s),
        "days":  s["date"].nunique(),
        "t_wk":  len(s) / WEEKS,
        "mfe15": s["mfe15"].mean(),
        "mfe30": s["mfe30"].mean(),
        "mfe60": s["mfe60"].mean(),
        "h50":   s["hit_>=0.50%"].mean() * 100,
        "h75":   s["hit_>=0.75%"].mean() * 100,
    }

def print_table(rows, title, sort_col="mfe30"):
    rows = [r for r in rows if r]
    rows = sorted(rows, key=lambda x: -x[sort_col])
    W = 84
    print(f"\n{'='*W}")
    print(f"  {title}  |  {DAYS}d  (~{WEEKS:.1f}wk)  |  1st touch  bounce>=0.15%  |  sorted by {sort_col}")
    print(f"{'='*W}")
    print(f"  {'Rank':<5} {'Sym':<6} {'N':>5}  {'T/Wk':>6}  "
          f"{'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*80}")
    for rank, r in enumerate(rows, 1):
        mark = " <<<" if r["h50"] >= 55 else ("  <<" if r["h50"] >= 40 else "")
        print(f"  {rank:<5} {r['sym']:<6} {r['n']:>5}  {r['t_wk']:>6.2f}  "
              f"{r['mfe15']:>6.3f}%  {r['mfe30']:>6.3f}%  {r['mfe60']:>6.3f}%   "
              f"{r['h50']:>7.1f}%  {r['h75']:>7.1f}%{mark}")

# ── 1. All levels combined, both sides ──────────────────────────────────────
rows = [sym_row(sym, first[first["sym"]==sym]) for sym in SYMBOLS]
print_table(rows, "ALL LEVELS — Long + Short combined")

# ── 2. Long only ─────────────────────────────────────────────────────────────
rows = [sym_row(sym, first[(first["sym"]==sym) & (first["side"]=="long")]) for sym in SYMBOLS]
print_table(rows, "LONG — All support levels (PML, PDL, 1H_Sup, 4H_Sup)", sort_col="mfe30")

# ── 3. Short only ────────────────────────────────────────────────────────────
rows = [sym_row(sym, first[(first["sym"]==sym) & (first["side"]=="short")]) for sym in SYMBOLS]
print_table(rows, "SHORT — All resistance levels (PMH, PDH, 1H_Res, 4H_Res)", sort_col="mfe30")

# ── 4. PML 1st ───────────────────────────────────────────────────────────────
rows = [sym_row(sym, first[(first["sym"]==sym) & (first["level"]=="PML")]) for sym in SYMBOLS]
print_table(rows, "PML 1st touch only")

# ── 5. PMH 1st ───────────────────────────────────────────────────────────────
rows = [sym_row(sym, first[(first["sym"]==sym) & (first["level"]=="PMH")]) for sym in SYMBOLS]
print_table(rows, "PMH 1st touch only")

# ── 6. 1H+4H combined ────────────────────────────────────────────────────────
hv = first[first["level"].isin(["1H_Res","4H_Res","1H_Sup","4H_Sup"])]
rows = [sym_row(sym, hv[hv["sym"]==sym]) for sym in SYMBOLS]
print_table(rows, "1H + 4H levels only (both sides)", sort_col="h50")

print(f"\n  Source: boof53_leaderboard_all.csv  |  {len(df):,} total touch records")
