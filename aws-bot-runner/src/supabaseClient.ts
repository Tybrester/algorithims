import 'dotenv/config';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import WS from 'ws';

export const supabase: SupabaseClient = createClient(
  process.env.SUPABASE_URL!,
  (process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY)!,
  { global: { headers: {} }, realtime: { transport: WS as any } }
);

export interface BotConfig {
  id: string;
  user_id: string;
  name: string;
  enabled: boolean;
  auto_submit: boolean;
  broker: string;
  bot_signal: string;
  bot_symbol: string;
  bot_scan_mode: string;
  bot_interval: string;
  bot_expiry_type: string;
  option_type: string;
  take_profit_pct: number;
  stop_loss_pct: number;
  paper_balance: number;
  paper_balance_start: number;
  market_open_delay_min: number;
  max_daily_trades: number | null;
  daily_trade_count: number;
  last_run_at: string | null;
  enabled_at: string | null;
  reset_at: string | null;
  contracts: number;
  amount_per_trade: number;
  chop_take_profit_pct?: number;
  chop_stop_loss_pct?: number;
}

export interface OpenTrade {
  id: string;
  bot_id: string;
  user_id: string;
  symbol: string;
  option_type: 'call' | 'put';
  strike: number;
  expiration_date: string;
  premium_per_contract: number;
  total_cost: number;
  contracts: number;
  status: string;
  order_id: string | null;
  entered_at: string;
  pnl: number | null;
}

export async function loadAllEnabledBots(): Promise<BotConfig[]> {
  const { data, error } = await supabase
    .from('options_bots')
    .select('*')
    .eq('enabled', true)
    .eq('auto_submit', true);

  if (error) {
    console.error('[Supabase] Failed to load bots:', error.message);
    return [];
  }
  return (data || []) as BotConfig[];
}

export async function loadOpenTrades(botId: string): Promise<OpenTrade[]> {
  const { data, error } = await supabase
    .from('options_trades')
    .select('*')
    .eq('bot_id', botId)
    .eq('status', 'open');

  if (error) {
    console.error(`[Supabase] Failed to load open trades for bot ${botId}:`, error.message);
    return [];
  }
  return (data || []) as OpenTrade[];
}

export async function getAlpacaCreds(userId: string): Promise<{ api_key: string; secret_key: string; env: string } | null> {
  const { data, error } = await supabase
    .from('broker_credentials')
    .select('credentials')
    .eq('user_id', userId)
    .eq('broker', 'alpaca')
    .maybeSingle();

  if (error || !data) return null;
  return data.credentials as { api_key: string; secret_key: string; env: string };
}

export async function recordTrade(trade: Record<string, any>): Promise<void> {
  const { error } = await supabase.from('options_trades').insert(trade);
  if (error) console.error('[Supabase] Insert trade failed:', error.message);
}

export async function closeTrade(tradeId: string, exitPrice: number, pnl: number): Promise<void> {
  const { error } = await supabase
    .from('options_trades')
    .update({ status: 'closed', exit_price: exitPrice, pnl, closed_at: new Date().toISOString() })
    .eq('id', tradeId);
  if (error) console.error('[Supabase] Close trade failed:', error.message);
}

export async function updateBotBalance(botId: string, newBalance: number): Promise<void> {
  const { error } = await supabase
    .from('options_bots')
    .update({ paper_balance: newBalance })
    .eq('id', botId);
  if (error) console.error('[Supabase] Update balance failed:', error.message);
}

export async function updateBotLastRun(botId: string): Promise<void> {
  const { error } = await supabase
    .from('options_bots')
    .update({ last_run_at: new Date().toISOString() })
    .eq('id', botId);
  if (error) console.error('[Supabase] Update last_run_at failed:', error.message);
}

export async function incrementDailyTradeCount(botId: string, currentCount: number): Promise<void> {
  const { error } = await supabase
    .from('options_bots')
    .update({ daily_trade_count: currentCount + 1 })
    .eq('id', botId);
  if (error) console.error('[Supabase] Increment trade count failed:', error.message);
}
