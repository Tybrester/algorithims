-- Symbol Slack Score Tracking
-- Tracks historical performance per symbol for smart filtering

CREATE TABLE IF NOT EXISTS symbol_slack_scores (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    symbol text NOT NULL,
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    bot_signal text NOT NULL DEFAULT 'boof23',
    total_trades int DEFAULT 0,
    winning_trades int DEFAULT 0,
    total_pnl decimal(12,2) DEFAULT 0,
    avg_pnl_per_trade decimal(12,2) DEFAULT 0,
    win_rate decimal(5,2) DEFAULT 0,
    slack_score decimal(10,2) DEFAULT 0,
    last_trade_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now(),
    UNIQUE(symbol, user_id, bot_signal)
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_symbol_slack_lookup 
    ON symbol_slack_scores(symbol, user_id, bot_signal);

-- Function to update slack score after trade closes
CREATE OR REPLACE FUNCTION update_symbol_slack_score()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process closed trades with P&L
    IF NEW.status = 'closed' AND NEW.pnl IS NOT NULL THEN
        INSERT INTO symbol_slack_scores (
            symbol, user_id, bot_signal, total_trades, winning_trades, 
            total_pnl, last_trade_at
        )
        VALUES (
            NEW.symbol, NEW.user_id, 
            COALESCE(NEW.signal_version, 'boof23'),
            1, 
            CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            NEW.pnl,
            NEW.closed_at
        )
        ON CONFLICT (symbol, user_id, bot_signal) 
        DO UPDATE SET
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

-- Trigger on options_trades table
DROP TRIGGER IF EXISTS trg_update_symbol_slack ON options_trades;
CREATE TRIGGER trg_update_symbol_slack
    AFTER UPDATE OF status ON options_trades
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION update_symbol_slack_score();

-- Row Level Security
ALTER TABLE symbol_slack_scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own symbol slack scores"
    ON symbol_slack_scores FOR SELECT
    USING (auth.uid() = user_id);
