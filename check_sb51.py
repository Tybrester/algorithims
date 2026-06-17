import requests
URL = "https://isanhutzyctcjygjhzbn.supabase.co/rest/v1/bot_status"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
r = requests.get(f"{URL}?bot=eq.BOOF51&select=symbol,setup_close,setup_watching,metrics&order=symbol.asc",
    headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"}, timeout=5)
for x in r.json():
    print(x["symbol"], "close=" + str(x["setup_close"]), "watching=" + str(x["setup_watching"]))
    print("  ", x["metrics"])
