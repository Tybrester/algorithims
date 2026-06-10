-- Alpaca Trades Storage
-- Stores fetched Alpaca orders for historical tracking and P&L analysis

CREATE TABLE IF NOT EXISTS alpaca_trades (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Alpaca Order Data
    alpaca_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL, -- 'buy' or 'sell'
    qty NUMERIC,
    filled_qty NUMERIC,
    filled_avg_price NUMERIC,
    order_type TEXT, -- 'market', 'limit', etc.
    status TEXT NOT NULL, -- 'filled', 'partially_filled', 'canceled', etc.
    created_at TIMESTAMP NOT NULL,
    submitted_at TIMESTAMP,
    filled_at TIMESTAMP,
    
    -- P&L Data (from positions API)
    unrealized_pl NUMERIC DEFAULT 0,
    realized_pl NUMERIC DEFAULT 0,
    cost_basis NUMERIC,
    
    -- Raw JSON for complete data
    raw_data JSONB,
    
    -- Tracking
    fetched_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(user_id, alpaca_order_id)
);

-- Enable RLS
ALTER TABLE alpaca_trades ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only access their own Alpaca trades
DROP POLICY IF EXISTS "Users can only access their own Alpaca trades" ON alpaca_trades;
CREATE POLICY "Users can only access their own Alpaca trades"
    ON alpaca_trades FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_user_id ON alpaca_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_symbol ON alpaca_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_created_at ON alpaca_trades(created_at);
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_status ON alpaca_trades(status);

COMMENT ON TABLE alpaca_trades IS 'Stores Alpaca broker orders for tracking and P&L analysis';
