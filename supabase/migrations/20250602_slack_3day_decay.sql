-- Rebuild slack scores with 3-day decay: Today 60%, Yesterday 30%, 2 days ago 10%

TRUNCATE symbol_slack_scores;

INSERT INTO symbol_slack_scores (
    symbol, bot_id, bot_signal, 
    total_trades, winning_trades, win_rate,
    total_pnl, avg_pnl_per_trade,
    slack_score, updated_at, user_id
)
SELECT 
    t.symbol,
    b.id as bot_id,
    COALESCE(b.bot_signal, 'boof23') as bot_signal,
    -- Weighted trade counts
    SUM(CASE 
        WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
        ELSE 0 
    END) as total_trades,
    -- Weighted winning trades
    SUM(CASE 
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE THEN 0.6
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
        ELSE 0 
    END) as winning_trades,
    -- Weighted win rate
    (SUM(CASE 
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE THEN 0.6
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
        WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
        ELSE 0 
    END) / NULLIF(SUM(CASE 
        WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
        ELSE 0 
    END), 0) * 100) as win_rate,
    -- Weighted P&L
    SUM(CASE 
        WHEN DATE(t.closed_at) = CURRENT_DATE THEN t.pnl * 0.6
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN t.pnl * 0.3
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN t.pnl * 0.1
        ELSE 0 
    END) as total_pnl,
    -- Average weighted P&L per trade
    SUM(CASE 
        WHEN DATE(t.closed_at) = CURRENT_DATE THEN t.pnl * 0.6
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN t.pnl * 0.3
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN t.pnl * 0.1
        ELSE 0 
    END) / NULLIF(SUM(CASE 
        WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
        WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
        ELSE 0 
    END), 0) as avg_pnl_per_trade,
    -- Slack score with weighted values
    GREATEST(50, LEAST(300,
        100 
        + ((SUM(CASE 
            WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE THEN 0.6
            WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
            WHEN t.pnl > 0 AND DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
            ELSE 0 
        END) / NULLIF(SUM(CASE 
            WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
            ELSE 0 
        END), 0) * 100) - 50) * 1.5
        + (SUM(CASE 
            WHEN DATE(t.closed_at) = CURRENT_DATE THEN t.pnl * 0.6
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN t.pnl * 0.3
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN t.pnl * 0.1
            ELSE 0 
        END) / NULLIF(SUM(CASE 
            WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
            ELSE 0 
        END), 0) / 20)
        + LN(SUM(CASE 
            WHEN DATE(t.closed_at) = CURRENT_DATE THEN 0.6
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '1 day' THEN 0.3
            WHEN DATE(t.closed_at) = CURRENT_DATE - INTERVAL '2 days' THEN 0.1
            ELSE 0 
        END) + 1) * 3
    )) as slack_score,
    NOW() as updated_at,
    b.user_id
FROM options_bots b
JOIN options_trades t ON t.bot_id = b.id
WHERE t.status = 'closed' 
  AND t.pnl IS NOT NULL
  AND DATE(t.closed_at) >= CURRENT_DATE - INTERVAL '2 days'
GROUP BY b.id, b.user_id, t.symbol, b.bot_signal;
