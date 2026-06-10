#!/usr/bin/env python3
"""
Analyze today's trades per bot
Run: python analyze_daily_trades.py
"""

import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

# Supabase credentials
SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

try:
    from supabase import create_client
except ImportError:
    print("Installing supabase client...")
    os.system("pip install supabase -q")
    from supabase import create_client

# Initialize Supabase
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get today's date in UTC (adjust for your timezone)
today = datetime.now().strftime('%Y-%m-%d')
today_start = f"{today}T00:00:00"
today_end = f"{today}T23:59:59"

print(f"\n{'='*70}")
print(f"DAILY TRADE ANALYSIS - {today}")
print(f"{'='*70}\n")

# Fetch all bots with their trades
bots_result = sb.table('options_bots').select('*, options_trades(*)').execute()
bots = bots_result.data or []

if not bots:
    print("No bots found.")
    exit()

# Analyze each bot
for bot in bots:
    bot_name = bot.get('name', 'Unknown')
    bot_id = bot.get('id', '')[:8]
    all_trades = bot.get('options_trades', [])
    
    # Filter today's trades
    today_trades = []
    for t in all_trades:
        trade_time = t.get('created_at', '')
        if today_start <= trade_time <= today_end:
            today_trades.append(t)
    
    if not today_trades:
        continue
    
    # Calculate stats
    closed_trades = [t for t in today_trades if t.get('status') == 'closed']
    open_trades = [t for t in today_trades if t.get('status') == 'open']
    
    wins = [t for t in closed_trades if (t.get('pnl') or 0) > 0]
    losses = [t for t in closed_trades if (t.get('pnl') or 0) <= 0]
    
    total_pnl = sum(t.get('pnl', 0) or 0 for t in closed_trades)
    win_count = len(wins)
    loss_count = len(losses)
    total_closed = len(closed_trades)
    
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0
    
    # Print bot header
    print(f"\n{'─'*70}")
    print(f"📊 {bot_name} (ID: {bot_id})")
    print(f"   Signal: {bot.get('bot_signal', 'N/A')} | Interval: {bot.get('bot_interval', 'N/A')}")
    print(f"{'─'*70}")
    
    # Summary stats
    print(f"\n   📈 SUMMARY:")
    print(f"      Total Trades Today: {len(today_trades)} ({len(open_trades)} open, {total_closed} closed)")
    print(f"      Win Rate: {win_rate:.1f}% ({win_count}W / {loss_count}L)")
    print(f"      Total P&L: ${total_pnl:,.2f}")
    print(f"      Avg per Trade: ${total_pnl/total_closed:,.2f}" if total_closed > 0 else "      Avg per Trade: $0.00")
    
    # Closed trades detail
    if closed_trades:
        print(f"\n   💰 CLOSED TRADES:")
        for t in sorted(closed_trades, key=lambda x: x.get('created_at', '')):
            symbol = t.get('symbol', 'N/A')
            pnl = t.get('pnl', 0) or 0
            contracts = t.get('contracts', 1)
            entry = t.get('premium_per_contract', 0)
            exit = t.get('exit_price', 0)
            reason = t.get('exit_reason', 'unknown')
            time = t.get('created_at', '').split('T')[1][:8] if 'T' in t.get('created_at', '') else ''
            
            emoji = "🟢" if pnl > 0 else "🔴"
            print(f"      {emoji} {time} {symbol:>6} x{contracts}  ${pnl:>+8.2f}  ({reason})")
    
    # Open trades
    if open_trades:
        print(f"\n   ⏳ OPEN TRADES:")
        for t in open_trades:
            symbol = t.get('symbol', 'N/A')
            contracts = t.get('contracts', 1)
            entry = t.get('premium_per_contract', 0)
            time = t.get('created_at', '').split('T')[1][:8] if 'T' in t.get('created_at', '') else ''
            print(f"      🟡 {time} {symbol:>6} x{contracts}  Entry: ${entry:.2f}")
    
    # Symbol breakdown
    symbol_pnl = defaultdict(float)
    for t in closed_trades:
        sym = t.get('symbol', 'Unknown')
        symbol_pnl[sym] += (t.get('pnl', 0) or 0)
    
    if symbol_pnl:
        print(f"\n   📊 BY SYMBOL:")
        for sym, pnl in sorted(symbol_pnl.items(), key=lambda x: abs(x[1]), reverse=True):
            color = "🟢" if pnl > 0 else "🔴"
            print(f"      {color} {sym:>6}: ${pnl:>+,.2f}")

print(f"\n{'='*70}")
print("Analysis complete!")
print(f"{'='*70}\n")
