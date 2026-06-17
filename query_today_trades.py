#!/usr/bin/env python3
"""Query today's trades for 22.5/23.5 bots, classify chop vs trend from entry_reason"""
import urllib.request, json, datetime

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

def query_today():
    # Get bot IDs for 22.5 / 23.5
    url = f"{SUPABASE_URL}/rest/v1/options_bots?select=id,name,bot_signal&or=(bot_signal.eq.boof22_5,bot_signal.eq.boof23_5)"
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req)
    bots = json.loads(resp.read().decode())
    
    if not bots:
        print("No boof22_5 or boof23_5 bots found.")
        return
    
    bot_ids = [str(b['id']) for b in bots]
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # Query trades for these bots today
    ids_param = ','.join(bot_ids)
    trades_url = f"{SUPABASE_URL}/rest/v1/options_trades?select=symbol,pnl,status,entry_reason,exit_reason,created_at,mode&bot_id=in.({ids_param})&created_at=gte.{today}T00:00:00Z&order=created_at.desc"
    
    req2 = urllib.request.Request(trades_url, headers=headers)
    resp2 = urllib.request.urlopen(req2)
    trades = json.loads(resp2.read().decode())
    
    print(f"=== Today's Trades ({today}) for .5 Bots ===\n")
    print(f"Total trades today: {len(trades)}\n")
    
    # Group by mode
    chop_trades = []
    trend_trades = []
    unknown_trades = []
    
    for t in trades:
        mode = t.get('mode')
        entry_reason = (t.get('entry_reason') or '').upper()
        
        if mode == 'chop' or 'CHOP' in entry_reason:
            chop_trades.append(t)
        elif mode == 'trend':
            trend_trades.append(t)
        else:
            unknown_trades.append(t)
    
    # Summary
    print(f"Chop trades:  {len(chop_trades)}")
    print(f"Trend trades: {len(trend_trades)}")
    print(f"Unknown:      {len(unknown_trades)}\n")
    
    # P&L breakdown
    chop_pnl = sum(t.get('pnl') or 0 for t in chop_trades)
    trend_pnl = sum(t.get('pnl') or 0 for t in trend_trades)
    total_pnl = chop_pnl + trend_pnl
    
    print(f"Chop P&L:  ${chop_pnl:+.2f}")
    print(f"Trend P&L: ${trend_pnl:+.2f}")
    print(f"Total P&L: ${total_pnl:+.2f}\n")
    
    # Detail chop trades
    if chop_trades:
        print("--- CHOP TRADES ---")
        for t in chop_trades:
            sym = t.get('symbol','?')
            pnl = t.get('pnl') or 0
            status = t.get('status','?')
            reason = (t.get('entry_reason') or '')[:40]
            created = t.get('created_at','')[11:19] if len(t.get('created_at','')) > 19 else '?'
            print(f"  {created} | {sym:6} | {status:8} | ${pnl:+7.2f} | {reason}")
        print()
    
    # Detail trend trades
    if trend_trades:
        print("--- TREND TRADES ---")
        for t in trend_trades:
            sym = t.get('symbol','?')
            pnl = t.get('pnl') or 0
            status = t.get('status','?')
            reason = (t.get('entry_reason') or '')[:40]
            created = t.get('created_at','')[11:19] if len(t.get('created_at','')) > 19 else '?'
            print(f"  {created} | {sym:6} | {status:8} | ${pnl:+7.2f} | {reason}")
        print()
    
    if unknown_trades:
        print(f"--- UNKNOWN ({len(unknown_trades)}) ---")
        for t in unknown_trades[:5]:
            sym = t.get('symbol','?')
            pnl = t.get('pnl') or 0
            status = t.get('status','?')
            reason = (t.get('entry_reason') or '')[:40]
            created = t.get('created_at','')[11:19] if len(t.get('created_at','')) > 19 else '?'
            print(f"  {created} | {sym:6} | {status:8} | ${pnl:+7.2f} | {reason}")
        print()

if __name__ == '__main__':
    query_today()
