-- Symbol Slack Score v2 - Daily Reset Version
-- Slack resets to 100 every day, intraday updates based on performance

-- Add daily tracking columns
ALTER TABLE symbol_slack_scores 
    ADD COLUMN IF NOT EXISTS daily_trades int DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_pnl decimal(12,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS daily_reset_date text;

-- Update trigger for intraday slack calculation
CREATE OR REPLACE FUNCTION update_symbol_slack_score()
RETURNS TRIGGER AS $$
DECLARE
    new_slack decimal(10,2);
    current_daily_pnl decimal(12,2);
    current_daily_trades int;
BEGIN
    -- Only process closed trades with P&L
    IF NEW.status = 'closed' AND NEW.pnl IS NOT NULL THEN
        
        -- Get current daily values (in case record exists)
        SELECT COALESCE(daily_pnl, 0), COALESCE(daily_trades, 0)
        INTO current_daily_pnl, current_daily_trades
        FROM symbol_slack_scores
        WHERE symbol = NEW.symbol 
          AND user_id = NEW.user_id 
          AND bot_signal = COALESCE(NEW.signal_version, 'boof23');
        
        -- Calculate intraday slack: baseline 100 + (daily_pnl × 0.6)
        -- Positive P&L increases slack, negative decreases it
        -- Multiplier 0.6 = ~6 losses needed to filter out (vs ~3 with 2.0)
        new_slack := 100 + ((current_daily_pnl + NEW.pnl) * 0.6);
        
        -- Clamp slack between 0 and 200 (prevent extreme values)
        IF new_slack < 0 THEN new_slack := 0; END IF;
        IF new_slack > 200 THEN new_slack := 200; END IF;
        
        INSERT INTO symbol_slack_scores (
            symbol, user_id, bot_signal, total_trades, winning_trades, 
            total_pnl, last_trade_at, slack_score, daily_trades, daily_pnl
        )
        VALUES (
            NEW.symbol, NEW.user_id, 
            COALESCE(NEW.signal_version, 'boof23'),
            1, 
            CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            NEW.pnl,
            NEW.closed_at,
            new_slack,
            1,
            NEW.pnl
        )
        ON CONFLICT (symbol, user_id, bot_signal) 
        DO UPDATE SET
            -- Cumulative stats (all-time)
            total_trades = symbol_slack_scores.total_trades + 1,
            winning_trades = symbol_slack_scores.winning_trades + 
                CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            total_pnl = symbol_slack_scores.total_pnl + NEW.pnl,
            avg_pnl_per_trade = (symbol_slack_scores.total_pnl + NEW.pnl) / 
                (symbol_slack_scores.total_trades + 1),
            win_rate = ((symbol_slack_scores.winning_trades + 
                CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END)::decimal / 
                (symbol_slack_scores.total_trades + 1)) * 100,
            last_trade_at = NEW.closed_at,
            updated_at = now(),
            -- Daily stats (intraday)
            daily_trades = symbol_slack_scores.daily_trades + 1,
            daily_pnl = symbol_slack_scores.daily_pnl + NEW.pnl,
            -- Intraday slack: 100 + (daily_pnl × 0.6), clamped 0-200
            -- Lower multiplier = more losses needed to filter out (~6 losses)
            slack_score = GREATEST(0, LEAST(200, 100 + ((symbol_slack_scores.daily_pnl + NEW.pnl) * 0.6)));
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

-- Create or replace policy for new columns
CREATE POLICY "Users can update own daily slack" ON symbol_slack_scores
    FOR UPDATE USING (auth.uid() = user_id);
