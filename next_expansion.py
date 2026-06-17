import pandas as pd, os

df = pd.read_csv("expanded_results.csv")
profile = pd.read_csv("symbol_profile.csv").rename(columns={"Unnamed: 0":"sym"})

# symbols with negative EV in 2hr hold — drop these
sym_ev = df.groupby("sym")["ret_2h"].mean()
losers  = sym_ev[sym_ev <= 0].index.tolist()
keepers = sym_ev[sym_ev >  0].index.tolist()

print(f"Current universe: {df.sym.nunique()} syms")
print(f"Dropping ({len(losers)}): {', '.join(sorted(losers))}")
print(f"Keeping  ({len(keepers)}): {', '.join(sorted(keepers))}\n")

# find 10 new candidates from profile not already in universe
already = df.sym.unique().tolist()
DATA_DIR = "data/1m"

candidates = profile[
    (~profile.sym.isin(already)) &
    (profile.market_cap_b >= 50) &
    (profile.avg_volume   >= 3e6) &
    (profile.atr_pct      <  6.5)
].copy().sort_values("ev", ascending=False)

print("Next expansion candidates (have data file, not yet tested):")
print(f"{'Sym':<7} {'Sector':<25} {'MCap$B':>7} {'ATR%':>5} {'AvgVol':>10} {'EV(gap_all)':>12}")
print("-"*72)
shown = 0
for _, r in candidates.iterrows():
    if not os.path.exists(os.path.join(DATA_DIR, f"{r.sym}.parquet")):
        continue
    ev  = f"{r.ev:>+6.3f}%" if pd.notna(r.get('ev')) else "   N/A"
    mc  = f"{r.market_cap_b:.0f}" if pd.notna(r.get('market_cap_b')) else "N/A"
    atr = f"{r.atr_pct:.2f}"  if pd.notna(r.get('atr_pct'))  else "N/A"
    vol = f"{int(r.avg_volume):>10,}" if pd.notna(r.get('avg_volume')) else "N/A"
    sec = str(r.get('sector',''))[:25]
    print(f"{r.sym:<7} {sec:<25} {mc:>7} {atr:>5} {vol:>10} {ev:>12}")
    shown += 1
    if shown >= 20:
        break
