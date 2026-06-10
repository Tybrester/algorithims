import random
random.seed(42)

TP_PCT, SL_PCT, TM_PCT = 0.35, -0.10, 0.08
TRADE = 300

# 2024 base: (tp, sl, tm) combined QQQ+SPY per month
monthly_exits = [
    (51,153,35),   # Jan  - weakest
    (103,130,65),  # Feb
    (96,126,82),   # Mar
    (123,156,99),  # Apr
    (114,145,85),  # May
    (109,137,86),  # Jun
    (114,168,100), # Jul
    (124,155,75),  # Aug
    (115,175,86),  # Sep
    (103,130,71),  # Oct
    (118,149,75),  # Nov
    (73,126,73),   # Dec
]

remaining = [
    ('May (rem)',  0.4,  4),
    ('Jun 2026',   1.0,  5),
    ('Jul 2026',   1.0,  6),
    ('Aug 2026',   1.0,  7),
    ('Sep 2026',   1.0,  8),
    ('Oct 2026',   1.0,  9),
    ('Nov 2026',   1.0, 10),
    ('Dec 2026',   0.7, 11),
]

def sim_month(frac, idx, tp_mult, sl_mult):
    tp_b, sl_b, tm_b = monthly_exits[idx]
    tp = round(tp_b * frac * tp_mult)
    sl = round(sl_b * frac * sl_mult)
    tm = round(tm_b * frac * ((tp_mult + sl_mult) / 2))
    return tp*TRADE*TP_PCT + sl*TRADE*SL_PCT + tm*TRADE*TM_PCT

# 10,000 simulations
# Each month independently varies:
#   tp_mult: 0.5 - 1.5 (winners can be more or fewer)
#   sl_mult: 0.6 - 1.6 (losers independently vary, can spike in bad months)
sims = []
for _ in range(10000):
    total = 0
    for label, frac, idx in remaining:
        tp_m = random.uniform(0.5, 1.5)
        sl_m = random.uniform(0.6, 1.6)
        total += sim_month(frac, idx, tp_m, sl_m)
    sims.append(total)

sims.sort()

# Base case
base = 0
print('May 25 - Dec 31, 2026  |  $300/trade  |  +35% TP / -10% SL')
print()
print('Base case (2024 analog, no variance):')
print('-'*40)
for label, frac, idx in remaining:
    pnl = sim_month(frac, idx, 1.0, 1.0)
    base += pnl
    print('  ' + label.ljust(14) + ' +$' + str(round(pnl)))
print('  ' + 'TOTAL'.ljust(14) + ' +$' + str(round(base)))

print()
print('Monte Carlo (10,000 simulations — TP/SL vary independently):')
print('-'*55)
print('  Bear case  (10th pct)  : +$' + str(round(sims[1000])))
print('  Cautious   (25th pct)  : +$' + str(round(sims[2500])))
print('  Expected   (50th pct)  : +$' + str(round(sims[5000])))
print('  Optimistic (75th pct)  : +$' + str(round(sims[7500])))
print('  Bull case  (90th pct)  : +$' + str(round(sims[9000])))
print()
print('  Probability > $70k  :  ' + str(round(sum(1 for s in sims if s > 70000) / 100)) + '%')
print('  Probability > $50k  :  ' + str(round(sum(1 for s in sims if s > 50000) / 100)) + '%')
print('  Probability > $40k  :  ' + str(round(sum(1 for s in sims if s > 40000) / 100)) + '%')
print('  Probability > $30k  :  ' + str(round(sum(1 for s in sims if s > 30000) / 100)) + '%')
print('  Probability > $20k  :  ' + str(round(sum(1 for s in sims if s > 20000) / 100)) + '%')
print('  Probability losing  :  ' + str(round(sum(1 for s in sims if s < 0) / 100)) + '%')
print()
print('  Min observed  : +$' + str(round(sims[0])))
print('  Max observed  : +$' + str(round(sims[-1])))
