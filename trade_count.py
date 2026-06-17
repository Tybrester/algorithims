import pandas as pd
df = pd.read_csv('walkforward_test.csv')
df['date'] = pd.to_datetime(df['date'])
total = len(df)
start = df.date.min().date()
end   = df.date.max().date()
cal_weeks = (df.date.max() - df.date.min()).days / 7
trad_days = df.date.nunique()
trad_weeks = trad_days / 5

print(f"Total trades:    {total}")
print(f"Date range:      {start} to {end}")
print(f"Calendar weeks:  {cal_weeks:.1f}")
print(f"Trading weeks:   {trad_weeks:.1f}")
print(f"Trades/cal week: {total/cal_weeks:.1f}")
print(f"Trades/trd week: {total/trad_weeks:.1f}")
print()
df['week'] = df['date'].dt.to_period('W')
weekly = df.groupby('week').size()
print(f"Min per week:  {weekly.min()}")
print(f"Max per week:  {weekly.max()}")
print(f"Median/week:   {weekly.median():.0f}")
print()
print(weekly.to_string())
