import requests

url = 'https://isanhutzyctcjygjhzbn.supabase.co/rest/v1/broker_credentials'
headers = {
    'apikey': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDI4NTgwMzAsImV4cCI6MjA1ODQzNDAzMH0.Fm9c0t8aE8nL1bwBuu1akb6vKj-4N_8h3Wyn82VfY8Y',
    'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDI4NTgwMzAsImV4cCI6MjA1ODQzNDAzMH0.Fm9c0t8aE8nL1bwBuu1akb6vKj-4N_8h3Wyn82VfY8Y'
}

params = {'select': 'credentials', 'broker': 'eq.alpaca'}

res = requests.get(url, headers=headers, params=params)
if res.status_code == 200:
    data = res.json()
    if data:
        creds = data[0]['credentials']
        key = creds.get('api_key', '')
        secret = creds.get('secret_key', '')
        print(f"APCA_API_KEY_ID={key}")
        print(f"APCA_API_SECRET_KEY={secret}")
    else:
        print('No Alpaca credentials found')
else:
    print(f'Error: {res.status_code}')
