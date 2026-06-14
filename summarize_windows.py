import pandas as pd

files = {
    '9:00-9:30':   'boof33_ranked_900-930.csv',
    '9:30-10:00':  'boof33_ranked_930-1000.csv',
    '10:00-10:30': 'boof33_ranked_1000-1030.csv',
    '10:30-11:00': 'boof33_ranked_1030-1100.csv',
    '11:00-11:30': 'boof33_ranked_1100-1130.csv',
    '11:30-12:00': 'boof33_ranked_1130-1200.csv',
    '9:00-10:00':  'boof33_ranked_900-1000.csv',
    '9:00-10:30':  'boof33_ranked_900-1030.csv',
    '9:00-12:00':  'boof33_ranked_900-1200.csv',
    '9:30-11:00':  'boof33_ranked_930-1100.csv',
    '9:30-12:00':  'boof33_ranked_930-1200.csv',
    'All Day':     'boof33_ranked_All_Day.csv',
}

rows = []
for label, f in files.items():
    df = pd.read_csv(f)
    rows.append(dict(
        window=label,
        trades=int(df['n'].sum()),
        avg_pf=df['pf'].mean(),
        avg_ev=df['ev'].mean() * 100,
        avg_mfe=df['avg_mfe'].mean(),
        med_mfe=df['med_mfe'].mean(),
    ))

rows.sort(key=lambda x: x['avg_pf'], reverse=True)
print(f"{'Window':<14}  {'Trades':>7}  {'AvgPF':>6}  {'AvgEV%':>8}  {'AvgMFE':>7}  {'MedMFE':>7}")
print('-' * 65)
for r in rows:
    print(f"{r['window']:<14}  {r['trades']:7d}  {r['avg_pf']:6.2f}  {r['avg_ev']:8.4f}%  {r['avg_mfe']:7.3f}%  {r['med_mfe']:7.3f}%")
