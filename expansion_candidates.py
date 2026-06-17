import pandas as pd

# symbols already in our filtered universe
current = pd.read_csv("ideas_backtest_results.csv").sym.unique().tolist()

# full profile with fundamentals
profile = pd.read_csv("symbol_profile.csv")
profile = profile.rename(columns={"Unnamed: 0": "sym"})

# exclude what we already have
candidates = profile[~profile.sym.isin(current)].copy()

# apply slightly relaxed filters: MCap>50B, Vol>3M, ATR<6.5%
candidates = candidates[
    (candidates.market_cap_b >= 50) &
    (candidates.avg_volume   >= 3e6) &
    (candidates.atr_pct      <  6.5)
].copy()

candidates = candidates.sort_values("ev", ascending=False)

print(f"Expansion candidates (MCap>50B, Vol>3M, ATR<6.5%) — sorted by backtest EV")
print(f"{'Sym':<7} {'Sector':<25} {'MCap$B':>7} {'ATR%':>5} {'GapF%':>6} {'AvgVol':>10} {'Beta':>5} {'EV':>8}")
print("-"*80)
for _, r in candidates.iterrows():
    ev  = f"{r.ev:>+6.3f}%" if pd.notna(r.get('ev')) else "   N/A"
    mc  = f"{r.market_cap_b:.0f}" if pd.notna(r.get('market_cap_b')) else "N/A"
    atr = f"{r.atr_pct:.2f}" if pd.notna(r.get('atr_pct')) else "N/A"
    gf  = f"{r.gap_days_pct:.1f}" if pd.notna(r.get('gap_days_pct')) else "N/A"
    vol = f"{int(r.avg_volume):>10,}" if pd.notna(r.get('avg_volume')) else "N/A"
    beta= f"{r.beta:.2f}" if pd.notna(r.get('beta')) else " N/A"
    sec = str(r.get('sector',''))[:25]
    print(f"{r.sym:<7} {sec:<25} {mc:>7} {atr:>5} {gf:>6} {vol:>10} {beta:>5} {ev:>8}")
