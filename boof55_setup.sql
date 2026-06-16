-- BOOF55 Setup SQL
-- Run this in Supabase → SQL Editor

-- Step 1: See what bots currently exist
SELECT id, name, bot_signal, bot_scan_mode, bot_expiry_type, enabled, auto_submit
FROM options_bots
ORDER BY name;

-- Step 2: Update the BOOF50 row to BOOF55
-- (run Step 1 first, then uncomment and run this with the correct id)

/*
UPDATE options_bots
SET
  name            = 'BOOF55',
  bot_signal      = 'boof55',
  bot_scan_mode   = 'scan_boof55',
  bot_expiry_type = 'stock',
  enabled         = true,
  auto_submit     = true,
  updated_at      = now()
WHERE name = 'BOOF50';
*/

-- Step 3: If no BOOF50 row exists, INSERT a new BOOF55 bot
-- (replace user_id with your actual user id from auth.users)

/*
INSERT INTO options_bots (
  name, bot_signal, bot_scan_mode, bot_expiry_type,
  enabled, auto_submit, paper_balance, contracts,
  amount_per_trade, take_profit_pct, stop_loss_pct,
  max_daily_trades, daily_trade_count, broker,
  user_id, created_at, updated_at
)
SELECT
  'BOOF55', 'boof55', 'scan_boof55', 'stock',
  true, true, 3000, 1,
  300, 120, 1,
  5, 0, 'alpaca_paper',
  id, now(), now()
FROM auth.users
LIMIT 1;
*/
