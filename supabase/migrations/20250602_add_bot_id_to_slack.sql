-- Add bot_id to symbol_slack_scores for per-bot tracking
-- This allows different timeframes (1m vs 5m) to have separate slack scores

-- Add bot_id column
ALTER TABLE symbol_slack_scores ADD COLUMN IF NOT EXISTS bot_id uuid REFERENCES options_bots(id) ON DELETE CASCADE;

-- Backfill bot_id from options_trades for existing slack scores
-- This aggregates trade data per bot and recreates slack scores
INSERT INTO symbol_slack_scores (symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at)
SELECT 
    t.symbol,
    t.user_id,
    t.bot_id,
    COALESCE(t.signal_version, 'boof23') as bot_signal,
    COUNT(*) as total_trades,
    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(t.pnl) as total_pnl,
    SUM(t.pnl) / COUNT(*) as avg_pnl_per_trade,
    (SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100 as win_rate,
    ((SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100) * 
     (SUM(t.pnl) / COUNT(*)) * 
     ln(COUNT(*) + 1) as slack_score,
    MAX(t.closed_at) as last_trade_at
FROM options_trades t
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
  AND t.bot_id IS NOT NULL
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
    updated_at = now();

-- Drop old unique constraint and index
ALTER TABLE symbol_slack_scores DROP CONSTRAINT IF EXISTS symbol_slack_scores_symbol_user_id_bot_signal_key;
DROP INDEX IF EXISTS idx_symbol_slack_lookup;

-- Create new unique constraint with bot_id
ALTER TABLE symbol_slack_scores ADD CONSTRAINT symbol_slack_scores_symbol_user_id_bot_id_key 
    UNIQUE (symbol, user_id, bot_id);

-- Create new index with bot_id
CREATE INDEX IF NOT EXISTS idx_symbol_slack_bot_lookup 
    ON symbol_slack_scores(symbol, user_id, bot_id, bot_signal);

-- Update the trigger function to include bot_id
CREATE OR REPLACE FUNCTION update_symbol_slack_score()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process closed trades with P&L
    IF NEW.status = 'closed' AND NEW.pnl IS NOT NULL THEN
        INSERT INTO symbol_slack_scores (
            symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, 
            total_pnl, last_trade_at
        )
        VALUES (
            NEW.symbol, NEW.user_id, NEW.bot_id,
            COALESCE(NEW.signal_version, 'boof23'),
            1, 
            CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            NEW.pnl,
            NEW.closed_at
        )
        ON CONFLICT (symbol, user_id, bot_id) 
        DO UPDATE SET
            bot_signal = EXCLUDED.bot_signal,
            total_trades = symbol_slack_scores.total_trades + 1,
            winning_trades = symbol_slack_scores.winning_trades + 
                CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            total_pnl = symbol_slack_scores.total_pnl + NEW.pnl,
            avg_pnl_per_trade = (symbol_slack_scores.total_pnl + NEW.pnl) / 
                (symbol_slack_scores.total_trades + 1),
            win_rate = ((symbol_slack_scores.winning_trades + 
                CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END)::decimal / 
                (symbol_slack_scores.total_trades + 1)) * 100,
            -- Slack Score = Win% × Avg PnL × ln(Trade Count + 1)
            slack_score = (((symbol_slack_scores.winning_trades + 
                CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END)::decimal / 
                (symbol_slack_scores.total_trades + 1)) * 100) * 
                ((symbol_slack_scores.total_pnl + NEW.pnl) / 
                (symbol_slack_scores.total_trades + 1)) * 
                ln(symbol_slack_scores.total_trades + 2),
            last_trade_at = NEW.closed_at,
            updated_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Recreate the trigger
DROP TRIGGER IF EXISTS trg_update_symbol_slack ON options_trades;
CREATE TRIGGER trg_update_symbol_slack
    AFTER UPDATE OF status ON options_trades
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION update_symbol_slack_score();

-- Add policy for bot_id based access (if needed)
-- Note: The existing policy on user_id should still work
