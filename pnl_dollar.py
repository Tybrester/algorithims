"""
Dollar P&L projection
Account: $2,500
Risk per trade: $500 (2 contracts, $250 per contract premium)
Weekly 5DTE ATM calls, scale-out L1=+0.75% L2=+1.50%, Stop=-1%
"""
import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')

# Weekly 5DTE profile
DELTA   = 0.50
GAMMA   = 0.025
THETA   = 0.025   # 2.5% of premium over 2hr hold
OPT_PCT = 0.0130  # option costs ~1.3% of stock price

ACCOUNT   = 2500
RISK_PER  = 500   # total risk per trade (2 contracts x $250 each)
PER_CONTRACT = RISK_PER / 2  # $250 per contract = premium paid

LEG1 = 0.75
LEG2 = 1.50
STOP = -1.00

def calc_pnl_pct(stock_ret, theta_frac):
    r = stock_ret / 100.0
    opt_move = (DELTA * abs(r) + 0.5 * GAMMA * r * r) * np.sign(r)
    pnl_frac = opt_move / OPT_PCT - theta_frac
    return pnl_frac

rows = []
for _, row in df.iterrows():
    r = row['ret_2h']

    if r <= STOP:
        l1_pct = calc_pnl_pct(STOP, THETA * 0.25)
        l2_pct = calc_pnl_pct(STOP, THETA * 0.25)
        oc = "STOP"
    elif r >= LEG2:
        l1_pct = calc_pnl_pct(LEG1, THETA * 0.35)
        l2_pct = calc_pnl_pct(LEG2, THETA * 0.65)
        oc = "BOTH_TP"
    elif r >= LEG1:
        l1_pct = calc_pnl_pct(LEG1, THETA * 0.35)
        l2_pct = calc_pnl_pct(r,    THETA)
        oc = "LEG1_TP"
    else:
        l1_pct = calc_pnl_pct(r, THETA)
        l2_pct = calc_pnl_pct(r, THETA)
        oc = "HOLD_2HR"

    l1_usd = l1_pct * PER_CONTRACT
    l2_usd = l2_pct * PER_CONTRACT
    total_usd = l1_usd + l2_usd

    rows.append({
        'sym':       row['sym'],
        'date':      row['date'],
        'ret_2h':    r,
        'outcome':   oc,
        'leg1_pct':  round(l1_pct*100,1),
        'leg2_pct':  round(l2_pct*100,1),
        'leg1_usd':  round(l1_usd, 2),
        'leg2_usd':  round(l2_usd, 2),
        'total_usd': round(total_usd, 2),
    })

res = pd.DataFrame(rows)
res['date'] = pd.to_datetime(res['date'])
res['week'] = res['date'].dt.to_period('W')

print("=" * 65)
print(f"DOLLAR P&L — $2,500 account | $500/trade (2x $250 contracts)")
print(f"Weekly 5DTE ATM calls | L1=+0.75% L2=+1.50% Stop=-1%")
print("=" * 65)

total = res.total_usd.sum()
n     = len(res)
wr    = (res.total_usd > 0).mean() * 100
avg   = res.total_usd.mean()
best  = res.total_usd.max()
worst = res.total_usd.min()
cal_weeks = (res.date.max() - res.date.min()).days / 7

print(f"\n  Trades:         {n}")
print(f"  Win Rate:       {wr:.1f}%")
print(f"  Avg per trade:  USD {avg:>+.2f}")
print(f"  Best trade:     USD {best:>+.2f}")
print(f"  Worst trade:    USD {worst:>+.2f}")
print(f"  Total P&L:      USD {total:>+.2f}  over {cal_weeks:.0f} weeks")
print(f"  Avg per week:   USD {total/cal_weeks:>+.2f}/week")
print(f"  Return on acct: {total/ACCOUNT*100:>+.1f} pct  over 6 months")

print(f"\n{'='*65}")
print("PER OUTCOME — avg dollar P&L")
print(f"{'='*65}")
for oc in ['BOTH_TP','LEG1_TP','HOLD_2HR','STOP']:
    sub = res[res.outcome==oc]
    if len(sub) == 0: continue
    print(f"  {oc:<12}  N={len(sub):>3}  Avg=USD {sub.total_usd.mean():>+7.2f}  "
          f"Leg1=USD {sub.leg1_usd.mean():>+7.2f}  Leg2=USD {sub.leg2_usd.mean():>+7.2f}")

print(f"\n{'='*65}")
print("WEEKLY P&L BREAKDOWN")
print(f"{'='*65}")
weekly = res.groupby('week').agg(
    trades=('total_usd','count'),
    pnl=('total_usd','sum'),
    wins=('total_usd', lambda x: (x>0).sum())
).reset_index()
weekly['wr'] = weekly.wins / weekly.trades * 100
cumulative = 0
print(f"  {'Week':<25} {'Trades':>7}  {'WR':>6}  {'PnL (USD)':>10}  {'Cumul (USD)':>12}")
print(f"  {'-'*62}")
for _, w in weekly.iterrows():
    cumulative += w.pnl
    print(f"  {str(w.week):<25} {w.trades:>7.0f}  {w.wr:>5.0f}%  "
          f"USD {w.pnl:>+7.2f}  USD {cumulative:>+10.2f}")

print(f"\n{'='*65}")
print("WHAT THE MATH LOOKS LIKE PER SCENARIO")
print(f"{'='*65}")
print(f"  BOTH_TP  hit (+0.75% then +1.50%):  USD {calc_pnl_pct(LEG1,THETA*0.35)*PER_CONTRACT:>+.2f} + USD {calc_pnl_pct(LEG2,THETA*0.65)*PER_CONTRACT:>+.2f} = USD {calc_pnl_pct(LEG1,THETA*0.35)*PER_CONTRACT+calc_pnl_pct(LEG2,THETA*0.65)*PER_CONTRACT:>+.2f}")
print(f"  LEG1 only (+0.75%, leg2 goes flat): USD {calc_pnl_pct(LEG1,THETA*0.35)*PER_CONTRACT:>+.2f} + ~0 = USD {calc_pnl_pct(LEG1,THETA*0.35)*PER_CONTRACT:>+.2f}")
print(f"  STOP hit (-1.00%):                  USD {calc_pnl_pct(STOP,THETA*0.25)*PER_CONTRACT*2:>+.2f} total (both legs)")
print(f"  Flat ride to 2hr (0%):              ~USD {-THETA*PER_CONTRACT*2:>+.2f} total (theta only)")

print(f"\n  Risk/Reward per trade:")
avg_win  = res[res.total_usd>0].total_usd.mean()
avg_loss = res[res.total_usd<0].total_usd.mean()
print(f"  Avg winner:  USD {avg_win:>+.2f}")
print(f"  Avg loser:   USD {avg_loss:>+.2f}")
print(f"  R multiple:  {abs(avg_win/avg_loss):.2f}x  (winner/loser ratio)")
