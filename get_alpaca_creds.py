"""Fetch Alpaca credentials from Supabase"""
import os
from supabase import create_client

url = os.getenv('SUPABASE_URL', 'https://isanhutzyctcjygjhzbn.supabase.co')
key = os.getenv('SUPABASE_ANON_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDI4NTgwMzAsImV4cCI6MjA1ODQzNDAzMH0.Fm9c0t8aE8nL1bwBuu1akb6vKj-4N_8h3Wyn82VfY8Y')

sb = create_client(url, key)

# Fetch credentials
res = sb.from_('broker_credentials').select('credentials').eq('broker', 'alpaca').limit(1).execute()

data = res.data
if data and len(data) > 0:
    creds = data[0]['credentials']
    print(f"export APCA_API_KEY_ID='{creds.get('api_key', '')}'")
    print(f"export APCA_API_SECRET_KEY='{creds.get('secret_key', '')}'")
else:
    print("No Alpaca credentials found in database")
