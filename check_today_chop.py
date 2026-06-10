#!/usr/bin/env python3
"""Check today's chop vs trend trades for 22.5 and 23.5 bots"""

import urllib.request, json, datetime

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

def query():
    # Get all 22.5 and 23.5 bots with their trades
    url = f"{SUPABASE_URL}/rest/v1/options_bots?select=bot_signal,name,options_trades(status,pnl,created_at,exit_reason,entry_reason)"
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read().decode())
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    print(f"=== Today's Chop vs Trend Trades ({today}) ===\n")
    
    for bot in data:
        sig = bot.get('bot_signal', '')
        if '22_5' not in sig and '23_5' not in sig and '22.5' not in sig and '23.5' not in sig:
            continue
            
        name = bot.get('name', 'unnamed')
        trades = bot.get('options_trades', [])
        
        # Filter today's trades
        today_trades = [t for t in trades if t.get('created_at', '').startswith(today)]
        
        if not today_trades:
            continue
        
        print(f"Bot: {name} ({sig})")
        print(f"  Total today: {len(today_trades)} trades")
        
        # Classify by entry_reason
        chop_trades = []
        trend_trades = []
        
        for t in today_trades:
            reason = t.get('entry_reason', '') or ''
            if 'CHOP' in reason.upper():
                chop_trades.append(t)
            else:
                trend_trades.append(t)
        
        print(f"  Chop trades: {len(chop_trades)} | Trend trades: {len(trend_trades)}")
        
        # P&L breakdown
        chop_pnl = sum((t.get('pnl') or 0) for t in chop_trades)
        trend_pnl = sum((t.get('pnl') or 0) for t in trend_trades)
        total_pnl = chop_pnl + trend_pnl
        
        print(f"  Chop P&L: ${chop_pnl:+.2f} | Trend P&L: ${trend_pnl:+.2f} | Total: ${total_pnl:+.2f}")
        
        if chop_trades:
            print("  --- Chop Trades ---")
            for t in chop_trades:
                pnl = t.get('pnl') or 0
                status = t.get('status', '?')
                reason = t.get('entry_reason', '')[:50]
                created = t.get('created_at', '')[11:19] if len(t.get('created_at', '')) > 19 else '?'
                print(f"    {created} | {status:8} | ${pnl:+.2f} | {reason}")
        
        if trend_trades:
            print("  --- Trend Trades ---")
            for t in trend_trades:
                pnl = t.get('pnl') or 0
                status = t.get('status', '?')
                reason = t.get('entry_reason', '')[:50]
                created = t.get('created_at', '')[11:19] if len(t.get('created_at', '')) > 19 else '?'
                print(f"    {created} | {status:8} | ${pnl:+.2f} | {reason}")
        
        print()

if __name__ == '__main__':
    query()
