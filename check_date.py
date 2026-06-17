import pytz, datetime
ET = pytz.timezone('America/New_York')
now = datetime.datetime.now(ET)
print('ET:', now.strftime('%Y-%m-%d %H:%M %A'))
print('UTC:', datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M'))
