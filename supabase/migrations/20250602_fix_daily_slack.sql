-- Fix: Backfill daily_pnl and daily_trades for today's date

-- First get today's date
DO $$
DECLARE
    today_str text := to_char(current_date, 'YYYY-MM-DD');
BEGIN
    -- Update existing slack scores with today's trade data
    UPDATE symbol_slack_scores s
    SET 
        daily_pnl = COALESCE(d.daily_pnl, 0),
        daily_trades = COALESCE(d.daily_trades, 0),
        daily_reset_date = today_str,
        updated_at = now()
    FROM (
        SELECT 
            symbol,
            user_id,
            bot_id,
            COALESCE(signal_version, 'boof23') as bot_signal,
            SUM(pnl) as daily_pnl,
            COUNT(*) as daily_trades
        FROM options_trades
        WHERE status = 'closed'
          AND pnl IS NOT NULL
          AND closed_at >= current_date
        GROUP BY symbol, user_id, bot_id, COALESCE(signal_version, 'boof23')
    ) d
    WHERE s.symbol = d.symbol 
      AND s.user_id = d.user_id
      AND (s.bot_id IS NOT DISTINCT FROM d.bot_id);

    RAISE NOTICE 'Updated daily slack scores for %', today_str;
END $$;

-- Also backfill any missing slack scores completely
INSERT INTO symbol_slack_scores (symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at, daily_pnl, daily_trades, daily_reset_date)
SELECT 
    t.symbol,
    t.user_id,
    t.bot_id,
    COALESCE(t.signal_version, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(t.pnl) as total_pnl,
    SUM(t.pnl) / NULLIF(COUNT(*), 0) as avg_pnl_per_trade,
    (SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / NULLIF(COUNT(*), 0)) * 100 as win_rate,
    100 + (SUM(t.pnl) / 100) as slack_score,
    MAX(t.closed_at) as last_trade_at,
    SUM(CASE WHEN t.closed_at >= current_date THEN t.pnl ELSE 0 END) as daily_pnl,
    SUM(CASE WHEN t.closed_at >= current_date THEN 1 ELSE 0 END) as daily_trades,
    to_char(current_date, 'YYYY-MM-DD') as daily_reset_date
FROM options_trades t
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
GROUP BY t.symbol, t.user_id, t.bot_id, COALESCE(t.signal_version, 'boof23')
ON CONFLICT (symbol, user_id, bot_id) 
DO UPDATE SET
    bot_signal = EXCLUDED.bot_signal,
    total_trades = EXCLUDED.total_trades,
    winning_trades = EXCLUDED.winning_trades,
    total_pnl = EXCLUDED.total_pnl,
    avg_pnl_per_trade = EXCLUDED.avg_pnl_per_trade,
    win_rate = EXCLUDED.win_rate,
    slack_score = EXCLUDED.slack_score,
    last_trade_at = EXCLUDED.last_trade_at,
    daily_pnl = EXCLUDED.daily_pnl,
    daily_trades = EXCLUDED.daily_trades,
    daily_reset_date = EXCLUDED.daily_reset_date,
    updated_at = now();

-- Verify
SELECT symbol, total_pnl, daily_pnl, daily_trades, win_rate, slack_score
FROM symbol_slack_scores 
WHERE daily_trades > 0 OR total_trades > 0
ORDER BY daily_pnl DESC
LIMIT 10;
