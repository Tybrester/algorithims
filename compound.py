import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')

DELTA = 0.50; GAMMA = 0.025; THETA = 0.025; OPT_PCT = 0.0130
START = 2500.0
RISK_PCT = 0.20   # 20% of account per trade

def calc_pnl_pct(stock_ret, theta_frac):
    r = stock_ret / 100.0
    opt_move = (DELTA * abs(r) + 0.5 * GAMMA * r * r) * np.sign(r)
    return opt_move / OPT_PCT - theta_frac

def get_outcome_pcts(r):
    if r <= -1.0:
        return calc_pnl_pct(-1.0, THETA*0.25), calc_pnl_pct(-1.0, THETA*0.25), "STOP"
    elif r >= 1.5:
        return calc_pnl_pct(0.75, THETA*0.35), calc_pnl_pct(1.50, THETA*0.65), "BOTH_TP"
    elif r >= 0.75:
        return calc_pnl_pct(0.75, THETA*0.35), calc_pnl_pct(r, THETA), "LEG1_TP"
    else:
        return calc_pnl_pct(r, THETA), calc_pnl_pct(r, THETA), "HOLD_2HR"

df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# ── Flat sizing ───────────────────────────────────────────────────────────────
acct_flat = START
flat_curve = []
for _, row in df.iterrows():
    risk = 500.0
    per_c = risk / 2
    l1, l2, oc = get_outcome_pcts(row.ret_2h)
    pnl = (l1 + l2) * per_c
    acct_flat += pnl
    flat_curve.append(round(acct_flat, 2))

# ── Compounded (20% risk per trade) ──────────────────────────────────────────
acct_comp = START
comp_curve = []
for _, row in df.iterrows():
    risk  = acct_comp * RISK_PCT
    per_c = risk / 2
    l1, l2, oc = get_outcome_pcts(row.ret_2h)
    pnl = (l1 + l2) * per_c
    acct_comp += pnl
    comp_curve.append(round(acct_comp, 2))

# ── Compounded at 10% risk ────────────────────────────────────────────────────
acct_cons = START
cons_curve = []
for _, row in df.iterrows():
    risk  = acct_cons * 0.10
    per_c = risk / 2
    l1, l2, oc = get_outcome_pcts(row.ret_2h)
    pnl = (l1 + l2) * per_c
    acct_cons += pnl
    cons_curve.append(round(acct_cons, 2))

df['flat']  = flat_curve
df['comp']  = comp_curve
df['cons']  = cons_curve
df['week']  = df['date'].dt.to_period('W')

print("=" * 60)
print(f"ACCOUNT GROWTH — Start: $2,500")
print("=" * 60)
print(f"\n  {'Sizing':<30}  {'End Balance':>12}  {'Return':>8}")
print(f"  {'-'*54}")
print(f"  {'Flat $500/trade':<30}  ${flat_curve[-1]:>11,.0f}  {(flat_curve[-1]-START)/START*100:>+7.0f}%")
print(f"  {'Compounded 20%/trade':<30}  ${comp_curve[-1]:>11,.0f}  {(comp_curve[-1]-START)/START*100:>+7.0f}%")
print(f"  {'Compounded 10%/trade (safe)':<30}  ${cons_curve[-1]:>11,.0f}  {(cons_curve[-1]-START)/START*100:>+7.0f}%")

print(f"\n{'='*60}")
print("MONTHLY SNAPSHOTS — Compounded 20%")
print(f"{'='*60}")
df['month'] = df['date'].dt.to_period('M')
monthly = df.groupby('month').last()[['comp','cons','flat']]
print(f"  {'Month':<12}  {'Flat $500':>12}  {'10% risk':>12}  {'20% risk':>12}")
print(f"  {'-'*52}")
for month, row in monthly.iterrows():
    print(f"  {str(month):<12}  ${row.flat:>11,.0f}  ${row.cons:>11,.0f}  ${row.comp:>11,.0f}")

print(f"\n  Start:  $2,500")
print(f"  End:    ${comp_curve[-1]:>10,.0f}  (20% compounded)")

# Drawdown
peak = START
max_dd = 0
for v in comp_curve:
    if v > peak: peak = v
    dd = (v - peak) / peak * 100
    if dd < max_dd: max_dd = dd
print(f"\n  Max Drawdown (20% comp): {max_dd:.1f}%")
peak = START
max_dd2 = 0
for v in cons_curve:
    if v > peak: peak = v
    dd = (v - peak) / peak * 100
    if dd < max_dd2: max_dd2 = dd
print(f"  Max Drawdown (10% comp): {max_dd2:.1f}%")
