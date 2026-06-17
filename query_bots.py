import urllib.request, json

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"

# Get all bot signals
url = f"{SUPABASE_URL}/rest/v1/options_bots?select=bot_signal,name"
req = urllib.request.Request(url, headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())

signals = {}
for bot in data:
    sig = bot.get('bot_signal', 'unknown')
    signals[sig] = signals.get(sig, 0) + 1

print("ALL BOT SIGNALS IN DATABASE:")
for sig, count in sorted(signals.items()):
    print(f"  {sig}: {count}")

# Now check for 22.5 and 23.5 specifically
for target in ['boof22_5', 'boof23_5']:
    url2 = f"{SUPABASE_URL}/rest/v1/options_bots?select=name,options_trades(status,pnl,created_at,exit_reason)&bot_signal=eq.{target}"
    req2 = urllib.request.Request(url2, headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'})
    try:
        resp2 = urllib.request.urlopen(req2)
        bots = json.loads(resp2.read().decode())
        print(f"\n{target} bots found: {len(bots)}")
        for bot in bots:
            name = bot.get('name', 'unnamed')
            trades = bot.get('options_trades', [])
            print(f"  Bot: {name}, Trades: {len(trades)}")
            if trades:
                for t in trades[:5]:
                    print(f"    {t.get('created_at','?')} | {t.get('status','?')} | P&L: {t.get('pnl','?')} | Exit: {t.get('exit_reason','?')}")
    except Exception as e:
        print(f"Error querying {target}: {e}")
