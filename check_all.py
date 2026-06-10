import urllib.request, json, datetime

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

# Get ALL bots
url = f"{SUPABASE_URL}/rest/v1/options_bots?select=bot_signal,name,options_trades(status,pnl,created_at,exit_reason)"
req = urllib.request.Request(url, headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())

today = datetime.datetime.now().strftime('%Y-%m-%d')
print(f"=== Date: {today} ===\n")
print(f"Total bots in DB: {len(data)}\n")

# Show all bot signals
signals = {}
for bot in data:
    sig = bot.get('bot_signal', 'unknown')
    signals[sig] = signals.get(sig, 0) + 1

print("Bot signals in database:")
for sig, count in sorted(signals.items()):
    print(f"  {sig}: {count}")

print("\n" + "="*60)

# Look for ANY bot that might be 22.5 or 23.5 (check various naming)
found_any = False
for bot in data:
    sig = bot.get('bot_signal', '')
    name = bot.get('name', '')
    if '22.5' in sig or '22_5' in sig or '23.5' in sig or '23_5' in sig or '22.5' in name or '23.5' in name:
        found_any = True
        print(f"\nFOUND: {name} (signal: {sig})")
        trades = bot.get('options_trades', [])
        
        # Filter today's trades
        today_trades = [t for t in trades if t.get('created_at', '').startswith(today)]
        print(f"  Total trades: {len(trades)} | Today's trades: {len(today_trades)}")
        
        if today_trades:
            wins = sum(1 for t in today_trades if (t.get('pnl') or 0) > 0)
            losses = len(today_trades) - wins
            total_pnl = sum((t.get('pnl') or 0) for t in today_trades)
            print(f"  Today's P&L: ${total_pnl:+.2f} | Wins: {wins} | Losses: {losses}")
            for t in today_trades:
                print(f"    {t.get('created_at','?')[11:19]} | {t.get('status','?')} | ${t.get('pnl',0):+.2f} | {t.get('exit_reason','N/A')}")
        else:
            print("  No trades today")

if not found_any:
    print("\nNo 22.5 or 23.5 bots found in database.")
    print("Looking for bots with 'boof' in name or signal...")
    for bot in data:
        sig = bot.get('bot_signal', '')
        name = bot.get('name', '')
        if 'boof' in sig.lower() or 'boof' in name.lower():
            print(f"  Found: {name} ({sig})")
