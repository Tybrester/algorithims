"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  BOOF 24 VALIDATION FRAMEWORK                                                 ║
║  Step 1: Backtest → EV per setup                                              ║
║  Step 2: Sim trade → behavior data collection                                 ║
║  Step 3: Drawdown + streak analysis                                           ║
║  Step 4: Walk-forward (time-based validation)                                 ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

FUTURES_CONFIG = {
    'ES':  {'file': 'futures_ES_6mo_20260606.csv',   'tick_value': 12.50, 'type': 'IMPULSE',  'name': 'E-mini S&P'},
    'MES': {'file': 'futures_MES_6mo_20260606.csv',  'tick_value': 1.25,  'type': 'IMPULSE',  'name': 'Micro E-mini S&P'},
    'NQ':  {'file': 'futures_NQ_6mo_20260606.csv',   'tick_value': 5.00,  'type': 'BREAKOUT', 'name': 'E-mini Nasdaq'},
    'MNQ': {'file': 'futures_MNQ_6mo_20260606.csv',  'tick_value': 0.50,  'type': 'BREAKOUT', 'name': 'Micro E-mini Nasdaq'},
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: BACKTEST → EV PER SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_ev_metrics(trades_list):
    """Calculate EV and distribution statistics"""
    if not trades_list:
        return {}
    
    pnls = np.array([t['pnl_r'] for t in trades_list])
    
    # Basic EV
    ev = np.mean(pnls)
    
    # Win/loss distribution
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    
    win_rate = len(wins) / len(pnls) * 100
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0
    
    # EV components
    win_ev = (win_rate/100) * avg_win
    loss_ev = ((100-win_rate)/100) * avg_loss
    
    # Variance and std
    variance = np.var(pnls)
    std = np.std(pnls)
    
    # Percentiles
    p10 = np.percentile(pnls, 10)
    p25 = np.percentile(pnls, 25)
    p50 = np.percentile(pnls, 50)
    p75 = np.percentile(pnls, 75)
    p90 = np.percentile(pnls, 90)
    
    # Tail ratios
    tail_ratio = abs(p90 / p10) if p10 != 0 else 0
    
    return {
        'ev': ev,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'win_ev': win_ev,
        'loss_ev': loss_ev,
        'variance': variance,
        'std': std,
        'sharpe': ev / std if std > 0 else 0,
        'p10': p10, 'p25': p25, 'p50': p50, 'p75': p75, 'p90': p90,
        'tail_ratio': tail_ratio,
        'total_trades': len(pnls),
        'win_count': len(wins),
        'loss_count': len(losses)
    }

def step1_backtest_ev(symbol, config):
    """Step 1: Calculate EV per setup type"""
    print(f"\n{symbol}: Backtest EV Analysis", end=' ')
    
    df = pd.read_csv(config['file'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate R value
    losses = df[df['pnl_dollar'] < 0]['pnl_pts'].abs()
    r_value = losses.mean() if len(losses) > 0 else 10
    df['pnl_r'] = df['pnl_pts'] / r_value
    
    # Build trades list
    trades = []
    for _, row in df.iterrows():
        trades.append({
            'timestamp': row['timestamp'],
            'symbol': symbol,
            'type': config['type'],
            'direction': row['direction'],
            'pnl_r': row['pnl_r'],
            'pnl_dollar': row['pnl_dollar'],
            'hit': row['hit'],
            'bars': row['bars'] if 'bars' in row else 10
        })
    
    # EV by setup type
    all_ev = calculate_ev_metrics(trades)
    
    # EV by direction
    long_trades = [t for t in trades if t['direction'] == 'long']
    short_trades = [t for t in trades if t['direction'] == 'short']
    
    long_ev = calculate_ev_metrics(long_trades)
    short_ev = calculate_ev_metrics(short_trades)
    
    # EV by exit type (if hit field exists)
    tp_trades = [t for t in trades if 'TP' in str(t.get('hit', ''))]
    sl_trades = [t for t in trades if 'SL' in str(t.get('hit', ''))]
    time_trades = [t for t in trades if 'time' in str(t.get('hit', '')).lower()]
    
    print(f"Done. EV={all_ev['ev']:.3f}R, WinRate={all_ev['win_rate']:.1f}%")
    
    return {
        'symbol': symbol,
        'type': config['type'],
        'r_value': r_value,
        'tick_value': config['tick_value'],
        'all_trades': trades,
        'ev_summary': all_ev,
        'long_ev': long_ev,
        'short_ev': short_ev,
        'tp_exits': calculate_ev_metrics(tp_trades),
        'sl_exits': calculate_ev_metrics(sl_trades),
        'time_exits': calculate_ev_metrics(time_trades)
    }

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: SIM TRADE → COLLECT BEHAVIOR DATA
# ═══════════════════════════════════════════════════════════════════════════════

def step2_sim_behavior(results_dict):
    """Step 2: Simulate real trading behavior with slippage, missed entries"""
    print("\n" + "="*80)
    print("STEP 2: SIM TRADE - Behavior Data Collection")
    print("="*80)
    
    behavior_data = {}
    
    for symbol, data in results_dict.items():
        trades = data['all_trades']
        if not trades:
            continue
        
        print(f"\n{symbol}: Simulating real behavior...", end=' ')
        
        # Simulate realistic execution issues
        sim_results = []
        
        for trade in trades:
            original_pnl = trade['pnl_r']
            
            # 1. Slippage simulation (±0.1R random)
            slippage = np.random.normal(0, 0.05)
            
            # 2. Missed entry simulation (5% chance of missing good signal)
            missed = np.random.random() < 0.05 and original_pnl > 0.5
            
            # 3. Worse fill on fast moves (correlated with |pnl|)
            fast_move_penalty = abs(original_pnl) * 0.02 if abs(original_pnl) > 1.5 else 0
            
            if missed:
                sim_pnl = 0  # Missed trade
            else:
                sim_pnl = original_pnl - slippage - fast_move_penalty
            
            sim_results.append({
                'original_pnl': original_pnl,
                'sim_pnl': sim_pnl,
                'missed': missed,
                'slippage': slippage,
                'type': trade['type'],
                'direction': trade['direction']
            })
        
        # Calculate behavior impact
        original_ev = np.mean([s['original_pnl'] for s in sim_results])
        sim_ev = np.mean([s['sim_pnl'] for s in sim_results])
        
        missed_count = sum(1 for s in sim_results if s['missed'])
        total_slippage = sum(s['slippage'] for s in sim_results)
        
        behavior_data[symbol] = {
            'original_ev': original_ev,
            'sim_ev': sim_ev,
            'ev_decay': original_ev - sim_ev,
            'missed_rate': missed_count / len(sim_results) * 100,
            'total_slippage_r': total_slippage,
            'sim_trades': sim_results
        }
        
        print(f"Done. EV decay: {original_ev - sim_ev:.3f}R")
    
    return behavior_data

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: DRAWDOWN + STREAK ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def step3_drawdown_streak(results_dict):
    """Step 3: Comprehensive drawdown and streak analysis"""
    print("\n" + "="*80)
    print("STEP 3: DRAWDOWN + STREAK ANALYSIS")
    print("="*80)
    
    analysis = {}
    
    for symbol, data in results_dict.items():
        trades = data['all_trades']
        if not trades:
            continue
        
        print(f"\n{symbol}: Analyzing...", end=' ')
        
        pnls = [t['pnl_r'] for t in trades]
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - running_max
        
        # Drawdown statistics
        max_dd = abs(min(drawdowns))
        avg_dd = abs(np.mean([d for d in drawdowns if d < 0]))
        dd_std = np.std([d for d in drawdowns if d < 0])
        
        # Find drawdown durations
        in_dd = False
        dd_start = 0
        dd_durations = []
        for i, dd in enumerate(drawdowns):
            if dd < -0.01 and not in_dd:  # Threshold for meaningful DD
                in_dd = True
                dd_start = i
            elif dd > -0.01 and in_dd:
                dd_durations.append(i - dd_start)
                in_dd = False
        
        avg_dd_duration = np.mean(dd_durations) if dd_durations else 0
        max_dd_duration = max(dd_durations) if dd_durations else 0
        
        # Streak analysis
        win_streaks = []
        loss_streaks = []
        current_win = 0
        current_loss = 0
        
        for pnl in pnls:
            if pnl > 0:
                current_win += 1
                if current_loss > 0:
                    loss_streaks.append(current_loss)
                    current_loss = 0
            else:
                current_loss += 1
                if current_win > 0:
                    win_streaks.append(current_win)
                    current_win = 0
        
        # Handle ending streaks
        if current_win > 0:
            win_streaks.append(current_win)
        if current_loss > 0:
            loss_streaks.append(current_loss)
        
        # Recovery analysis
        recovery_times = []
        peak_equity = 0
        peak_idx = 0
        
        for i, eq in enumerate(cumulative):
            if eq > peak_equity:
                if peak_equity > 0:  # Was in drawdown
                    recovery_times.append(i - peak_idx)
                peak_equity = eq
                peak_idx = i
        
        analysis[symbol] = {
            'max_dd_r': max_dd,
            'avg_dd_r': avg_dd,
            'dd_volatility': dd_std,
            'avg_dd_duration': avg_dd_duration,
            'max_dd_duration': max_dd_duration,
            
            'max_win_streak': max(win_streaks) if win_streaks else 0,
            'avg_win_streak': np.mean(win_streaks) if win_streaks else 0,
            'max_loss_streak': max(loss_streaks) if loss_streaks else 0,
            'avg_loss_streak': np.mean(loss_streaks) if loss_streaks else 0,
            
            'recovery_time_avg': np.mean(recovery_times) if recovery_times else 0,
            'recovery_time_max': max(recovery_times) if recovery_times else 0,
            
            # Prop firm risk metrics
            'prob_10r_dd': sum(1 for d in drawdowns if abs(d) > 10) / len(drawdowns) * 100,
            'prob_20r_dd': sum(1 for d in drawdowns if abs(d) > 20) / len(drawdowns) * 100
        }
        
        print(f"Done. Max DD: {max_dd:.1f}R, Max Loss Streak: {analysis[symbol]['max_loss_streak']}")
    
    return analysis

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: WALK-FORWARD (TIME-BASED VALIDATION)
# ═══════════════════════════════════════════════════════════════════════════════

def step4_walkforward(results_dict):
    """Step 4: Walk-forward analysis by time periods"""
    print("\n" + "="*80)
    print("STEP 4: WALK-FORWARD VALIDATION")
    print("="*80)
    
    walkforward_results = {}
    
    for symbol, data in results_dict.items():
        trades = data['all_trades']
        if not trades:
            continue
        
        print(f"\n{symbol}: Walk-forward analysis...", end=' ')
        
        # Group by week
        weekly_results = defaultdict(list)
        monthly_results = defaultdict(list)
        
        for trade in trades:
            ts = trade['timestamp']
            week_key = ts.strftime('%Y-W%U')
            month_key = ts.strftime('%Y-%m')
            
            weekly_results[week_key].append(trade['pnl_r'])
            monthly_results[month_key].append(trade['pnl_r'])
        
        # Calculate weekly EV
        weekly_ev = {}
        for week, pnls in sorted(weekly_results.items()):
            weekly_ev[week] = {
                'ev': np.mean(pnls),
                'trades': len(pnls),
                'total_r': sum(pnls),
                'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) * 100
            }
        
        # Calculate monthly EV
        monthly_ev = {}
        for month, pnls in sorted(monthly_results.items()):
            monthly_ev[month] = {
                'ev': np.mean(pnls),
                'trades': len(pnls),
                'total_r': sum(pnls),
                'win_rate': sum(1 for p in pnls if p > 0) / len(pnls) * 100
            }
        
        # Consistency metrics
        weekly_evs = [w['ev'] for w in weekly_ev.values()]
        monthly_evs = [m['ev'] for m in monthly_ev.values()]
        
        # Count profitable periods
        profitable_weeks = sum(1 for ev in weekly_evs if ev > 0)
        profitable_months = sum(1 for ev in monthly_evs if ev > 0)
        
        walkforward_results[symbol] = {
            'weekly': weekly_ev,
            'monthly': monthly_ev,
            
            'total_weeks': len(weekly_ev),
            'profitable_weeks': profitable_weeks,
            'week_consistency': profitable_weeks / len(weekly_ev) * 100 if weekly_ev else 0,
            'weekly_ev_std': np.std(weekly_evs),
            'weekly_ev_range': max(weekly_evs) - min(weekly_evs) if weekly_evs else 0,
            
            'total_months': len(monthly_ev),
            'profitable_months': profitable_months,
            'month_consistency': profitable_months / len(monthly_ev) * 100 if monthly_ev else 0,
            'monthly_ev_std': np.std(monthly_evs),
            'monthly_ev_range': max(monthly_evs) - min(monthly_evs) if monthly_evs else 0
        }
        
        print(f"Done. {profitable_months}/{len(monthly_ev)} profitable months")
    
    return walkforward_results

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("BOOF 24 VALIDATION FRAMEWORK")
print("4-Step Prop Firm Readiness Check")
print("=" * 90)

# STEP 1: Backtest EV
print("\n" + "="*90)
print("STEP 1: BACKTEST → EV PER SETUP")
print("="*90)

results_dict = {}
for symbol, config in FUTURES_CONFIG.items():
    result = step1_backtest_ev(symbol, config)
    if result:
        results_dict[symbol] = result

# Print EV Summary
print("\n" + "="*90)
print("EV PER SETUP SUMMARY")
print("="*90)

print(f"\n{'Symbol':<8} {'Type':<10} {'EV/R':<10} {'Win%':<8} {'AvgWin':<10} {'AvgLoss':<10} {'TailRatio':<10}")
print("-" * 90)

for symbol, data in results_dict.items():
    ev = data['ev_summary']
    print(f"{symbol:<8} {data['type']:<10} {ev['ev']:<10.3f} {ev['win_rate']:<8.1f} "
          f"{ev['avg_win']:<10.2f} {ev['avg_loss']:<10.2f} {ev['tail_ratio']:<10.2f}")

# Print Directional breakdown
print("\n" + "="*90)
print("EV BY DIRECTION")
print("="*90)

print(f"\n{'Symbol':<8} {'Long EV':<12} {'Short EV':<12} {'Bias':<15}")
print("-" * 55)

for symbol, data in results_dict.items():
    long_ev = data['long_ev'].get('ev', 0) if data['long_ev'] else 0
    short_ev = data['short_ev'].get('ev', 0) if data['short_ev'] else 0
    bias = "LONG" if long_ev > short_ev else "SHORT" if short_ev > long_ev else "NEUTRAL"
    print(f"{symbol:<8} {long_ev:<12.3f} {short_ev:<12.3f} {bias:<15}")

# STEP 2: Sim Trade Behavior
behavior_data = step2_sim_behavior(results_dict)

# Print Behavior Impact
print("\n" + "="*90)
print("STEP 2: SIM TRADE → BEHAVIOR IMPACT")
print("="*90)

print(f"\n{'Symbol':<8} {'Backtest EV':<15} {'Sim EV':<15} {'EV Decay':<15} {'Missed%':<10}")
print("-" * 80)

for symbol, data in behavior_data.items():
    print(f"{symbol:<8} {data['original_ev']:<15.3f} {data['sim_ev']:<15.3f} "
          f"{data['ev_decay']:<15.3f} {data['missed_rate']:<10.1f}%")

# STEP 3: Drawdown + Streak
streak_analysis = step3_drawdown_streak(results_dict)

# Print Drawdown Analysis
print("\n" + "="*90)
print("STEP 3: DRAWDOWN + STREAK ANALYSIS")
print("="*90)

print(f"\n{'Symbol':<8} {'MaxDD(R)':<12} {'AvgDD(R)':<12} {'MaxLossStreak':<15} {'AvgLossStreak':<15} {'Prob10RDD':<12}")
print("-" * 95)

for symbol, data in streak_analysis.items():
    print(f"{symbol:<8} {data['max_dd_r']:<12.1f} {data['avg_dd_r']:<12.2f} "
          f"{data['max_loss_streak']:<15} {data['avg_loss_streak']:<15.1f} {data['prob_10r_dd']:<12.1f}%")

# STEP 4: Walk-Forward
walkforward = step4_walkforward(results_dict)

# Print Walk-Forward
print("\n" + "="*90)
print("STEP 4: WALK-FORWARD VALIDATION")
print("="*90)

print(f"\n{'Symbol':<8} {'Weeks':<10} {'ProfWeeks':<12} {'WeekConsist':<14} {'Months':<10} {'ProfMonths':<12} {'MonthConsist':<14}")
print("-" * 100)

for symbol, data in walkforward.items():
    print(f"{symbol:<8} {data['total_weeks']:<10} {data['profitable_weeks']:<12} "
          f"{data['week_consistency']:<14.1f}% {data['total_months']:<10} "
          f"{data['profitable_months']:<12} {data['month_consistency']:<14.1f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# FINAL PROP FIRM READINESS SCORE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "="*90)
print("PROP FIRM READINESS SCORE")
print("="*90)

for symbol in results_dict.keys():
    ev_data = results_dict[symbol]['ev_summary']
    streak_data = streak_analysis[symbol]
    wf_data = walkforward[symbol]
    behavior = behavior_data[symbol]
    
    # Scoring (0-100)
    ev_score = min(max(ev_data['ev'] * 100, 0), 30)  # Max 30 pts
    consistency_score = min(wf_data['month_consistency'] / 100 * 25, 25)  # Max 25 pts
    dd_score = max(0, 20 - streak_data['max_dd_r'] / 2)  # Max 20 pts
    streak_score = max(0, 15 - streak_data['max_loss_streak'] / 2)  # Max 15 pts
    behavior_score = max(0, 10 - behavior['ev_decay'] * 10)  # Max 10 pts
    
    total_score = ev_score + consistency_score + dd_score + streak_score + behavior_score
    
    print(f"\n{symbol}:")
    print(f"  EV Score:        {ev_score:.1f}/30  (EV={ev_data['ev']:.3f}R)")
    print(f"  Consistency:     {consistency_score:.1f}/25  ({wf_data['month_consistency']:.0f}% profitable months)")
    print(f"  Drawdown:        {dd_score:.1f}/20  (Max DD={streak_data['max_dd_r']:.1f}R)")
    print(f"  Streak Control:  {streak_score:.1f}/15  (Max streak={streak_data['max_loss_streak']})")
    print(f"  Behavior:        {behavior_score:.1f}/10  (Decay={behavior['ev_decay']:.3f}R)")
    print(f"  {'='*40}")
    print(f"  TOTAL:           {total_score:.1f}/100")
    
    if total_score >= 70:
        print(f"  [READY FOR PROP] Excellent risk profile")
    elif total_score >= 50:
        print(f"  [CONDITIONAL] Viable with size limits")
    elif total_score >= 30:
        print(f"  [CAUTION] Higher risk - test small")
    else:
        print(f"  [NOT READY] Significant issues detected")

print("\n" + "="*90)
