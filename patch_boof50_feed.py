with open("/home/ec2-user/algorithims/boof50_live.py", "r") as f:
    src = f.read()

src = src.replace('data_feed="sip"', 'data_feed="iex"')

with open("/home/ec2-user/algorithims/boof50_live.py", "w") as f:
    f.write(src)

print("Feed patched to iex OK")
