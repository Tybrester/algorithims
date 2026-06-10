import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const corsHeaders = { 
  'Access-Control-Allow-Origin': '*', 
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 
  'Access-Control-Allow-Methods': 'POST, OPTIONS' 
};

// Paper trading configuration
const PAPER_SPREAD_PCT = 0.05; // 5% spread simulation (bid/ask)
const PAPER_FILL_DELAY_MS = 200; // Simulate network delay

// Price source - use Polygon or Alpha Vantage for paper quotes
const POLYGON_API_KEY = Deno.env.get('POLYGON_API_KEY') || '';
const ALPHA_VANTAGE_KEY = Deno.env.get('ALPHA_VANTAGE_API_KEY') || '';

interface PaperPosition {
  id: string;
  bot_id: string;
  user_id: string;
  symbol: string;
  option_type: 'call' | 'put';
  strike: number;
  expiration_date: string;
  contracts: number;
  entry_price: number;
  entry_time: string;
  unrealized_pnl: number;
  status: 'open' | 'closed';
}

// ─────────────────────────────────────────────
// PRICE FETCHING (Paper trading - no Alpaca)
// ─────────────────────────────────────────────

async function fetchPaperQuote(symbol: string): Promise<{ price: number; bid: number; ask: number } | null> {
  try {
    // Try Polygon first
    if (POLYGON_API_KEY) {
      const res = await fetch(
        `https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/${symbol}?apiKey=${POLYGON_API_KEY}`,
        { signal: AbortSignal.timeout(3000) }
      );
      if (res.ok) {
        const data = await res.json();
        const ticker = data.tickers?.[0];
        if (ticker?.lastTrade?.p) {
          const price = ticker.lastTrade.p;
          const spread = price * PAPER_SPREAD_PCT;
          return { price, bid: price - spread, ask: price + spread };
        }
      }
    }
    
    // Fallback to Alpha Vantage
    if (ALPHA_VANTAGE_KEY) {
      const res = await fetch(
        `https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=${symbol}&apikey=${ALPHA_VANTAGE_KEY}`,
        { signal: AbortSignal.timeout(3000) }
      );
      if (res.ok) {
        const data = await res.json();
        const price = parseFloat(data['Global Quote']?.['05. price']);
        if (price) {
          const spread = price * PAPER_SPREAD_PCT;
          return { price, bid: price - spread, ask: price + spread };
        }
      }
    }
    
    return null;
  } catch (e) {
    console.error('[PaperQuote] Error:', e);
    return null;
  }
}

// Simple Black-Scholes for paper option pricing
function paperOptionPrice(
  spot: number, 
  strike: number, 
  daysToExpiry: number, 
  type: 'call' | 'put',
  iv: number = 0.30
): { price: number; bid: number; ask: number } {
  // Simplified: just use intrinsic + time value approximation
  const timeValue = Math.max(0, spot * iv * Math.sqrt(daysToExpiry / 365));
  const intrinsic = type === 'call' 
    ? Math.max(0, spot - strike)
    : Math.max(0, strike - spot);
  
  const price = intrinsic + timeValue;
  const spread = price * PAPER_SPREAD_PCT;
  
  return {
    price,
    bid: Math.max(0.01, price - spread),
    ask: price + spread
  };
}

// ─────────────────────────────────────────────
// PAPER TRADING LOGIC
// ─────────────────────────────────────────────

async function executePaperTrade(
  supabase: any,
  bot: any,
  signal: { direction: 'call' | 'put'; confidence: number },
  quote: { price: number; bid: number; ask: number }
): Promise<{ success: boolean; trade?: any; error?: string }> {
  const symbol = bot.symbol || 'SPY';
  const amount = bot.amount || 500;
  
  // Get or calculate expiry
  const expDate = getMonthlyExpiry();
  const daysToExpiry = Math.ceil((new Date(expDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  
  // Pick strike (0.3 ATR from spot - closer to ATM)
  const atr = quote.price * 0.02; // Approximate 2% daily ATR
  const strikeDistance = atr * 0.3;
  const rawStrike = signal.direction === 'call' 
    ? quote.price + strikeDistance
    : quote.price - strikeDistance;
  
  // Round to valid strike
  let interval = quote.price > 500 ? 5 : (quote.price > 50 ? 2.5 : 1);
  const strike = Math.round(rawStrike / interval) * interval;
  
  // Calculate option price
  const optQuote = paperOptionPrice(quote.price, strike, daysToExpiry, signal.direction);
  const midPrice = (optQuote.bid + optQuote.ask) / 2;
  
  // Check budget
  const maxContracts = Math.floor(amount / (midPrice * 100));
  if (maxContracts < 1) {
    return { success: false, error: `Option too expensive: $${midPrice.toFixed(2)} for $${amount} budget` };
  }
  
  const contracts = Math.min(maxContracts, 2); // Max 2 contracts per trade
  const fillPrice = optQuote.ask; // Paper fill at ask (worst case)
  const totalCost = fillPrice * contracts * 100;
  
  // Simulate fill delay
  await new Promise(r => setTimeout(r, PAPER_FILL_DELAY_MS));
  
  // Record paper trade
  const tradeData = {
    bot_id: bot.id,
    user_id: bot.user_id,
    symbol: symbol,
    option_type: signal.direction,
    strike: strike,
    expiration_date: expDate,
    contracts: contracts,
    entry_price: fillPrice,
    total_cost: totalCost,
    status: 'open',
    broker: 'paper', // Mark as paper trade
    entry_time: new Date().toISOString(),
    unrealized_pnl: 0,
    paper_mode: true
  };
  
  const { data: trade, error } = await supabase
    .from('options_trades')
    .insert(tradeData)
    .select()
    .single();
  
  if (error) {
    return { success: false, error: `DB insert failed: ${error.message}` };
  }
  
  return { success: true, trade };
}

// ─────────────────────────────────────────────
// TP/SL CHECK FOR PAPER TRADES
// ─────────────────────────────────────────────

async function checkPaperTPSL(supabase: any): Promise<void> {
  const { data: openTrades } = await supabase
    .from('options_trades')
    .select('*')
    .eq('status', 'open')
    .eq('paper_mode', true);
  
  if (!openTrades || openTrades.length === 0) return;
  
  for (const trade of openTrades) {
    // Get current stock price
    const quote = await fetchPaperQuote(trade.symbol);
    if (!quote) continue;
    
    // Calculate current option value
    const daysLeft = Math.ceil((new Date(trade.expiration_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    const optQuote = paperOptionPrice(quote.price, trade.strike, daysLeft, trade.option_type as 'call' | 'put');
    const currentPrice = optQuote.bid; // Use bid for exit
    
    const entryValue = trade.entry_price * trade.contracts * 100;
    const currentValue = currentPrice * trade.contracts * 100;
    const pnl = currentValue - entryValue;
    const pnlPct = (pnl / entryValue) * 100;
    
    // Check TP/SL (40% TP, -15% SL from bot config)
    const tp = 40;
    const sl = -15;
    
    const shouldClose = pnlPct >= tp || pnlPct <= sl || daysLeft <= 0;
    
    if (shouldClose) {
      const reason = pnlPct >= tp ? 'take_profit' : (pnlPct <= sl ? 'stop_loss' : 'expiry');
      
      await supabase.from('options_trades')
        .update({
          status: 'closed',
          exit_price: currentPrice,
          pnl: pnl,
          closed_at: new Date().toISOString(),
          close_reason: reason
        })
        .eq('id', trade.id);
      
      console.log(`[PaperTPSL] Closed ${trade.symbol} ${trade.option_type} $${trade.strike}: ${reason} P&L=$${pnl.toFixed(2)} (${pnlPct.toFixed(1)}%)`);
    } else {
      // Update unrealized P&L
      await supabase.from('options_trades')
        .update({ unrealized_pnl: pnl })
        .eq('id', trade.id);
    }
  }
}

// ─────────────────────────────────────────────
// MAIN HANDLER
// ─────────────────────────────────────────────

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { headers: corsHeaders });
  
  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') || '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || ''
    );
    
    const url = new URL(req.url);
    const action = url.searchParams.get('action') || 'trade';
    
    // Get paper trading bots
    const { data: bots } = await supabase
      .from('options_bots')
      .select('*')
      .eq('broker', 'paper')
      .eq('enabled', true);
    
    if (!bots || bots.length === 0) {
      return new Response(JSON.stringify({ message: 'No paper bots active' }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    
    // Check TP/SL on existing paper trades
    await checkPaperTPSL(supabase);
    
    if (action === 'tpsl_only') {
      return new Response(JSON.stringify({ success: true, message: 'TP/SL check complete' }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    
    // Execute new trades for each bot
    const results = [];
    
    for (const bot of bots) {
      try {
        // Fetch stock price
        const quote = await fetchPaperQuote(bot.symbol || 'SPY');
        if (!quote) {
          results.push({ bot: bot.name, error: 'Failed to fetch quote' });
          continue;
        }
        
        // Generate signal (simplified - use random for demo, or integrate with your signal logic)
        // For production, import your signal functions like:
        // const signal = await generateSignal(bot.symbol, bot.signal_strategy);
        const signal = {
          direction: Math.random() > 0.5 ? 'call' : 'put' as 'call' | 'put',
          confidence: 0.6
        };
        
        // Check if we already have a position for this symbol
        const { data: existing } = await supabase
          .from('options_trades')
          .select('id')
          .eq('bot_id', bot.id)
          .eq('symbol', bot.symbol)
          .eq('status', 'open')
          .eq('paper_mode', true)
          .maybeSingle();
        
        if (existing) {
          results.push({ bot: bot.name, skipped: 'Already has open position' });
          continue;
        }
        
        // Execute paper trade
        const result = await executePaperTrade(supabase, bot, signal, quote);
        results.push({ 
          bot: bot.name, 
          symbol: bot.symbol,
          signal: signal.direction,
          ...result 
        });
        
      } catch (e) {
        results.push({ bot: bot.name, error: e.message });
      }
    }
    
    return new Response(JSON.stringify({ success: true, results }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
    
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});

function getMonthlyExpiry(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const firstDay = new Date(year, month, 1);
  let firstFriday = 1 + ((5 - firstDay.getDay() + 7) % 7);
  const thirdFriday = firstFriday + 14;
  return new Date(year, month, thirdFriday).toISOString().slice(0, 10);
}
