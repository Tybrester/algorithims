"""
Daily PnL Tracker - Compare Live Results to Model
Run this after market close to see how you did vs expectations
"""
import os
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client

# Supabase setup
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://ccqfyquftgseuzkvonhc.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNjcWZ5cXVmdGdzZXV6a3ZvbmhjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDI3NjYwNDEsImV4cCI6MjA1ODM0MjA0MX0._PcdD2c0p7nTtVO8dE3bjj6t2Y8wEKXWmPm2WljX5Qo')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Model expectations (from slippage analysis)
MODEL = {
    'expected_daily_pnl': 719,      # After slippage
    'expected_trades': 40,         # 22 + 23 combined
    'expected_win_rate': 0.625,    # 62.5%
    'slippage_buffer': 0.33,       # 33% slippage haircut
}

def get_today_trades():
    """Fetch today's trades from database"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Get all closed trades for today
    result = supabase.table('options_trades').select('*').eq('status', 'closed').gte('closed_at', today).execute()
    
    trades = result.data if result.data else []
    
    # Filter for Boof 22/23 signals
    boof_trades = [t for t in trades if t.get('signal_type') in ['boof22', 'boof23'] or 
                   (t.get('bot_id') and 'boof' in str(t.get('bot_id', '')).lower())]
    
    return boof_trades

def analyze_day(trades):
    """Calculate daily stats"""
    if not trades:
        return {
            'total_pnl': 0,
            'trade_count': 0,
            'winners': 0,
            'losers': 0,
            'win_rate': 0,
            'avg_winner': 0,
            'avg_loser': 0,
            'max_winner': 0,
            'max_loser': 0,
        }
    
    pnls = [float(t.get('pnl', 0) or 0) for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    
    return {
        'total_pnl': sum(pnls),
        'trade_count': len(pnls),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': len(winners) / len(pnls) if pnls else 0,
        'avg_winner': sum(winners) / len(winners) if winners else 0,
        'avg_loser': sum(losers) / len(losers) if losers else 0,
        'max_winner': max(winners) if winners else 0,
        'max_loser': min(losers) if losers else 0,
    }

def print_report(actual):
    """Print daily report comparing to model"""
    expected = MODEL['expected_daily_pnl']
    variance = actual['total_pnl'] - expected
    variance_pct = (variance / expected * 100) if expected else 0
    
    print("\n" + "="*70)
    print(f"DAILY PnL REPORT - {datetime.now().strftime('%Y-%m-%d')}")
    print("="*70)
    
    print(f"\n📊 ACTUAL RESULTS:")
    print(f"  Total P&L:        ${actual['total_pnl']:+.2f}")
    print(f"  Trades:           {actual['trade_count']} ({actual['winners']}W / {actual['losers']}L)")
    print(f"  Win Rate:         {actual['win_rate']*100:.1f}%")
    print(f"  Avg Winner:       ${actual['avg_winner']:+.2f}")
    print(f"  Avg Loser:        ${actual['avg_loser']:+.2f}")
    print(f"  Max Winner:       ${actual['max_winner']:+.2f}")
    print(f"  Max Loser:        ${actual['max_loser']:+.2f}")
    
    print(f"\n🎯 vs MODEL (Expected):")
    print(f"  Expected P&L:     ${expected:+.2f}")
    print(f"  Variance:         ${variance:+.2f} ({variance_pct:+.1f}%)")
    
    # Status
    if variance >= 0:
        print(f"\n✅ GREEN DAY - Met or beat expectations")
    elif variance > -200:
        print(f"\n⚠️  SLIGHT MISS - Within normal variance")
    else:
        print(f"\n🔴 RED FLAG - Significant underperformance")
    
    # Check if within expected range
    lower_bound = expected * 0.4  # Bad day threshold
    upper_bound = expected * 1.5  # Great day
    
    if actual['total_pnl'] >= lower_bound:
        print(f"\n✅ Within expected range (${lower_bound:.0f} - ${upper_bound:.0f})")
    else:
        print(f"\n⚠️  Below expected range (floor: ${lower_bound:.0f})")
    
    # Trade count check
    if actual['trade_count'] < MODEL['expected_trades'] * 0.5:
        print(f"⚠️  Low trade count - possible missed signals")
    
    print("="*70)

def main():
    print("Fetching today's Boof 22/23 trades...")
    trades = get_today_trades()
    
    if not trades:
        print("\n⚠️  No trades found for today yet")
        print("   (Or check that trades have been closed and have PnL recorded)")
        return
    
    actual = analyze_day(trades)
    print_report(actual)
    
    # Save to history file
    today = datetime.now().strftime('%Y-%m-%d')
    log_line = f"{today},{actual['total_pnl']:.2f},{actual['trade_count']},{actual['win_rate']*100:.1f}\n"
    
    with open('daily_pnl_history.csv', 'a') as f:
        if os.path.getsize('daily_pnl_history.csv') == 0:
            f.write("date,pnl,trades,win_rate\n")
        f.write(log_line)
    
    print(f"\n💾 Saved to daily_pnl_history.csv")

if __name__ == "__main__":
    main()
