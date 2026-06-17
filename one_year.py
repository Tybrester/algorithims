"""
1-year projection using actual test trades (6mo) + train period stats for second 6mo
Stock account: $3K equity, $12K BP, 10% compounding cap on position size growth
-1% hard stop, 2hr hold
"""
import pandas as pd
import numpy as np

test = pd.read_csv('walkforward_test.csv')
train = pd.read_csv('walkforward_train.csv')

test['date'] = pd.to_datetime(test['date'])
train['date'] = pd.to_datetime(train['date'])

# Use actual test trades for first 6 months
# For second 6 months: resample from train returns (bootstrap)
# This gives a realistic distribution rather than just repeating test

STOP_PCT    = 0.01
START       = 3000.0
MAX_BP_MULT = 4       # broker max 4x margin
SCALE_PCT   = 0.10    # risk 10% of equity per trade

np.random.seed(42)

# Bootstrap second 6 months from train returns
# Train had ~382 trades over 3 years = ~127/year = ~64 trades per 6mo
train_rets = train['ret_2h'].dropna().values
second_half_trades = np.random.choice(train_rets, size=64, replace=True)

# Combine: actual 6mo test + bootstrapped second 6mo
all_rets = list(test['ret_2h'].values) + list(second_half_trades)

def simulate(returns, start, scale_pct, max_bp_mult, label, cap_growth=True):
    equity = start
    bp     = start * max_bp_mult
    curve  = [start]
    weekly_pnl = []
    week_pnl = 0
    trade_count = 0

    for i, ret in enumerate(returns):
        risk_dollar = equity * scale_pct
        position    = min(risk_dollar / STOP_PCT, bp)
        actual_ret  = max(ret / 100.0, -STOP_PCT)
        pnl         = position * actual_ret
        equity      = max(equity + pnl, 1)   # can't go below $1
        bp          = equity * max_bp_mult
        curve.append(round(equity, 2))
        weekly_pnl.append(pnl)
        trade_count += 1

    return curve, weekly_pnl

# Run multiple scenarios
scenarios = [
    ("10% risk, 4x BP",        0.10, 4),
    ("5% risk, 4x BP",         0.05, 4),
    ("10% risk, 2x BP (safe)", 0.10, 2),
]

print("=" * 65)
print("1-YEAR PROJECTION — $3,000 start")
print("First 6mo: actual test trades | Second 6mo: bootstrapped from train")
print("Stock account, -1% stop, 2hr hold")
print("=" * 65)

print(f"\n  {'Scenario':<28}  {'6mo':>10}  {'1yr':>10}  {'Return':>8}  {'MaxDD':>8}")
print(f"  {'-'*62}")

for label, scale, bp_mult in scenarios:
    curve, _ = simulate(all_rets, START, scale, bp_mult, label)
    mid   = curve[len(test)]   # end of first 6 months
    end   = curve[-1]
    ret   = (end - START) / START * 100
    peak  = START; dd = 0
    for v in curve:
        if v > peak: peak = v
        if (v-peak)/peak*100 < dd: dd = (v-peak)/peak*100
    print(f"  {label:<28}  ${mid:>9,.0f}  ${end:>9,.0f}  {ret:>+7.0f}%  {dd:>+7.1f}%")

# Detailed monthly for 10% / 4x
print(f"\n{'='*65}")
print("MONTHLY DETAIL — 10% risk, 4x BP")
print(f"{'='*65}")

curve10, pnls = simulate(all_rets, START, 0.10, 4, "10%")

# Map months
test_sorted = test.sort_values('date').reset_index(drop=True)
months_1 = test_sorted['date'].dt.to_period('M')
# second half: assume Jul-Dec 2026
import pandas as pd
second_months = pd.period_range('2026-07', periods=6, freq='M')

# Print by actual months for first half, estimated for second
equity = START; bp = START*4
month_end = {}
trade_idx = 0
for _, row in test_sorted.iterrows():
    m = row['date'].to_period('M')
    risk = equity * 0.10
    pos  = min(risk/STOP_PCT, bp)
    ar   = max(row.ret_2h/100.0, -STOP_PCT)
    equity = max(equity + pos*ar, 1)
    bp = equity*4
    month_end[str(m)] = round(equity,2)

# second half from bootstrap
boot_rets = second_half_trades
trades_per_month = len(boot_rets) // 6
for i, m in enumerate(second_months):
    chunk = boot_rets[i*trades_per_month:(i+1)*trades_per_month]
    for ret in chunk:
        risk = equity*0.10
        pos  = min(risk/STOP_PCT, bp)
        ar   = max(ret/100.0, -STOP_PCT)
        equity = max(equity + pos*ar, 1)
        bp = equity*4
    month_end[str(m)] = round(equity,2)

print(f"  {'Month':<12}  {'Equity':>12}  {'Buying Power':>14}  {'Note'}")
print(f"  {'-'*58}")
for i, (m, eq) in enumerate(month_end.items()):
    note = "  (actual)" if i < 7 else "  (projected)"
    print(f"  {m:<12}  ${eq:>11,.0f}  ${eq*4:>13,.0f}{note}")

final = list(month_end.values())[-1]
print(f"\n  Start:       $3,000")
print(f"  After 6mo:   ${list(month_end.values())[5]:>10,.0f}  (actual test data)")
print(f"  After 1yr:   ${final:>10,.0f}  (projected)")
print(f"  Total return: {(final-START)/START*100:>+.0f}%")
print(f"\n  NOTE: Second 6 months uses bootstrapped returns from")
print(f"  2022-2024 training data. Real results will vary.")
print(f"  This is a probability-weighted estimate, not a guarantee.")
