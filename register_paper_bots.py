"""
Run once to insert Boof 23 and Boof 29 paper bot records into stock_bots table.
Prints the bot IDs to paste into the paper scripts.
"""
import requests, json

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
ANON_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
USER_ID      = "d0bb84ba-f968-446c-9792-9bcff8849e37"

HEADERS = {
    "apikey":        ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=representation",
}

bots = [
    {
        "name":               "Boof 23 Paper Bot",
        "user_id":            USER_ID,
        "broker":             "paper",
        "bot_signal":         "boof23",
        "bot_symbol":         "MULTI",
        "bot_scan_mode":      "scan",
        "bot_interval":       "5Min",
        "bot_dollar_amount":  500,
        "bot_trade_direction":"both",
        "enabled":            True,
        "auto_submit":        True,
        "paper_balance":      5000,
        "run_interval_min":   5,
    },
    {
        "name":               "Boof 29 Paper Bot",
        "user_id":            USER_ID,
        "broker":             "paper",
        "bot_signal":         "boof29",
        "bot_symbol":         "MULTI",
        "bot_scan_mode":      "scan",
        "bot_interval":       "5Min",
        "bot_dollar_amount":  500,
        "bot_trade_direction":"long",
        "enabled":            True,
        "auto_submit":        True,
        "paper_balance":      5000,
        "run_interval_min":   5,
    },
]

for bot in bots:
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/stock_bots",
        headers=HEADERS,
        json=bot
    )
    if r.ok:
        data = r.json()
        bot_id = data[0]["id"] if isinstance(data, list) else data.get("id")
        print(f"  {bot['name']}: id={bot_id}")
    else:
        print(f"  {bot['name']} FAILED: {r.status_code} {r.text[:200]}")
