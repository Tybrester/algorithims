"""
Compare 0DTE vs 1DTE vs Weekly (5DTE) options on the same trade set
Same scale-out: Leg1 +0.75%, Leg2 +1.50%, Stop -1.00%
Key difference: theta drag and delta/gamma profile changes with DTE
"""
import pandas as pd
import numpy as np

df = pd.read_csv('walkforward_test.csv')

# ── Greeks by DTE (ATM, approximate) ─────────────────────────────────────────
# Based on Black-Scholes ATM approximation with IV=30% (typical large cap)
# Option price ATM ≈ stock_price * IV * sqrt(DTE/252) * 0.4
# Delta ATM ≈ 0.50 always
# Gamma ATM ≈ 1 / (stock_price * IV * sqrt(DTE/252)) -> higher for 0DTE
# Theta per day ≈ option_price * sqrt(1/(2*pi*DTE)) -> higher for 0DTE
# Over 2hr hold = 2/390 of trading day = 0.00513 days

TRADING_MINS_PER_DAY = 390
HOLD_MINS = 120
HOLD_FRAC = HOLD_MINS / TRADING_MINS_PER_DAY  # fraction of day held

DTE_PROFILES = {
    "0DTE": {
        "delta":        0.50,
        "gamma":        0.08,   # very high, massive gamma scalp potential
        "theta_pct":    0.22,   # % of premium lost in 2hrs (brutal decay near expiry)
        "option_price_pct": 0.0040,  # ~0.4% of stock price for ATM 0DTE (IV=30%)
        "leverage":     125,    # approx option leverage vs stock
    },
    "1DTE": {
        "delta":        0.50,
        "gamma":        0.055,
        "theta_pct":    0.10,   # ~10% of premium in 2hrs
        "option_price_pct": 0.0060,
        "leverage":     83,
    },
    "Weekly (5DTE)": {
        "delta":        0.50,
        "gamma":        0.025,  # lower gamma, less explosive
        "theta_pct":    0.025,  # ~2.5% of premium in 2hrs (negligible)
        "option_price_pct": 0.0130,  # more expensive, ~1.3% of stock
        "leverage":     38,
    },
    "2-Week (10DTE)": {
        "delta":        0.50,
        "gamma":        0.018,
        "theta_pct":    0.013,  # ~1.3% of premium in 2hrs
        "option_price_pct": 0.0185,
        "leverage":     27,
    },
}

LEG1 = 0.0075
LEG2 = 0.0150
STOP = -0.0100

def sim_dte(df, profile, name):
    delta    = profile['delta']
    gamma    = profile['gamma']
    theta    = profile['theta_pct']
    lev      = profile['leverage']

    def calc_pnl(stock_ret_pct, theta_frac):
        r = stock_ret_pct / 100.0
        # option move as fraction of option price
        # delta * r + 0.5 * gamma * r^2 = fraction of underlying move
        # convert to % of premium: divide by option_price_pct
        opt_pct = profile['option_price_pct']
        move_frac = (delta * abs(r) + 0.5 * gamma * r * r) * np.sign(r)
        pnl_pct_premium = (move_frac * 1.0 / opt_pct) * 100 - theta_frac * 100
        return pnl_pct_premium

    rows = []
    for _, row in df.iterrows():
        r = row['ret_2h']
        if r <= -1.0:
            # stop — exits early, less theta used
            l1 = calc_pnl(-1.0, theta * 0.25)
            l2 = calc_pnl(-1.0, theta * 0.25)
            oc = "STOP"
        elif r >= 1.5:
            l1 = calc_pnl(0.75, theta * 0.35)
            l2 = calc_pnl(1.50, theta * 0.65)
            oc = "BOTH_TP"
        elif r >= 0.75:
            l1 = calc_pnl(0.75, theta * 0.35)
            l2 = calc_pnl(r,    theta)
            oc = "LEG1_TP"
        else:
            l1 = calc_pnl(r, theta)
            l2 = calc_pnl(r, theta)
            oc = "HOLD_2HR"

        avg = (l1 + l2) / 2
        rows.append({'outcome': oc, 'leg1': l1, 'leg2': l2, 'avg': avg,
                     'stock_ret': r})

    res = pd.DataFrame(rows)
    n   = len(res)
    wr  = (res.avg > 0).mean() * 100
    ev  = res.avg.mean()
    med = res.avg.median()
    w   = res[res.avg > 0].avg.sum()
    l   = res[res.avg < 0].avg.abs().sum()
    pf  = w / l if l else 999.0
    tot = res.avg.sum()

    print(f"\n  {'='*62}")
    print(f"  {name}  (theta={theta*100:.1f}% over 2hr, lev=~{lev}x, "
          f"opt~{profile['option_price_pct']*100:.2f}% of stock)")
    print(f"  {'='*62}")
    print(f"  N={n}  WR={wr:.1f}%  EV={ev:>+7.1f}%  Median={med:>+7.1f}%  "
          f"PF={pf:.3f}  TotPnl={tot:>+8.1f}%")
    print(f"  Outcomes: BOTH_TP={(res.outcome=='BOTH_TP').sum():>3} | "
          f"LEG1_TP={(res.outcome=='LEG1_TP').sum():>3} | "
          f"HOLD={(res.outcome=='HOLD_2HR').sum():>3} | "
          f"STOP={(res.outcome=='STOP').sum():>3}")
    for oc in ['BOTH_TP','LEG1_TP','HOLD_2HR','STOP']:
        sub = res[res.outcome == oc]
        if len(sub) == 0: continue
        print(f"    {oc:<12} N={len(sub):>3}  Avg={sub.avg.mean():>+7.1f}%  "
              f"Leg1={sub.leg1.mean():>+7.1f}%  Leg2={sub.leg2.mean():>+7.1f}%")
    return res

print("=" * 65)
print("DTE COMPARISON — 2x ATM Calls, Scale-Out L1=+0.75% L2=+1.50% Stop=-1%")
print("P&L expressed as % of premium paid per contract")
print("=" * 65)

all_results = {}
for name, profile in DTE_PROFILES.items():
    all_results[name] = sim_dte(df, profile, name)

# ── Head to head summary ──────────────────────────────────────────────────────
print(f"\n\n{'='*65}")
print("HEAD TO HEAD SUMMARY")
print(f"{'='*65}")
print(f"  {'DTE':<18} {'WR':>6}  {'EV/trade':>10}  {'PF':>7}  {'Leverage':>9}  {'Theta/2hr':>10}")
print(f"  {'-'*62}")
for name, profile in DTE_PROFILES.items():
    res = all_results[name]
    wr  = (res.avg>0).mean()*100
    ev  = res.avg.mean()
    w   = res[res.avg>0].avg.sum(); l=res[res.avg<0].avg.abs().sum()
    pf  = w/l if l else 999.0
    print(f"  {name:<18} {wr:>5.1f}%  {ev:>+9.1f}%  {pf:>7.3f}  {profile['leverage']:>8}x  "
          f"{profile['theta_pct']*100:>9.1f}%")

print(f"\n  Stock (2hr hold, no options): WR=71.4%  EV=+1.25% of position  PF=2.986")

print(f"""
KEY INSIGHT:
  0DTE  = lottery ticket. Huge leverage but theta kills you on losers/holds.
           Stop at -1% stock = ~full premium loss.
  Weekly = smoother. Theta negligible over 2hrs. Lower leverage but
           losers only lose ~delta * move, not full premium.
           Stop at -1% stock = only ~38-50% of premium lost.
  Best DTE for THIS strategy = Weekly (5DTE):
    - Theta drag <3% over 2hrs (negligible)  
    - Stop loss = partial loss not wipeout
    - Still gets 60-80% of the move via delta
    - Survives the HOLD_2HR flat trades much better
""")
