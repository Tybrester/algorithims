import pandas as pd

print("=" * 70)
print("BOOF 30 — 2-Bar Short Ignition Results")
print("=" * 70)

# Full day results (from earlier)
print("\n📊 FULL DAY (9:30 AM - 4:00 PM) — 1-Minute")
print("-" * 70)
try:
    df = pd.read_csv('boof30_mfe_mae_signals.csv')
    print(f"Signals: {len(df)}")
    for period in ['15m', '30m', '60m']:
        mfe = df[f'mfe_{period}'].dropna()
        mae = df[f'mae_{period}'].dropna()
        if len(mfe) > 0:
            print(f"\n{period}:")
            print(f"  MFE (favorable drop):  Avg={mfe.mean()*100:>5.2f}%  Med={mfe.median()*100:>5.2f}%  P90={mfe.quantile(0.90)*100:>5.2f}%")
            print(f"  MAE (adverse rise):    Avg={mae.mean()*100:>5.2f}%  Med={mae.median()*100:>5.2f}%")
except Exception as e:
    print(f"Error: {e}")

# 11 AM only results
print("\n" + "=" * 70)
print("📊 MORNING ONLY (9:30 AM - 11:00 AM) — 5-Minute")
print("-" * 70)
try:
    df5 = pd.read_csv('boof30_mfe_mae_5m_11am.csv')
    print(f"Signals: {len(df5)}")
    for bars, mins in [(3, '15m'), (6, '30m'), (12, '60m')]:
        mfe = df5[f'mfe_{bars}'].dropna()
        mae = df5[f'mae_{bars}'].dropna()
        if len(mfe) > 0:
            print(f"\n{mins} ({bars} bars):")
            print(f"  MFE: Avg={mfe.mean()*100:>5.2f}%  Med={mfe.median()*100:>5.2f}%  P90={mfe.quantile(0.90)*100:>5.2f}%")
            print(f"  MAE: Avg={mae.mean()*100:>5.2f}%  Med={mae.median()*100:>5.2f}%")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 70)
