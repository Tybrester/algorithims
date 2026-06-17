"""
Stock account simulation
Account: $3,000 equity, $12,000 buying power (4x margin)
Risk per trade: 5% of equity = $150
Stop loss: -1% on stock (from our strategy)
Position size: risk / stop = $150 / 1% = $15,000 notional
But capped at $12,000 buying power
2hr hold, no TP/SL on stock (time exit)
"""
import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

START_EQUITY  = 3000.0
BUYING_POWER  = 12000.0  # 4x margin
RISK_PCT      = 0.05     # 5% of equity per trade
STOP_PCT      = 0.01     # -1% stop on stock

# Position size = risk_dollar / stop_pct
# e.g. $150 risk / 1% stop = $15,000 notional -> but capped at $12,000 BP

def sim_stock(df, start, bp, risk_pct, stop_pct, compound=True):
    equity = start
    curve  = []
    for _, row in df.iterrows():
        risk_dollar = equity * risk_pct
        position    = min(risk_dollar / stop_pct, bp)  # cap at buying power
        ret         = row['ret_2h'] / 100.0             # stock return

        # apply stop: if stock fell more than stop, exit at stop
        actual_ret = max(ret, -stop_pct)
        pnl = position * actual_ret
        equity += pnl
        if compound and equity > 0:
            bp = equity * 4  # recompute buying power as equity grows
        curve.append(round(equity, 2))
    return curve

# Flat equity sizing
flat   = sim_stock(df, START_EQUITY, BUYING_POWER, RISK_PCT, STOP_PCT, compound=False)
# Compounded
comp   = sim_stock(df, START_EQUITY, BUYING_POWER, RISK_PCT, STOP_PCT, compound=True)

df['flat_eq'] = flat
df['comp_eq'] = comp
df['month']   = df['date'].dt.to_period('M')

def max_dd(curve):
    peak = curve[0]; dd = 0
    for v in curve:
        if v > peak: peak = v
        if (v-peak)/peak*100 < dd: dd = (v-peak)/peak*100
    return dd

print("=" * 60)
print("STOCK ACCOUNT — $3K equity / $12K buying power / 5% risk")
print("2hr hold | -1% hard stop | Gap>1% + RVOL>=1.5 + Early")
print("=" * 60)

print(f"\n  {'Sizing':<28}  {'End Equity':>11}  {'Return':>8}  {'MaxDD':>8}")
print(f"  {'-'*58}")
print(f"  {'Flat (5% of $3K always)':<28}  ${flat[-1]:>10,.0f}  "
      f"{(flat[-1]-START_EQUITY)/START_EQUITY*100:>+7.0f}%  {max_dd(flat):>+7.1f}%")
print(f"  {'Compounded (5% of equity)':<28}  ${comp[-1]:>10,.0f}  "
      f"{(comp[-1]-START_EQUITY)/START_EQUITY*100:>+7.0f}%  {max_dd(comp):>+7.1f}%")

print(f"\n{'='*60}")
print("MONTHLY — Compounded")
print(f"{'='*60}")
monthly = df.groupby('month').last()[['flat_eq','comp_eq']]
print(f"  {'Month':<12}  {'Flat':>12}  {'Compounded':>12}  {'BP (comp)':>12}")
print(f"  {'-'*52}")
for month, row in monthly.iterrows():
    print(f"  {str(month):<12}  ${row.flat_eq:>11,.0f}  ${row.comp_eq:>11,.0f}  "
          f"${row.comp_eq*4:>11,.0f}")

print(f"\n  Start equity:    $3,000   (BP: $12,000)")
print(f"  End equity:      ${comp[-1]:>8,.0f}   (BP: ${comp[-1]*4:>8,.0f})")

# Per trade stats
positions = []
equity = START_EQUITY; bp = BUYING_POWER
for _, row in df.iterrows():
    risk_dollar = equity * RISK_PCT
    position    = min(risk_dollar / STOP_PCT, bp)
    actual_ret  = max(row['ret_2h']/100.0, -STOP_PCT)
    pnl         = position * actual_ret
    positions.append(pnl)
    equity += pnl
    bp = equity * 4

pos_s = pd.Series(positions)
print(f"\n{'='*60}")
print("PER TRADE STATS (compounded)")
print(f"{'='*60}")
print(f"  Avg winner:   ${pos_s[pos_s>0].mean():>+8,.0f}")
print(f"  Avg loser:    ${pos_s[pos_s<0].mean():>+8,.0f}")
print(f"  Best trade:   ${pos_s.max():>+8,.0f}")
print(f"  Worst trade:  ${pos_s.min():>+8,.0f}")
print(f"  Avg/trade:    ${pos_s.mean():>+8,.0f}")
print(f"  Win rate:     {(pos_s>0).mean()*100:.1f}%")
w=pos_s[pos_s>0].sum(); l=pos_s[pos_s<0].abs().sum()
print(f"  Profit factor:{w/l:.3f}")
print(f"  Total P&L:    ${pos_s.sum():>+8,.0f}")
cal_weeks = (df.date.max()-df.date.min()).days/7
print(f"  Avg/week:     ${pos_s.sum()/cal_weeks:>+8,.0f}")
