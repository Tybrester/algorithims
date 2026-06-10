-- Fix the trigger function to use correct slack score formula
-- Formula: 100 + (win_rate - 50)*1.5 + avg_pnl/20 + ln(total_trades+1)*3, clamped 50-300

DROP TRIGGER IF EXISTS trg_update_symbol_slack ON options_trades;

CREATE OR REPLACE FUNCTION update_symbol_slack_score()
RETURNS TRIGGER AS $$
DECLARE
    new_total_trades int;
    new_winning_trades int;
    new_win_rate decimal;
    new_total_pnl decimal;
    new_avg_pnl decimal;
    new_slack_score decimal;
BEGIN
    -- Only process closed trades with P&L
    IF NEW.status = 'closed' AND NEW.pnl IS NOT NULL THEN
        -- Calculate new stats
        SELECT 
            COALESCE(total_trades, 0) + 1,
            COALESCE(winning_trades, 0) + CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END,
            COALESCE(total_pnl, 0) + NEW.pnl
        INTO new_total_trades, new_winning_trades, new_total_pnl
        FROM symbol_slack_scores
        WHERE symbol = NEW.symbol AND user_id = NEW.user_id AND bot_id = NEW.bot_id;
        
        -- Handle first trade for this symbol/bot
        IF new_total_trades IS NULL THEN
            new_total_trades := 1;
            new_winning_trades := CASE WHEN NEW.pnl > 0 THEN 1 ELSE 0 END;
            new_total_pnl := NEW.pnl;
        END IF;
        
        -- Calculate derived metrics
        new_win_rate := (new_winning_trades::decimal / new_total_trades) * 100;
        new_avg_pnl := new_total_pnl / new_total_trades;
        
        -- Calculate slack score using proper formula with baseline 100
        -- Formula: 100 + (win_rate - 50)*1.5 + avg_pnl/20 + ln(total_trades+1)*3
        new_slack_score := GREATEST(50, LEAST(300,
            100 
            + ((new_win_rate - 50) * 1.5)
            + (new_avg_pnl / 20)
            + LN(new_total_trades + 1) * 3
        ));
        
        INSERT INTO symbol_slack_scores (
            symbol, user_id, bot_id, bot_signal, total_trades, winning_trades, 
            total_pnl, avg_pnl_per_trade, win_rate, slack_score, last_trade_at, daily_pnl, daily_trades
        )
        VALUES (
            NEW.symbol, NEW.user_id, NEW.bot_id,
            COALESCE(NEW.signal_version, 'boof23'),
            new_total_trades,
            new_winning_trades,
            new_total_pnl,
            new_avg_pnl,
            new_win_rate,
            new_slack_score,
            NEW.closed_at,
            NEW.pnl,  -- daily_pnl starts with this trade's P&L
            1         -- daily_trades starts at 1
        )
        ON CONFLICT ON CONSTRAINT symbol_slack_scores_symbol_user_id_bot_id_key
        DO UPDATE SET
            bot_signal = EXCLUDED.bot_signal,
            total_trades = EXCLUDED.total_trades,
            winning_trades = EXCLUDED.winning_trades,
            total_pnl = EXCLUDED.total_pnl,
            avg_pnl_per_trade = EXCLUDED.avg_pnl_per_trade,
            win_rate = EXCLUDED.win_rate,
            slack_score = EXCLUDED.slack_score,
            last_trade_at = EXCLUDED.last_trade_at,
            -- Update daily stats (simple approach - adds to existing daily)
            daily_pnl = CASE 
                WHEN DATE(symbol_slack_scores.last_trade_at) = CURRENT_DATE 
                THEN symbol_slack_scores.daily_pnl + NEW.pnl 
                ELSE NEW.pnl 
            END,
            daily_trades = CASE 
                WHEN DATE(symbol_slack_scores.last_trade_at) = CURRENT_DATE 
                THEN symbol_slack_scores.daily_trades + 1 
                ELSE 1 
            END,
            updated_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_symbol_slack
    AFTER UPDATE OF status ON options_trades
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION update_symbol_slack_score();
