"""
Analyze Saved Boof 24 Futures Results (from 2026-06-06 Databento data)
"""
import pandas as pd
import numpy as np

FUTURES_FILES = {
    'ES':   ('futures_ES_6mo_20260606.csv',   12.50, 'IMPULSE'),
    'MES':  ('futures_MES_6mo_20260606.csv',  1.25,  'IMPULSE'),
    'NQ':   ('futures_NQ_6mo_20260606.csv',   5.00,  'BREAKOUT'),
    'MNQ':  ('futures_MNQ_6mo_20260606.csv',  0.50,  'BREAKOUT'),
}

def analyze_results(symbol, filename, tick_value, trade_type):
    """Analyze saved trade results"""
    try:
        df = pd.read_csv(filename)
    except:
        return None
    
    total_trades = len(df)
    wins = len(df[df['pnl_dollar'] > 0])
    losses = len(df[df['pnl_dollar'] < 0])
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    total_pnl = df['pnl_dollar'].sum()
    avg_pnl = df['pnl_dollar'].mean()
    
    # Calculate R-multiples (assume 1R = avg loss size)
    losses_df = df[df['pnl_dollar'] < 0]
    avg_loss = abs(losses_df['pnl_dollar'].mean()) if len(losses_df) > 0 else 100
    
    df['r_mult'] = df['pnl_dollar'] / avg_loss
    total_r = df['r_mult'].sum()
    avg_r = df['r_mult'].mean()
    
    # Profit factor
    gross_profit = df[df['pnl_dollar'] > 0]['pnl_dollar'].sum()
    gross_loss = abs(df[df['pnl_dollar'] < 0]['pnl_dollar'].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else 0
    
    return {
        'symbol': symbol,
        'type': trade_type,
        'tick_value': tick_value,
        'trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_pnl': total_pnl,
        'avg_r': avg_r,
        'total_r': total_r,
        'profit_factor': pf
    }

print("=" * 85)
print("BOOF 24 FUTURES - ANALYSIS OF SAVED RESULTS (Databento 6mo data)")
print("=" * 85)
print(f"{'Contract':<8} {'Type':<10} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WR%':<7} {'Avg $':<10} {'Total $':<12} {'R/T':<8} {'PF':<6}")
print("-" * 85)

all_results = []
for sym, (file, tick_val, ttype) in FUTURES_FILES.items():
    result = analyze_results(sym, file, tick_val, ttype)
    if result:
        all_results.append(result)
        status = "✅" if result['avg_r'] > 0.15 else "✓" if result['avg_r'] > 0.05 else "⚠️" if result['avg_r'] > 0 else "✗"
        print(f"{result['symbol']:<8} {result['type']:<10} {result['trades']:<8} {result['wins']:<6} {result['losses']:<6} "
              f"{result['win_rate']:<7.1f} ${result['avg_pnl']:<9.2f} ${result['total_pnl']:<11.2f} "
              f"{result['avg_r']:<8.3f} {result['profit_factor']:<6.2f} {status}")

# Breakdown by type
breakout = [r for r in all_results if r['type'] == 'BREAKOUT']
impulse = [r for r in all_results if r['type'] == 'IMPULSE']

print("\n" + "=" * 85)
print("BREAKDOWN BY TYPE")
print("=" * 85)

if breakout:
    bt = sum(b['trades'] for b in breakout)
    bw = sum(b['wins'] for b in breakout)
    bl = sum(b['losses'] for b in breakout)
    bwr = bw / bt * 100 if bt > 0 else 0
    btpnl = sum(b['total_pnl'] for b in breakout)
    btr = sum(b['total_r'] for b in breakout)
    bavgr = btr / bt if bt > 0 else 0
    print(f"\n📈 BREAKOUT (NQ, MNQ):")
    print(f"    Trades: {bt} | Wins: {bw} | Losses: {bl} | WR: {bwr:.1f}%")
    print(f"    Total P&L: ${btpnl:+.2f} | Total R: {btr:+.2f} | R/T: {bavgr:.3f}")
    print(f"    Verdict: {'✅ Edge confirmed' if bavgr > 0.10 else '⚠️ Weak edge' if bavgr > 0 else '🔴 No edge'}")

if impulse:
    it = sum(i['trades'] for i in impulse)
    iw = sum(i['wins'] for i in impulse)
    il = sum(i['losses'] for i in impulse)
    iwr = iw / it * 100 if it > 0 else 0
    itpnl = sum(i['total_pnl'] for i in impulse)
    itr = sum(i['total_r'] for i in impulse)
    iavgr = itr / it if it > 0 else 0
    print(f"\n⚡ IMPULSE (ES, MES):")
    print(f"    Trades: {it} | Wins: {iw} | Losses: {il} | WR: {iwr:.1f}%")
    print(f"    Total P&L: ${itpnl:+.2f} | Total R: {itr:+.2f} | R/T: {iavgr:.3f}")
    print(f"    Verdict: {'✅ Edge confirmed' if iavgr > 0.10 else '⚠️ Weak edge' if iavgr > 0 else '🔴 No edge'}")

# Grand total
if all_results:
    gt = sum(r['trades'] for r in all_results)
    gw = sum(r['wins'] for r in all_results)
    gl = sum(r['losses'] for r in all_results)
    gwr = gw / gt * 100 if gt > 0 else 0
    gtpnl = sum(r['total_pnl'] for r in all_results)
    gtr = sum(r['total_r'] for r in all_results)
    gavgr = gtr / gt if gt > 0 else 0
    
    print("\n" + "=" * 85)
    print("GRAND TOTAL - ALL FUTURES")
    print("=" * 85)
    print(f"\nTotal Trades:  {gt}")
    print(f"Win Rate:      {gwr:.1f}%")
    print(f"Total P&L:     ${gtpnl:+.2f}")
    print(f"Total R:       {gtr:+.2f}")
    print(f"R per Trade:   {gavgr:.3f}")
    print(f"\n{'=' * 85}")
    if gavgr > 0.15:
        print("✅✅ STRONG EDGE - Boof 24 Futures ready for deployment")
    elif gavgr > 0.10:
        print("✅ EDGE CONFIRMED - Boof 24 Futures viable with caution")
    elif gavgr > 0:
        print("⚠️  MARGINAL EDGE - Needs more testing/optimization")
    else:
        print("🔴 NO EDGE - Do not deploy")
    print(f"{'=' * 85}")

print("\n💡 These results are from the Boof 24 backtest on 6 months of Databento futures data")
