// Options TP/SL Daemon — Fast exit execution
// Runs every 30 seconds, checks all open positions, closes on TP/SL hit

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

// ── BLACK-SCHOLES (fallback when real price fails) ──
function normCDF(x: number): number {
  return 0.5 * (1 + erf(x / Math.sqrt(2)));
}

function erf(x: number): number {
  const sign = x >= 0 ? 1 : -1;
  x = Math.abs(x);
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return sign * y;
}

function blackScholes(S: number, K: number, T: number, r: number, sigma: number, type: 'call' | 'put'): number {
  if (T <= 0) return Math.max(0, type === 'call' ? S - K : K - S);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  if (type === 'call') {
    return S * normCDF(d1) - K * Math.exp(-r * T) * normCDF(d2);
  } else {
    return K * Math.exp(-r * T) * normCDF(-d2) - S * normCDF(-d1);
  }
}

function calcHistoricalVolatility(closes: number[], period = 20, interval = '1h'): number {
  const returns: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    returns.push(Math.log(closes[i] / closes[i - 1]));
  }
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / returns.length;
  const annualFactor = interval === '1m' ? Math.sqrt(252 * 390) : interval === '5m' ? Math.sqrt(252 * 78) : interval === '15m' ? Math.sqrt(252 * 26) : interval === '1h' ? Math.sqrt(252 * 6.5) : Math.sqrt(252);
  return Math.sqrt(variance) * annualFactor;
}

// ── FETCH REAL OPTION PRICE ──
async function fetchRealOptionPrice(symbol: string, strike: number, expiration: string, optionType: string, interval = '1h', userId?: string, supabase?: any, alpacaApiKey?: string, alpacaSecretKey?: string): Promise<number> {
  // 1. Try Alpaca OPRA first (real-time, no auth needed beyond API key)
  if (alpacaApiKey && alpacaSecretKey) {
    try {
      const exp = expiration.replace(/-/g, '');
      const yy = exp.slice(2, 4);
      const mm = exp.slice(4, 6);
      const dd = exp.slice(6, 8);
      const optSymbol = `${symbol}${yy}${mm}${dd}${optionType.toUpperCase().charAt(0)}${String(Math.round(strike * 1000)).padStart(8, '0')}`;
      const url = `https://data.alpaca.markets/v1beta1/options/snapshots/${encodeURIComponent(optSymbol)}`;
      const res = await fetch(url, { headers: { 'APCA-API-KEY-ID': alpacaApiKey, 'APCA-API-SECRET-KEY': alpacaSecretKey } });
      if (res.ok) {
        const json = await res.json();
        const snap = json?.snapshot ?? json;
        const bid = snap?.latestQuote?.bp ?? 0;
        const ask = snap?.latestQuote?.ap ?? 0;
        const mid = (bid + ask) / 2;
        if (mid > 0) { console.log(`[TPSLDaemon] Alpaca OPRA price ${optSymbol}: $${mid.toFixed(2)}`); return mid; }
      }
    } catch (_) {}
  }

  // 2. Try Tastytrade if userId provided
  if (userId && supabase) {
    try {
      const { data: creds } = await supabase.from('broker_credentials')
        .select('credentials').eq('user_id', userId).eq('broker', 'tastytrade').maybeSingle();
      if (creds?.credentials?.refresh_token) {
        const tokenRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/tasty-oauth?action=refresh&user_id=${userId}`, {
          headers: { 'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}` }
        });
        const tokenJson = await tokenRes.json();
        if (tokenJson.access_token) {
          const exp = expiration.replace(/-/g, '');
          const yy = exp.slice(2, 4);
          const mm = exp.slice(4, 6);
          const dd = exp.slice(6, 8);
          const sym = `${symbol}${yy}${mm}${dd}${optionType.toUpperCase().charAt(0)}${String(Math.round(strike * 1000)).padStart(8, '0')}`;
          const url = `https://api.tastytrade.com/market-data/streamers/quotes/${sym}`;
          const res = await fetch(url, { headers: { 'Authorization': `Bearer ${tokenJson.access_token}` } });
          const json = await res.json();
          const quote = json?.data?.[0];
          const mid = quote?.mid ?? ((quote?.bid + quote?.ask) / 2);
          if (mid > 0) return mid;
        }
      }
    } catch (_) {}
  }
  
  return 0;
}

// ── MAIN DAEMON ──
Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });
  
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  );
  
  const R = 0.05;
  const results: any[] = [];
  
  try {
    // Get all open option trades
    const { data: openTrades, error: tradesError } = await supabase
      .from('options_trades')
      .select('*, options_bots!inner(user_id, bot_interval, broker, take_profit_pct, stop_loss_pct, symbol_rules, consecutive_losses, max_consecutive_losses, cooldown_minutes, cooldown_until)')
      .eq('status', 'open');
    
    if (tradesError) throw tradesError;
    if (!openTrades || openTrades.length === 0) {
      return new Response(JSON.stringify({ status: 'ok', message: 'No open trades to check', checked: 0 }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }
    
    console.log(`[TPSLDaemon] Checking ${openTrades.length} open trades for TP/SL`);

    // Cache Alpaca creds per user
    const alpacaCache: Record<string, { api_key?: string; secret_key?: string }> = {};
    
    for (const trade of openTrades) {
      try {
        const bot = trade.options_bots;
        const interval = bot?.bot_interval ?? '1h';
        const userId = bot?.user_id;

        // Fetch Alpaca creds once per user
        if (userId && !alpacaCache[userId]) {
          const { data: alpRow } = await supabase.from('broker_credentials').select('credentials').eq('user_id', userId).eq('broker', 'alpaca').maybeSingle();
          alpacaCache[userId] = alpRow?.credentials ?? {};
        }
        const alpacaApiKey = alpacaCache[userId]?.api_key;
        const alpacaSecretKey = alpacaCache[userId]?.secret_key;
        
        // Fetch current option price — Alpaca OPRA first, Tastytrade fallback
        const optionPrice = await fetchRealOptionPrice(
          trade.symbol, 
          trade.strike, 
          trade.expiration_date, 
          trade.option_type, 
          interval, 
          userId,
          supabase,
          alpacaApiKey,
          alpacaSecretKey
        );
        
        if (!optionPrice || optionPrice <= 0) {
          console.log(`[TPSLDaemon] SKIP: No price for ${trade.symbol} $${trade.strike}`);
          results.push({ trade_id: trade.id, symbol: trade.symbol, action: 'skip', reason: 'No price available' });
          continue;
        }
        
        // Calculate P&L %
        const entry = Number(trade.premium_per_contract);
        const pnlPct = ((optionPrice - entry) / entry) * 100;
        
        // Use per-symbol rules if available (Boof 8.0 adaptive), otherwise bot defaults
        const symbolRules: any[] = bot?.symbol_rules || [];
        const symRule = symbolRules.find((r: any) => r.symbol?.toUpperCase() === trade.symbol?.toUpperCase());
        const tpPct = symRule?.tp ?? Number(bot?.take_profit_pct ?? 50);
        const slPct = symRule?.sl ?? Number(bot?.stop_loss_pct ?? -20);
        
        // 5-min SL grace window: don't trigger stop in first 5 min after entry
        const entryAge = trade.created_at
          ? (Date.now() - new Date(trade.created_at).getTime()) / 1000 / 60
          : 999;
        const slActive = entryAge >= 5;

        // EOD force-close at 4:29 PM ET (2:29 PM MST)
        const etStr = new Date().toLocaleString('en-US', { timeZone: 'America/New_York' });
        const etNow = new Date(etStr);
        const isEOD = etNow.getHours() > 16 || (etNow.getHours() === 16 && etNow.getMinutes() >= 29);

        // Check TP/SL
        const shouldTP = pnlPct >= tpPct;
        const shouldSL = slActive && pnlPct <= slPct;
        
        console.log(`[TPSLDaemon] ${trade.symbol} ${trade.option_type} $${trade.strike}: current=$${optionPrice.toFixed(2)} entry=$${entry.toFixed(2)} pnl=${pnlPct.toFixed(1)}% tp=${tpPct}% sl=${slPct}% age=${entryAge.toFixed(1)}m shouldTP=${shouldTP} shouldSL=${shouldSL}`);
        
        if (!shouldTP && !shouldSL && !isEOD) {
          results.push({ trade_id: trade.id, symbol: trade.symbol, action: 'hold', pnl_pct: pnlPct });
          continue;
        }
        if (isEOD) console.log(`[TPSLDaemon] EOD force-close ${trade.symbol} pnl=${pnlPct.toFixed(1)}%`);
        
        // CLOSE TRADE
        const pnl = (optionPrice - entry) * trade.contracts * 100;
        const exitReason = shouldTP ? 'tp' : isEOD && !shouldSL ? 'eod' : 'sl';
        
        // Paper trading close
        if (bot?.broker === 'paper' || !bot?.broker) {
          await supabase.from('options_trades').update({
            status: 'closed',
            exit_price: optionPrice,
            pnl: pnl,
            exit_reason: exitReason,
            closed_at: new Date().toISOString()
          }).eq('id', trade.id);
          
          // Return balance
          const { data: bRow } = await supabase.from('options_bots')
            .select('paper_balance')
            .eq('id', trade.bot_id)
            .single();
          const bal = Number(bRow?.paper_balance ?? 100000);

          // Track consecutive losses (for logging only, no cooldowns)
          const isLoss = pnl < 0;
          const prevConsec = Number(bot?.consecutive_losses ?? 0);
          const newConsec = isLoss ? prevConsec + 1 : 0;

          // Track per-symbol loss count (for logging only, no cooldown)
          const symCooldowns: Record<string, any> = (bot?.symbol_cooldowns as any) ?? {};
          const sym = (trade.symbol as string).toUpperCase();
          if (isLoss) {
            const prev = symCooldowns[sym] ?? { losses: 0 };
            const newLosses = (prev.losses ?? 0) + 1;
            symCooldowns[sym] = { losses: newLosses, until: null };
          } else {
            // Win resets symbol loss counter
            if (symCooldowns[sym]) symCooldowns[sym] = { losses: 0, until: null };
          }

          const botUpdate: any = {
            paper_balance: bal + Number(trade.total_cost) + pnl,
            consecutive_losses: newConsec,
            symbol_cooldowns: symCooldowns,
            cooldown_until: null, // Always clear cooldown
          };
          await supabase.from('options_bots').update(botUpdate).eq('id', trade.bot_id);
          
          console.log(`[TPSLDaemon] CLOSED ${trade.symbol} at ${exitReason.toUpperCase()}: $${optionPrice.toFixed(2)} pnl=$${pnl.toFixed(2)} consec_losses=${newConsec}`);
          results.push({ trade_id: trade.id, symbol: trade.symbol, action: 'close', reason: exitReason, pnl: pnl, pnl_pct: pnlPct });
        } else {
          // Live broker close would go here
          results.push({ trade_id: trade.id, symbol: trade.symbol, action: 'pending', reason: 'Live broker close not implemented in daemon' });
        }
        
      } catch (tradeErr) {
        console.log(`[TPSLDaemon] ERROR on trade ${trade.id}: ${tradeErr}`);
        results.push({ trade_id: trade.id, symbol: trade.symbol, action: 'error', error: String(tradeErr) });
      }
    }
    
    return new Response(JSON.stringify({ 
      status: 'ok', 
      checked: openTrades.length,
      closed: results.filter(r => r.action === 'close').length,
      results 
    }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    
  } catch (err) {
    console.log(`[TPSLDaemon] FATAL ERROR: ${err}`);
    return new Response(JSON.stringify({ error: String(err) }), { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
  }
});
