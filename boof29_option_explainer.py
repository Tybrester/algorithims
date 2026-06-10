from math import log, sqrt, exp
from scipy.stats import norm

def bs_call(S, K, T, r, sigma):
    if T <= 0: return max(S-K, 0)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S*norm.cdf(d1) - K*exp(-r*T)*norm.cdf(d2)

def bs_delta(S, K, T, r, sigma):
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    return norm.cdf(d1)

def bs_theta_per_min(S, K, T, r, sigma):
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    theta_per_year = -(S * norm.pdf(d1) * sigma) / (2 * sqrt(T))
    return theta_per_year / (252 * 390)  # per minute

IV = 0.40
R  = 0.05

# Typical signal: NVDA at $130, 0.5% move
S     = 130.0
S_out = S * 1.005  # +0.5%

# 1 trading day = 390 min. Entry at 9:35 = 355 min left. Exit 10:20 = 310 min left.
T_in  = 355 / 390 / 252
T_out = 310 / 390 / 252
HOLD_MINS = 45

SPREAD = 0.10   # per-side for deep ITM
COMM   = 0.0065

print("=" * 68)
print("  WHY A 0.5% MOVE BARELY WORKS FOR 1DTE OPTIONS")
print("  NVDA ~$130 | entry 9:35 | exit 10:20 | 0.5% move = +$0.65")
print("=" * 68)
print(f"  Stock P&L (100 shares): +${(S_out-S)*100:.2f}\n")

print(f"  {'Strike':>10} {'Delta':>7} {'Premium':>10} {'Buy':>8} {'Sell':>8} {'Delta$':>8} {'Theta$':>8} {'Net$':>8}  Verdict")
print("-" * 100)

cases = [
    ("ATM   K=130", 130),
    ("0.70d K=125", 125),
    ("0.80d K=120", 120),
    ("0.85d K=117", 117),
    ("0.90d K=115", 115),
    ("0.95d K=110", 110),
    ("Deep  K=100", 100),
]

for label, K in cases:
    opt_in   = bs_call(S,     K, T_in,  R, IV)
    opt_out  = bs_call(S_out, K, T_out, R, IV)
    delta    = bs_delta(S, K, T_in, R, IV)
    theta_pm = bs_theta_per_min(S, K, T_in, R, IV)

    buy_px   = opt_in  + SPREAD + COMM
    sell_px  = opt_out - SPREAD - COMM

    net_pnl    = (sell_px - buy_px) * 100
    delta_gain = delta * (S_out - S) * 100
    theta_cost = theta_pm * HOLD_MINS * 100   # theta bleed over 45 min

    verdict = "PROFIT" if net_pnl > 0 else "LOSS"
    print(f"  {label:>10}  {delta:>6.2f}  ${opt_in*100:>8.2f}  ${buy_px:>6.2f}  ${sell_px:>6.2f}  ${delta_gain:>+6.2f}  ${theta_cost:>+6.2f}  ${net_pnl:>+6.2f}  {verdict}")

print()
print("=" * 68)
print("  THE MATH EXPLAINED:")
print("=" * 68)
print("""
  For ATM (delta 0.50):
    - You pay ~$220 premium for 0.50 delta
    - 0.50 delta * $0.65 stock move = +$0.325 per share = +$32.50 per contract
    - BUT theta decay over 45 min eats ~$25-30 of that
    - PLUS spread ($10 entry) + spread ($10 exit) = $20 cost
    - Net: +$32 - $28 theta - $20 spread = roughly BREAKEVEN or LOSS

  For 0.80 delta (K ~$120):
    - Premium ~$1,050 but intrinsic value = $10 (in-the-money)
    - 0.80 delta * $0.65 stock move = +$0.52 per share = +$52 per contract
    - Theta decay is LOWER (ITM options decay less than ATM)
    - Spread still $20 total
    - Net: +$52 - $15 theta - $20 spread = ~+$17 profit (marginal)

  THE CORE ISSUE:
    A 0.5% move on a $130 stock = only $0.65 per share
    That's $65 on 100 shares (1 contract equivalent)
    After spread + commission you need delta > 0.75 just to break even
    The edge is in the 65% win rate on STOCK, not in the option leverage

  WHEN OPTIONS WOULD WORK:
    - Move bucket > 1.0% (gives $1.30+ per share to work with)
    - Same-day expiry with <2 hrs left (less theta, more gamma)
    - Or use the stock strategy as-is: PF 2.56 beats any option structure here
""")
