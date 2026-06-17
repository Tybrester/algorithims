"""
Options Scale-Out Backtest
Buy 2x ATM calls at breakout entry
Leg 1: sell at +0.75% underlying move
Leg 2: sell at +1.50% underlying move
Stop:  exit both at -1.00% underlying move (hit first)

ATM option P&L model (Black-Scholes approximations):
  Delta:  0.50  (ATM)
  Gamma:  assumed constant for small moves (simplification)
  Theta:  ~0.05-0.10% of premium per minute (2hr hold = ~120 mins)
  Vega:   ignored (IV assumed stable intraday)

Option price move approx = delta * underlying_move + 0.5 * gamma * underlying_move^2
For ATM 0-1DTE:
  delta = 0.50
  gamma = ~0.08 (high for 0DTE ATM)
  theta per minute = premium * 0.0007  (rough: 0DTE loses ~40% of value in last 2hrs)

We model two scenarios:
  A) Simple delta model: option_ret = delta * stock_ret  (conservative)
  B) Full greeks model:  option_ret with gamma boost and theta drag
"""
import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')
df['date'] = pd.to_datetime(df['date'])

# ── Option pricing approximation ──────────────────────────────────────────────
# For ATM 0DTE calls, rough empirical multipliers from market data:
# stock moves +1% -> ATM call moves ~+50-70% of premium (delta + gamma boost)
# stock moves -1% -> ATM call moves ~-45-55% of premium (delta - gamma drag)
# theta over 2hrs ~= 15-25% of morning premium (0DTE is brutal for theta)

DELTA        = 0.50
GAMMA        = 0.08     # per 1% move squared contribution
THETA_2HR    = 0.20     # 20% of premium lost to theta over 2hr hold (0DTE estimate)

LEG1_TRIG    = 0.0075   # +0.75% underlying
LEG2_TRIG    = 0.0150   # +1.50% underlying
STOP_TRIG    = -0.0100  # -1.00% underlying

def option_pnl_pct(stock_ret_pct, theta_drag=THETA_2HR):
    """
    Returns option P&L as % of premium paid.
    stock_ret_pct: stock move in % (e.g. +1.5 means +1.5%)
    """
    r = stock_ret_pct / 100.0
    opt_move = DELTA * r + 0.5 * GAMMA * r * r
    theta    = theta_drag  # fraction of premium lost to time
    # option pnl as fraction of premium
    pnl_frac = opt_move / (DELTA * 0.01) - theta   # normalize: 1% move = delta*1%
    # simpler: just use multiplier
    # at +1% stock move, ATM option gains ~delta*1% / (option_price/stock_price)
    # option price ATM ≈ 0.4% of stock price (rough for 0DTE, varies by IV)
    # so leverage ≈ 1 / 0.004 = 250x on stock move
    # but expressed as % of premium: gain% = stock_move_$ * delta / premium
    return pnl_frac * 100

def sim_trade(row):
    """
    Simulate 2-contract scale-out on a single trade.
    We don't have bar-by-bar data here, so we use the 2hr endpoint
    and known TP levels to reconstruct the path approximation.
    Returns P&L for each leg as % of premium.
    """
    r = row['ret_2h']  # final 2hr return in %

    # Determine what happened to each leg
    # We know from pl_analysis: what % of trades hit each threshold
    # Use the endpoint + threshold logic:
    # If r >= +1.5% -> both legs hit TP (best case)
    # If +0.75% <= r < +1.5% -> leg1 hit TP, leg2 closed at r
    # If -1.0% <= r < +0.75% -> neither TP hit, both closed at r (or stop)
    # If r <= -1.0% -> stop hit, both legs out at -1%

    if r <= -1.0:
        # Stop hit — both legs exit at -1% underlying
        stock_exit = -1.0
        leg1_pnl = option_pnl_pct(stock_exit, THETA_2HR * 0.3)  # stopped early, less theta
        leg2_pnl = option_pnl_pct(stock_exit, THETA_2HR * 0.3)
        outcome = "STOP"

    elif r >= 1.5:
        # Both legs hit TP
        # Leg1 exits at +0.75% (less theta, exits earlier)
        leg1_pnl = option_pnl_pct(0.75, THETA_2HR * 0.4)
        # Leg2 exits at +1.50%
        leg2_pnl = option_pnl_pct(1.50, THETA_2HR * 0.7)
        outcome = "BOTH_TP"

    elif r >= 0.75:
        # Only leg1 hit TP, leg2 held to 2hr close
        leg1_pnl = option_pnl_pct(0.75, THETA_2HR * 0.4)
        leg2_pnl = option_pnl_pct(r,    THETA_2HR)
        outcome = "LEG1_TP"

    else:
        # Neither TP hit — both ride to 2hr close
        leg1_pnl = option_pnl_pct(r, THETA_2HR)
        leg2_pnl = option_pnl_pct(r, THETA_2HR)
        outcome = "HOLD_2HR"

    total_pnl = (leg1_pnl + leg2_pnl) / 2  # avg of both contracts
    return pd.Series({
        'leg1_pnl': round(leg1_pnl, 2),
        'leg2_pnl': round(leg2_pnl, 2),
        'avg_pnl':  round(total_pnl, 2),
        'outcome':  outcome
    })

results = df.apply(sim_trade, axis=1)
df2 = pd.concat([df, results], axis=1)

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 70)
print("OPTIONS SCALE-OUT BACKTEST — 2x ATM Calls")
print("Leg1: sell at +0.75% stock | Leg2: sell at +1.50% stock | Stop: -1.00%")
print("=" * 70)

print(f"\nTotal trades: {len(df2)}")
print(f"\nOutcome breakdown:")
for oc in ['BOTH_TP','LEG1_TP','HOLD_2HR','STOP']:
    sub = df2[df2.outcome==oc]
    print(f"  {oc:<12} {len(sub):>3} trades ({len(sub)/len(df2)*100:>5.1f}%)")

print(f"\n{'='*70}")
print("P&L AS % OF PREMIUM PAID (per contract)")
print(f"{'='*70}")
print(f"  Avg Leg1 P&L:   {df2.leg1_pnl.mean():>+7.1f}%  of premium")
print(f"  Avg Leg2 P&L:   {df2.leg2_pnl.mean():>+7.1f}%  of premium")
print(f"  Avg Combined:   {df2.avg_pnl.mean():>+7.1f}%  of premium")
print(f"  Median:         {df2.avg_pnl.median():>+7.1f}%  of premium")
print(f"  Win Rate:       {(df2.avg_pnl>0).mean()*100:>7.1f}%")
wins = df2[df2.avg_pnl>0].avg_pnl.sum()
loss = df2[df2.avg_pnl<0].avg_pnl.abs().sum()
print(f"  Profit Factor:  {wins/loss:>7.3f}" if loss else "  Profit Factor:  999")
print(f"  Total P&L:      {df2.avg_pnl.sum():>+7.1f}%  cumulative")

print(f"\n{'='*70}")
print("BY OUTCOME — avg option P&L")
print(f"{'='*70}")
for oc in ['BOTH_TP','LEG1_TP','HOLD_2HR','STOP']:
    sub = df2[df2.outcome==oc]
    if len(sub) == 0: continue
    print(f"  {oc:<12}  N={len(sub):>3}  Avg={sub.avg_pnl.mean():>+7.1f}%  "
          f"Leg1={sub.leg1_pnl.mean():>+7.1f}%  Leg2={sub.leg2_pnl.mean():>+7.1f}%")

print(f"\n{'='*70}")
print("UNDERLYING vs OPTIONS P&L COMPARISON")
print(f"{'='*70}")
print(f"  {'Metric':<25} {'Stock (2hr hold)':>18}  {'Options (scale-out)':>20}")
print(f"  {'-'*65}")
stock_wr = (df['ret_2h']>0).mean()*100
stock_ev = df['ret_2h'].mean()
sw = df[df.ret_2h>0].ret_2h.sum(); sl = df[df.ret_2h<0].ret_2h.abs().sum()
stock_pf = sw/sl if sl else 999
opt_wr   = (df2.avg_pnl>0).mean()*100
opt_ev   = df2.avg_pnl.mean()
opt_pf   = wins/loss if loss else 999
print(f"  {'Win Rate':<25} {stock_wr:>17.1f}%  {opt_wr:>19.1f}%")
print(f"  {'Avg EV':<25} {stock_ev:>+17.3f}%  {opt_ev:>+19.1f}%  of premium")
print(f"  {'Profit Factor':<25} {stock_pf:>18.3f}  {opt_pf:>20.3f}")

print(f"\n{'='*70}")
print("NOTE: Option P&L expressed as % of premium paid per contract")
print("  e.g. +40% means a $2.00 option becomes $2.80")
print("  Theta drag assumed: 20% of premium lost over 2hr hold (0DTE estimate)")
print("  Delta=0.50, Gamma=0.08 (ATM 0DTE approximation)")
print("  Actual results will vary with IV, exact strike, expiry")
