-- Phase 1 Security: Enable RLS on all tables
-- Run this in Supabase Dashboard > SQL Editor

-- ─── stock_bots ───────────────────────────────────────────
ALTER TABLE stock_bots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only access their own stock bots" ON stock_bots;
CREATE POLICY "Users can only access their own stock bots"
  ON stock_bots FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ─── options_bots ─────────────────────────────────────────
ALTER TABLE options_bots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only access their own options bots" ON options_bots;
CREATE POLICY "Users can only access their own options bots"
  ON options_bots FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ─── trades ───────────────────────────────────────────────
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only access their own trades" ON trades;
CREATE POLICY "Users can only access their own trades"
  ON trades FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ─── options_trades ───────────────────────────────────────
ALTER TABLE options_trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only access their own options trades" ON options_trades;
CREATE POLICY "Users can only access their own options trades"
  ON options_trades FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ─── broker_credentials ───────────────────────────────────
ALTER TABLE broker_credentials ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only access their own broker credentials" ON broker_credentials;
CREATE POLICY "Users can only access their own broker credentials"
  ON broker_credentials FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ─── audit_logs ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id UUID,
  old_values JSONB,
  new_values JSONB,
  ip_address TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can only view their own audit logs" ON audit_logs;
CREATE POLICY "Users can only view their own audit logs"
  ON audit_logs FOR SELECT
  USING (auth.uid() = user_id);

-- ─── broker_connections view (hides raw credentials) ──────
CREATE OR REPLACE VIEW broker_connections AS
SELECT
  id,
  user_id,
  broker,
  created_at,
  CASE WHEN credentials IS NOT NULL THEN true ELSE false END AS is_connected
FROM broker_credentials;
