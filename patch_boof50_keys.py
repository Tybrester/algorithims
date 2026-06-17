with open("/home/ec2-user/algorithims/boof50_live.py", "r") as f:
    src = f.read()

src = src.replace(
    'API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"',
    'API_KEY    = "PKTAPRDPBBOKTQYZGNBDZJ6XJZ"'
)
src = src.replace(
    'API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"',
    'API_SECRET = "6tzye8uezFRCV13EwhUqft4BNV6cg47kC77WgRVVZrpi"'
)

with open("/home/ec2-user/algorithims/boof50_live.py", "w") as f:
    f.write(src)

print("Keys updated OK")
