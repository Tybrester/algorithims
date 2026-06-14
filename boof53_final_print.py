"""Print corrected full leaderboard — clean, no truncation"""
import pandas as pd

df     = pd.read_csv("boof53_leaderboard_all.csv")
b      = df[(df["bounced"]==True) & (df["touch_lbl"]=="1st")]
WEEKS  = df["date"].nunique() / 5
DAYS   = df["date"].nunique()
SYMS   = sorted(df["sym"].unique())

def build_rows(subset, sort="mfe30"):
    rows = []
    for sym in SYMS:
        s = subset[subset["sym"]==sym]
        if len(s) < 3: continue
        rows.append(dict(
            sym=sym, n=len(s),
            t_wk=len(s)/WEEKS,
            mfe15=s["mfe15"].mean(),
            mfe30=s["mfe30"].mean(),
            mfe60=s["mfe60"].mean(),
            h50=s["hit_>=0.50%"].mean()*100,
            h75=s["hit_>=0.75%"].mean()*100,
        ))
    return sorted(rows, key=lambda x: -x[sort])

def print_table(rows, title):
    print(f"\n{'='*92}")
    print(f"  {title}  |  {DAYS}d (~{WEEKS:.1f}wk)  |  1st touch bounce>=0.15%")
    print(f"{'='*92}")
    print(f"  {'Rk':<4} {'Sym':<6} {'N':>5} {'T/Wk':>6}  {'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
    print(f"  {'-'*88}")
    for rk, r in enumerate(rows, 1):
        mk = " <<<" if r["h50"]>=55 else ("  <<" if r["h50"]>=40 else "")
        print(f"  {rk:<4} {r['sym']:<6} {r['n']:>5} {r['t_wk']:>6.2f}  "
              f"{r['mfe15']:>6.3f}%  {r['mfe30']:>6.3f}%  {r['mfe60']:>6.3f}%  "
              f"{r['h50']:>8.1f}%  {r['h75']:>8.1f}%{mk}")

# ── 1. All levels both sides ─────────────────────────────────────────────────
print_table(build_rows(b), "ALL LEVELS — Long + Short combined")

# ── 2. Long only ─────────────────────────────────────────────────────────────
print_table(build_rows(b[b["side"]=="long"]), "LONG — PML, PDL, 1H_Sup, 4H_Sup")

# ── 3. Short only ────────────────────────────────────────────────────────────
print_table(build_rows(b[b["side"]=="short"]), "SHORT — PMH, PDH, 1H_Res, 4H_Res")

# ── 4. PML only ──────────────────────────────────────────────────────────────
print_table(build_rows(b[b["level"]=="PML"]), "PML 1st touch")

# ── 5. PMH only ──────────────────────────────────────────────────────────────
print_table(build_rows(b[b["level"]=="PMH"]), "PMH 1st touch")

# ── 6. 1H+4H only ────────────────────────────────────────────────────────────
hv = b[b["level"].isin(["1H_Res","4H_Res","1H_Sup","4H_Sup"])]
print_table(build_rows(hv, sort="h50"), "1H + 4H levels only (both sides) — sorted by >=0.50%")

# ── 7. T/Week summary ────────────────────────────────────────────────────────
print(f"\n{'='*92}")
print(f"  TRADES PER WEEK — all levels, 1st touch, bounce>=0.15%  |  sorted by T/Wk")
print(f"{'='*92}")
print(f"  {'Rk':<4} {'Sym':<6} {'Tot/Wk':>8}  {'Lng/Wk':>8}  {'Sht/Wk':>8}  {'MFE30':>7}  {'>=0.50%':>8}  {'>=0.75%':>8}")
print(f"  {'-'*80}")
trows = []
for sym in SYMS:
    s  = b[b["sym"]==sym]
    sl = s[s["side"]=="long"]; ss = s[s["side"]=="short"]
    if len(s) < 3: continue
    trows.append(dict(sym=sym, tot=len(s)/WEEKS, lng=len(sl)/WEEKS,
                      sht=len(ss)/WEEKS, mfe30=s["mfe30"].mean(),
                      h50=s["hit_>=0.50%"].mean()*100,
                      h75=s["hit_>=0.75%"].mean()*100))
trows.sort(key=lambda x: -x["tot"])
total = 0
for rk, r in enumerate(trows, 1):
    mk = " <<<" if r["h50"]>=55 else ("  <<" if r["h50"]>=40 else "")
    print(f"  {rk:<4} {r['sym']:<6} {r['tot']:>8.2f}  {r['lng']:>8.2f}  {r['sht']:>8.2f}  "
          f"{r['mfe30']:>6.3f}%  {r['h50']:>8.1f}%  {r['h75']:>8.1f}%{mk}")
    total += r["tot"]
print(f"  {'-'*80}")
print(f"  {'ALL':<10} {total:>8.2f}")

# ── 8. Tier summary ──────────────────────────────────────────────────────────
tier1 = ["RKLB","HIMS","MU","APP","SMCI","ARM","TEM","HOOD","COIN","PLTR","ORCL","CRM","AMD","AVGO"]
tier2 = ["TSLA","NVDA","ADBE","LLY","UNH","META","AMZN","GOOGL","NFLX"]
tier3 = ["MSFT","WMT","JPM","AAPL","COST","IWM"]
print(f"\n{'='*92}")
print(f"  TIER SUMMARY")
print(f"{'='*92}")
print(f"  {'Tier':<36} {'T/Wk':>7}  {'MFE30':>7}  {'>=0.50%':>9}  {'>=0.75%':>9}")
print(f"  {'-'*72}")
for lbl, tier in [("Tier 1 — Elite  (14)", tier1),
                  ("Tier 2 — Strong  (9)", tier2),
                  ("Tier 3 — Weak    (6)", tier3)]:
    ts  = b[b["sym"].isin(tier)]
    tpw = sum(r["tot"] for r in trows if r["sym"] in tier)
    print(f"  {lbl:<36} {tpw:>7.1f}  {ts['mfe30'].mean():>6.3f}%  "
          f"{ts['hit_>=0.50%'].mean()*100:>9.1f}%  "
          f"{ts['hit_>=0.75%'].mean()*100:>9.1f}%")
print(f"\n  Tier 1: {', '.join(tier1)}")
print(f"  Tier 2: {', '.join(tier2)}")
print(f"  Tier 3: {', '.join(tier3)}")
