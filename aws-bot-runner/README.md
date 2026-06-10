# Boof Capital — AWS EC2 Bot Runner

Always-on Node.js/TypeScript bot running on **EC2 t3.nano in us-east-1** — same data center as Alpaca's matching engine. Replaces Supabase pg_cron + Edge Function cold starts entirely.

## Architecture

```
OLD (slow):
[Supabase pg_cron] ──(lag)──> [Edge Function cold start] ──> [Market Order] = slippage

NEW (zero latency):
[Alpaca OPRA WebSocket] ──(instant 1m bar)──> [EC2 us-east-1] ──> [Limit Order <5ms] = perfect fills
```

The WebSocket bar close **IS** the cron. No polling. No cold starts.

---

## Phase 1 — Launch EC2 Instance

1. Log into [AWS Console](https://console.aws.amazon.com/ec2)
2. **Region**: top-right → **US East (N. Virginia) us-east-1**
3. Click **Launch Instance**
   - **Name**: `Alpaca-Trading-Bot`
   - **OS**: Ubuntu Server 22.04 LTS
   - **Instance type**: `t3.nano` (~$3-4/mo) or `t4g.nano` (ARM, even cheaper)
   - **Key pair**: Create new → RSA → `.pem` → **save to your computer**
   - **Network**: ✅ Allow SSH traffic from: My IP
4. Click **Launch Instance**

---

## Phase 2 — Connect & Configure Server

```bash
# From your local terminal (Mac/Linux):
chmod 400 your-key.pem
ssh -i "your-key.pem" ubuntu@<YOUR_EC2_PUBLIC_IP>

# Inside the EC2 terminal:
sudo apt update && sudo apt install -y nodejs npm git

# Verify Node version (need 18+)
node --version

# If Node is too old, install v20 via nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20 && nvm use 20
```

---

## Phase 3 — Deploy the Bot Code

```bash
# On the EC2 server:
git clone https://github.com/Tybrester/boofcapital.git
cd boofcapital/aws-bot-runner

npm install
npm install typescript ts-node --save-dev

# Create your .env file
cp .env.example .env
nano .env
```

Fill in `.env`:
```env
ALPACA_KEY=your_alpaca_live_api_key
ALPACA_SECRET=your_alpaca_live_secret_key
ALPACA_PAPER=false

SUPABASE_URL=https://isanhutzyctcjygjhzbn.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
```

---

## Phase 4 — Launch 24/7 with PM2

```bash
# Install PM2 globally
sudo npm install pm2 -g

# Start the bot
pm2 start ecosystem.config.js

# Lock it so it auto-restarts on server reboot
pm2 startup
# (run the command it prints, then:)
pm2 save

# Monitor live logs
pm2 logs alpaca-options-bot
```

**Useful PM2 commands:**
```bash
pm2 status                        # check running
pm2 logs alpaca-options-bot       # live log tail
pm2 restart alpaca-options-bot    # restart after code change
pm2 stop alpaca-options-bot       # stop
```

---

## Phase 5 — CRITICAL: Shut Down Supabase Execution

Once the EC2 bot is confirmed live, **kill the old Supabase triggers** to prevent duplicate trades.

### Deactivate Supabase Cron Jobs
Go to **Supabase Dashboard → SQL Editor** and run:
```sql
SELECT cron.unschedule(jobid) FROM cron.job;
```

### Deactivate Edge Functions
Go to **Supabase Dashboard → Edge Functions**.  
The `options-bot` function can be left in place — with cron gone it will never be invoked again. Or delete it entirely.

---

## Environment Variables

| Variable | Description |
|---|---|
| `ALPACA_KEY` | Alpaca live API key |
| `ALPACA_SECRET` | Alpaca live secret key |
| `ALPACA_PAPER` | Set `true` to use paper account, `false` for live |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase **service role** key |

---

## How It Works

- **On startup**: loads all enabled bots from Supabase + pre-fetches 150 candles per symbol
- **On every 1m bar close**: Alpaca WebSocket pushes the bar instantly → runs Boof22/23 signal math → if signal fires, fetches live option quote snapshot → places protected limit order → falls back to market after 5s if unfilled
- **Supabase**: used only as async trade log — never blocks the execution loop
- **PM2**: keeps the process alive 24/7, auto-restarts on crash or server reboot
- **Bot config reload**: every 60s — picks up new bots or setting changes without restart
