#!/usr/bin/env python3
"""Check today's chop trades for 22.5 and 23.5 bots"""

import urllib.request, json, datetime

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

def query():
    url = f"{SUPABASE_URL}/rest/v1/options_bots?select=bot_signal,name,options_trades(status,pnl,created_at,exit_reason)&or=(bot_signal.eq.boof22_5,bot_signal.eq.boof23_5)"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    }
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read().decode())
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    print(f"=== Today's Trades ({today}) for 22.5 / 23.5 Bots ===\n")
    
    for bot in data:
        signal = bot.get('bot_signal', 'unknown')
        name = bot.get('name', 'unnamed')
        trades = bot.get('options_trades', [])
        
        if not trades:
            continue
            
        print(f"Bot: {name} ({signal})")
        
        today_trades = []
        for t in trades:
            created = t.get('created_at', '')
            if created and today in created:
                today_trades.append(t)
        
        if not today_trades:
            print("  No trades today\n")
            continue
        
        # Note: The database may not track 'mode' (chop vs trend) per trade
        # unless that field was added. We can infer from exit reasons if available.
        for t in today_trades:
            status = t.get('status', 'unknown')
            pnl = t.get('pnl', 0) or 0
            exit_reason = t.get('exit_reason', 'N/A')
            created = t.get('created_at', '')
            print(f"  {created[11:19] if len(created) > 19 else '??'} | {status:8} | P&L: ${pnl:+.2f} | Exit: {exit_reason}")
        
        wins = sum(1 for t in today_trades if (t.get('pnl') or 0) > 0)
        losses = len(today_trades) - wins
        total_pnl = sum((t.get('pnl') or 0) for t in today_trades)
        
        print(f"  Total: {len(today_trades)} trades | {wins}W/{losses}L | P&L: ${total_pnl:+.2f}")
        print()

if __name__ == '__main__':
    query()
