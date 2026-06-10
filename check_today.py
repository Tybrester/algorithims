import urllib.request, json, datetime

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

url = f"{SUPABASE_URL}/rest/v1/options_bots?select=bot_signal,name,options_trades(status,pnl,created_at,exit_reason)&or=(bot_signal.eq.boof22_5,bot_signal.eq.boof23_5)"
headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
req = urllib.request.Request(url, headers=headers)
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())

print(f"Found {len(data)} bots with boof22_5 or boof23_5 signal")
for bot in data:
    print(f"\nBot: {bot.get('name')} ({bot.get('bot_signal')})")
    trades = bot.get('options_trades', [])
    print(f"  Total trades in DB: {len(trades)}")
    if trades:
        print(f"  Latest trade: {trades[0].get('created_at')}")
        print(f"  Status: {trades[0].get('status')}, P&L: {trades[0].get('pnl')}")
