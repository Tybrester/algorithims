"""
Boof 24 Futures Deep Analysis - Sessions, Regimes, Risk Metrics
Using saved 6mo Databento data
"""
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

FUTURES_FILES = {
    'ES':   ('futures_ES_6mo_20260606.csv',   12.50, 'IMPULSE'),
    'MES':  ('futures_MES_6mo_20260606.csv',  1.25,  'IMPULSE'),
    'NQ':   ('futures_NQ_6mo_20260606.csv',   5.00,  'BREAKOUT'),
    'MNQ':  ('futures_MNQ_6mo_20260606.csv',  0.50,  'BREAKOUT'),
}

def load_and_enhance(symbol, filename, tick_value, trade_type):
    """Load data and add session/regime analysis"""
    df = pd.read_csv(filename)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour
    df['date'] = df['timestamp'].dt.date
    df['month'] = df['timestamp'].dt.to_period('M')
    df['weekday'] = df['timestamp'].dt.day_name()
    
    # Session classification (futures hours: 18:00-17:00 ET next day)
    def get_session(hour):
        if 18 <= hour or hour < 5:  # 6pm-5am (overnight + early)
            return 'Overnight'
        elif 5 <= hour < 11:        # 5am-11am (market open)
            return 'Open'
        elif 11 <= hour < 14:       # 11am-2pm (midday)
            return 'Midday'
        else:                       # 2pm-5pm (afternoon)
            return 'Afternoon'
    
    df['session'] = df['hour'].apply(get_session)
    
    # Calculate rolling metrics for regime detection
    df['pnl_5d_sum'] = df.groupby('date')['pnl_dollar'].transform(lambda x: x.rolling(5, min_periods=1).sum())
    
    # Regime classification based on recent performance
    df['recent_pnl'] = df['pnl_dollar'].rolling(20, min_periods=5).sum()
    df['recent_wr'] = df['hit'].rolling(20, min_periods=5).mean()
    
    def regime_class(row):
        if pd.isna(row['recent_pnl']):
            return 'Unknown'
        if row['recent_pnl'] > 500 and row['recent_wr'] > 0.55:
            return 'Hot'
        elif row['recent_pnl'] < -200 and row['recent_wr'] < 0.45:
            return 'Cold'
        else:
            return 'Normal'
    
    df['regime'] = df.apply(regime_class, axis=1)
    
    # Volatility proxy (based on trade frequency and P&L variance)
    df['volatility'] = df['pnl_dollar'].rolling(10, min_periods=5).std()
    df['vol_regime'] = df['volatility'].apply(lambda x: 'High' if x > 200 else 'Low' if pd.notna(x) else 'Unknown')
    
    return df

def analyze_consecutive_losses(df):
    """Find longest losing streaks"""
    losses = (df['pnl_dollar'] < 0).astype(int)
    streaks = []
    current_streak = 0
    
    for is_loss in losses:
        if is_loss:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        streaks.append(current_streak)
    
    return max(streaks) if streaks else 0, streaks

def calculate_drawdown(df):
    """Calculate max drawdown"""
    df = df.sort_values('timestamp')
    cumulative = df['pnl_dollar'].cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    return drawdown.min(), cumulative.iloc[-1]

# ═══════════════════════════════════════════════════════════════════════════════
# LOAD ALL DATA
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("BOOF 24 FUTURES - DEEP ANALYSIS")
print("=" * 90)

all_data = {}
for sym, (file, tick, ttype) in FUTURES_FILES.items():
    print(f"\nLoading {sym}...", end=' ')
    df = load_and_enhance(sym, file, tick, ttype)
    all_data[sym] = df
    print(f"{len(df)} trades loaded")

# Combine all
combined = pd.concat(all_data.values(), ignore_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("SESSION PERFORMANCE")
print("=" * 90)

sessions = ['Overnight', 'Open', 'Midday', 'Afternoon']
print(f"\n{'Session':<12} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WR%':<7} {'Avg $':<10} {'Total $':<12} {'R/T':<8}")
print("-" * 90)

session_results = []
for session in sessions:
    session_df = combined[combined['session'] == session]
    if len(session_df) == 0:
        continue
    
    trades = len(session_df)
    wins = len(session_df[session_df['pnl_dollar'] > 0])
    losses = len(session_df[session_df['pnl_dollar'] < 0])
    wr = wins / trades * 100
    avg_pnl = session_df['pnl_dollar'].mean()
    total_pnl = session_df['pnl_dollar'].sum()
    
    # R calculation
    losses_df = session_df[session_df['pnl_dollar'] < 0]
    avg_loss = abs(losses_df['pnl_dollar'].mean()) if len(losses_df) > 0 else 100
    r_mults = session_df['pnl_dollar'] / avg_loss
    avg_r = r_mults.mean()
    
    session_results.append({
        'session': session, 'trades': trades, 'wr': wr, 
        'avg_pnl': avg_pnl, 'total_pnl': total_pnl, 'avg_r': avg_r
    })
    
    status = "[STRONG]" if avg_r > 0.15 else "[OK]" if avg_r > 0.05 else "[WEAK]"
    print(f"{session:<12} {trades:<8} {wins:<6} {losses:<6} {wr:<7.1f} ${avg_pnl:<9.2f} ${total_pnl:<11.2f} {avg_r:<8.3f} {status}")

# ═══════════════════════════════════════════════════════════════════════════════
# REGIME ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("MARKET REGIME PERFORMANCE")
print("=" * 90)

regimes = ['Hot', 'Normal', 'Cold']
print(f"\n{'Regime':<12} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WR%':<7} {'Avg $':<10} {'Total $':<12} {'R/T':<8}")
print("-" * 90)

for regime in regimes:
    regime_df = combined[combined['regime'] == regime]
    if len(regime_df) == 0:
        continue
    
    trades = len(regime_df)
    wins = len(regime_df[regime_df['pnl_dollar'] > 0])
    losses = len(regime_df[regime_df['pnl_dollar'] < 0])
    wr = wins / trades * 100
    avg_pnl = regime_df['pnl_dollar'].mean()
    total_pnl = regime_df['pnl_dollar'].sum()
    
    losses_df = regime_df[regime_df['pnl_dollar'] < 0]
    avg_loss = abs(losses_df['pnl_dollar'].mean()) if len(losses_df) > 0 else 100
    r_mults = regime_df['pnl_dollar'] / avg_loss
    avg_r = r_mults.mean()
    
    status = "[HOT]" if regime == 'Hot' else "[COLD]" if regime == 'Cold' else "[---]"
    print(f"{regime:<12} {trades:<8} {wins:<6} {losses:<6} {wr:<7.1f} ${avg_pnl:<9.2f} ${total_pnl:<11.2f} {avg_r:<8.3f} {status}")

# Volatility Regime
print(f"\n{'Vol Regime':<12} {'Trades':<8} {'Wins':<6} {'Loss':<6} {'WR%':<7} {'Avg $':<10} {'Total $':<12} {'R/T':<8}")
print("-" * 90)

for vol in ['High', 'Low']:
    vol_df = combined[combined['vol_regime'] == vol]
    if len(vol_df) == 0:
        continue
    
    trades = len(vol_df)
    wins = len(vol_df[vol_df['pnl_dollar'] > 0])
    losses = len(vol_df[vol_df['pnl_dollar'] < 0])
    wr = wins / trades * 100
    avg_pnl = vol_df['pnl_dollar'].mean()
    total_pnl = vol_df['pnl_dollar'].sum()
    
    losses_df = vol_df[vol_df['pnl_dollar'] < 0]
    avg_loss = abs(losses_df['pnl_dollar'].mean()) if len(losses_df) > 0 else 100
    r_mults = vol_df['pnl_dollar'] / avg_loss
    avg_r = r_mults.mean()
    
    status = "[HIGH]" if vol == 'High' else "[LOW]"
    print(f"{vol:<12} {trades:<8} {wins:<6} {losses:<6} {wr:<7.1f} ${avg_pnl:<9.2f} ${total_pnl:<11.2f} {avg_r:<8.3f} {status}")

# ═══════════════════════════════════════════════════════════════════════════════
# CONSECUTIVE LOSS ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("CONSECUTIVE LOSS ANALYSIS (RISK METRICS)")
print("=" * 90)

print(f"\n{'Symbol':<8} {'Total Trades':<14} {'Longest Streak':<16} {'Avg Streak':<12} {'3+ Streaks':<12}")
print("-" * 90)

max_streak_overall = 0
worst_symbol = ''

for sym, df in all_data.items():
    max_streak, all_streaks = analyze_consecutive_losses(df)
    avg_streak = np.mean(all_streaks) if all_streaks else 0
    streaks_3plus = len([s for s in all_streaks if s >= 3])
    
    if max_streak > max_streak_overall:
        max_streak_overall = max_streak
        worst_symbol = sym
    
    print(f"{sym:<8} {len(df):<14} {max_streak:<16} {avg_streak:<12.1f} {streaks_3plus:<12}")

print(f"\n🔴 Worst Losing Streak: {max_streak_overall} consecutive losses on {worst_symbol}")

# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY PERFORMANCE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("MONTHLY PERFORMANCE")
print("=" * 90)

monthly = combined.groupby('month').agg({
    'pnl_dollar': ['count', 'sum', 'mean'],
    'hit': 'mean'
}).reset_index()

monthly.columns = ['month', 'trades', 'total_pnl', 'avg_pnl', 'wr']
monthly['wr'] = monthly['wr'] * 100

print(f"\n{'Month':<10} {'Trades':<8} {'Win Rate':<10} {'Avg $':<10} {'Total $':<12} {'Status':<10}")
print("-" * 90)

worst_month_pnl = 0
worst_month_name = ''
best_month_pnl = -999999
best_month_name = ''

for _, row in monthly.iterrows():
    status = "[STRONG]" if row['total_pnl'] > 10000 else "[OK]" if row['total_pnl'] > 0 else "[BAD]"
    print(f"{str(row['month']):<10} {int(row['trades']):<8} {row['wr']:<10.1f} ${row['avg_pnl']:<9.2f} ${row['total_pnl']:<11.2f} {status}")
    
    if row['total_pnl'] < worst_month_pnl:
        worst_month_pnl = row['total_pnl']
        worst_month_name = str(row['month'])
    if row['total_pnl'] > best_month_pnl:
        best_month_pnl = row['total_pnl']
        best_month_name = str(row['month'])

print(f"\n[WORST MONTH] {worst_month_name} (${worst_month_pnl:,.2f})")
print(f"[BEST MONTH] {best_month_name} (${best_month_pnl:,.2f})")

# ═══════════════════════════════════════════════════════════════════════════════
# DRAWDOWN ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("DRAWDOWN ANALYSIS")
print("=" * 90)

print(f"\n{'Symbol':<8} {'Max Drawdown':<16} {'Final P&L':<16} {'Return/DD':<12}")
print("-" * 90)

worst_dd = 0
worst_dd_sym = ''

for sym, df in all_data.items():
    dd, final_pnl = calculate_drawdown(df)
    ret_dd = abs(final_pnl / dd) if dd != 0 else 0
    
    if dd < worst_dd:
        worst_dd = dd
        worst_dd_sym = sym
    
    print(f"{sym:<8} ${dd:<15,.2f} ${final_pnl:<15,.2f} {ret_dd:<12.2f}")

# Combined drawdown
combined_sorted = combined.sort_values('timestamp')
combined_dd, combined_final = calculate_drawdown(combined_sorted)

print("-" * 90)
print(f"{'COMBINED':<8} ${combined_dd:<15,.2f} ${combined_final:<15,.2f} {abs(combined_final/combined_dd):<12.2f}")

print(f"\n[MAX DD] ${worst_dd:,.2f} on {worst_dd_sym}")
print(f"[PORTFOLIO MAX DD] ${combined_dd:,.2f}")

# ═══════════════════════════════════════════════════════════════════════════════
# WEEKDAY ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("WEEKDAY PERFORMANCE")
("=" * 90)

days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
print(f"\n{'Day':<12} {'Trades':<8} {'Win Rate':<10} {'Avg $':<10} {'Total $':<12}")
print("-" * 70)

for day in days:
    day_df = combined[combined['weekday'] == day]
    if len(day_df) == 0:
        continue
    trades = len(day_df)
    wr = day_df['hit'].mean() * 100
    avg_pnl = day_df['pnl_dollar'].mean()
    total_pnl = day_df['pnl_dollar'].sum()
    
    status = "[STRONG]" if total_pnl > 2000 else "[OK]" if total_pnl > 0 else "[WEAK]"
    print(f"{day:<12} {trades:<8} {wr:<10.1f} ${avg_pnl:<9.2f} ${total_pnl:<11.2f} {status}")

print("\n" + "=" * 90)
print("SUMMARY INSIGHTS")
print("=" * 90)

# Best session
best_session = max(session_results, key=lambda x: x['avg_r'])
print(f"\n[BEST SESSION] {best_session['session']} ({best_session['avg_r']:.3f} R/T)")

# Key stats
print(f"\n[KEY STATISTICS]")
print(f"   • Longest Losing Streak: {max_streak_overall} trades ({worst_symbol})")
print(f"   • Worst Month: {worst_month_name} (${worst_month_pnl:,.2f})")
print(f"   • Best Month: {best_month_name} (${best_month_pnl:,.2f})")
print(f"   • Max Drawdown: ${combined_dd:,.2f}")
print(f"   • Return/Max DD Ratio: {abs(combined_final/combined_dd):.2f}x")

# Recommendations
print(f"\n[RECOMMENDATIONS]")
if best_session['session'] == 'Open':
    print(f"   • Focus trading on Market Open session (strongest edge)")
elif best_session['session'] == 'Overnight':
    print(f"   • Overnight session shows edge - consider 24hr trading")
else:
    print(f"   • {best_session['session']} is optimal trading window")

print(f"   • Reduce size after {max_streak_overall-1} consecutive losses")
print(f"   • Skip trading in 'Cold' regime (edge degrades)")
print(f"   • Max drawdown risk: ${combined_dd:,.0f} (size accordingly)")
