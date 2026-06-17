import pandas as pd

df = pd.read_csv("ideas_backtest_results.csv")
combo = df[(df.time_bucket == "early") & (df.rvol >= 1.5)]

df["date"] = pd.to_datetime(df["date"])
combo = combo.copy()
combo["date"] = pd.to_datetime(combo["date"])

date_range_days = (df["date"].max() - df["date"].min()).days
trading_days    = df["date"].nunique()
trading_weeks   = trading_days / 5

total  = len(combo)
per_day  = total / trading_days
per_week = total / trading_weeks

print(f"Data range:     {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Trading days:   {trading_days}")
print(f"Trading weeks:  {trading_weeks:.1f}")
print(f"Total trades:   {total}")
print(f"Trades/day:     {per_day:.2f}")
print(f"Trades/week:    {per_week:.1f}")

print(f"\n-- Per week breakdown --")
combo["week"] = combo["date"].dt.to_period("W")
weekly = combo.groupby("week").size()
print(f"  Min:   {weekly.min()} trades")
print(f"  Max:   {weekly.max()} trades")
print(f"  Mean:  {weekly.mean():.1f} trades")
print(f"  Median:{weekly.median():.0f} trades")
print()
print(weekly.to_string())

print(f"\n-- Trades per day of week --")
combo["dow"] = combo["date"].dt.day_name()
dow_order = ["Monday","Tuesday","Wednesday","Thursday","Friday"]
print(combo.groupby("dow").size().reindex(dow_order).to_string())
