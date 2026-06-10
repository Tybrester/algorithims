import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    const url = new URL(req.url);
    const userId = url.searchParams.get('user_id');
    const systemId = url.searchParams.get('system_id');

    if (!userId || !systemId) {
      return new Response(JSON.stringify({ error: 'Missing user_id or system_id' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    // Validate system belongs to user and is enabled
    const { data: system, error: sysErr } = await supabase
      .from('systems')
      .select('*')
      .eq('id', systemId)
      .eq('user_id', userId)
      .single();

    if (sysErr || !system) {
      return new Response(JSON.stringify({ error: 'System not found or unauthorized' }), {
        status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    if (!system.enabled) {
      return new Response(JSON.stringify({ error: 'System is disabled' }), {
        status: 403, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // Parse TradingView payload — accept common field name variants
    const wCl = Number(req.headers.get('content-length') || 0);
    if (wCl > 65536) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    const wRaw = await req.text();
    if (wRaw.length > 65536) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    let body: any;
    try { body = JSON.parse(wRaw); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 422, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }); }
    console.log('[Webhook Debug] Raw payload:', JSON.stringify(body));
    const rawAction = (body.action || body.side || body.signal || body.direction_action || 'buy').toLowerCase();
    const action    = ['buy','sell','close'].includes(rawAction) ? rawAction : 'buy';
    const symbol    = (body.symbol || body.ticker || body.instrument || body.asset || '').toString().toUpperCase().replace(/[^A-Z0-9./:!=-]/g, '').slice(0, 30);
    
    // Helper function to normalize symbols for comparison
    function normalizeSymbolForComparison(sym) {
      if (!sym) return '';
      let s = sym.includes(':') ? sym.split(':')[1] : sym;
      s = s.toUpperCase();
      // Map TradingView futures to Yahoo Finance format
      const futuresMap = {
        'CL1!': 'CL=F', 'ES1!': 'ES=F', 'NQ1!': 'NQ=F', 'GC1!': 'GC=F',
        'SI1!': 'SI=F', 'NG1!': 'NG=F', 'ZB1!': 'ZB=F', 'ZN1!': 'ZN=F',
        'YM1!': 'YM=F', 'RTY1!': 'RTY=F', 'MES1!': 'MES=F', 'MNQ1!': 'MNQ=F',
        'MCL1!': 'MCL=F', 'MGC1!': 'MGC=F', 'SIL1!': 'SIL=F', 'MYM1!': 'MYM=F',
        'M2K1!': 'M2K=F',
      };
      return futuresMap[s] || s;
    }

    // Check trade direction restrictions
    const tradeDirection = system.trade_direction || 'both';
    if (tradeDirection !== 'both') {
      // Check for open positions
      const { data: openTrades } = await supabase
        .from('trades')
        .select('*')
        .eq('user_id', userId)
        .eq('system_id', systemId)
        .eq('status', 'filled');
      
      // Normalize the incoming alert symbol
      const normalizedAlertSymbol = normalizeSymbolForComparison(symbol);
      
      // DEBUG: Log what we're checking
      console.log(`[Webhook Debug] Action: ${action}, Symbol: ${symbol}, Normalized: ${normalizedAlertSymbol}`);
      console.log(`[Webhook Debug] Open trades:`, openTrades?.map(t => ({ id: t.id, symbol: t.symbol, action: t.action })));
      
      if (tradeDirection === 'long') {
        // LONG ONLY MODE
        if (action === 'sell') {
          // Sell alerts should only close existing long positions with matching symbol
          // For options, symbol might be the underlying (AAPL) while position is the contract (AAPL250425C190)
          let matchDetails = null;
          const hasMatchingLongPosition = openTrades?.some(t => {
            if (t.action !== 'buy') return false;
            // Normalize the open position symbol
            const openSymbolRaw = (t.symbol || '').toUpperCase();
            const normalizedOpenSymbol = normalizeSymbolForComparison(t.symbol);
            
            console.log(`[Webhook Debug] Checking position: ${t.symbol} (raw: ${openSymbolRaw}, normalized: ${normalizedOpenSymbol}) vs alert: ${symbol} (normalized: ${normalizedAlertSymbol})`);
            
            // Exact match after normalization: CL=F === CL=F
            if (normalizedOpenSymbol === normalizedAlertSymbol) {
              console.log(`[Webhook Debug] ✓ Matched by normalized symbol`);
              matchDetails = { type: 'normalized', openSymbol: t.symbol };
              return true;
            }
            // Also check raw symbol match
            if (openSymbolRaw === symbol.toUpperCase()) {
              console.log(`[Webhook Debug] ✓ Matched by raw symbol`);
              matchDetails = { type: 'raw', openSymbol: t.symbol };
              return true;
            }
            // Options match: alert ticker "AAPL" matches contract "AAPL250425C190"
            if (openSymbolRaw.startsWith(symbol.toUpperCase()) && /\d{6}[CP]\d+$/.test(openSymbolRaw)) {
              console.log(`[Webhook Debug] ✓ Matched by options pattern`);
              matchDetails = { type: 'options', openSymbol: t.symbol };
              return true;
            }
            return false;
          });
          console.log(`[Webhook Debug] Has matching long position: ${hasMatchingLongPosition}, Match details:`, matchDetails);
          if (!hasMatchingLongPosition) {
            // No matching long position to close - fail the trade
            const { data: trade, error: tradeErr } = await supabase.from('trades').insert({
              user_id: userId,
              system_id: systemId,
              symbol,
              action,
              quantity: parseFloat(body.quantity || body.qty || body.size || body.contracts || body.amount || 1),
              price: null,
              order_type: body.order_type || body.orderType || body.type || 'market',
              broker: system.broker || body.broker || body.account || 'paper',
              status: 'failed',
              failure_reason: `System set to Long Only: Sell alerts only close existing long positions. No open long position found for ${symbol}.`,
              payload: body,
              created_at: new Date().toISOString(),
            }).select().single();
            
            if (tradeErr) {
              return new Response(JSON.stringify({ error: tradeErr.message }), {
                status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
              });
            }
            
            return new Response(JSON.stringify({ 
              success: true, 
              status: 'failed',
              reason: `No open long position for ${symbol} to close (Long Only mode)`,
              trade_id: trade.id 
            }), {
              status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          // Has matching long position - CLOSE the existing trade instead of creating new sell trade
          const matchedTrade = openTrades.find(t => {
            if (t.action !== 'buy') return false;
            const openSymbolRaw = (t.symbol || '').toUpperCase();
            const normalizedOpenSymbol = normalizeSymbolForComparison(t.symbol);
            if (normalizedOpenSymbol === normalizedAlertSymbol) return true;
            if (openSymbolRaw === symbol.toUpperCase()) return true;
            if (openSymbolRaw.startsWith(symbol.toUpperCase()) && /\d{6}[CP]\d+$/.test(openSymbolRaw)) return true;
            return false;
          });
          
          if (matchedTrade) {
            console.log(`[Webhook Debug] Closing existing long position: ${matchedTrade.id}`);
            
            // Get exit price (use provided price or fetch current)
            let exitPrice = parseFloat(body.price || body.close || 0) || null;
            if (!exitPrice) {
              try {
                const ticker = symbol.includes(':') ? symbol.split(':')[1] : symbol;
                const priceRes = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${ticker}?interval=1m&range=1d`);
                const priceJson = await priceRes.json();
                exitPrice = priceJson?.chart?.result?.[0]?.meta?.regularMarketPrice || matchedTrade.price;
              } catch (e) {
                exitPrice = matchedTrade.price;
              }
            }
            
            // Calculate P&L
            const normalizedSymbol = normalizeSymbolForComparison(symbol);
            const isOption = /\d{6}[CP]\d+$/.test(symbol);
            const contractMultipliers = {
              'ES=F': 50, 'MES=F': 5, 'NQ=F': 20, 'MNQ=F': 2,
              'CL=F': 1000, 'MCL=F': 100, 'GC=F': 100, 'MGC=F': 10,
              'SI=F': 5000, 'SIL=F': 1000, 'NG=F': 10000,
              'ZB=F': 1000, 'ZN=F': 1000, 'YM=F': 5, 'MYM=F': 0.5,
              'RTY=F': 50, 'M2K=F': 5,
            };
            const multiplier = isOption ? 100 : (contractMultipliers[normalizedSymbol] || 1);
            const qty = matchedTrade.quantity || 1;
            const pointDiff = exitPrice - matchedTrade.price;
            const pnl = pointDiff * multiplier * qty;
            
            // Update paper balance for sell
            const { data: acct } = await supabase.from('paper_accounts').select('*').eq('user_id', userId).maybeSingle();
            if (acct) {
              const proceeds = exitPrice * qty;
              const newBalance = acct.balance + proceeds;
              await supabase.from('paper_accounts').update({ balance: newBalance, updated_at: new Date().toISOString() }).eq('user_id', userId);
            }
            
            // Close the existing trade
            const { data: updatedTrade, error: updateErr } = await supabase.from('trades').update({
              status: 'closed',
              exit_price: exitPrice,
              pnl: pnl,
              closed_at: new Date().toISOString(),
              payload: { ...matchedTrade.payload, close_alert: body },
            }).eq('id', matchedTrade.id).select().single();
            
            if (updateErr) {
              return new Response(JSON.stringify({ error: updateErr.message }), {
                status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
              });
            }
            
            return new Response(JSON.stringify({ 
              success: true, 
              status: 'closed',
              reason: `Closed long position for ${symbol}`,
              trade_id: matchedTrade.id,
              pnl: pnl
            }), {
              status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
        }
        // Any action other than 'buy' (opening long) in Long Only mode should be blocked
        // Short selling actions like 'sellshort', 'short', etc. are not allowed
        const shortActionKeywords = ['sellshort', 'short', 'shortsell', 'sell_short'];
        const isShortAction = shortActionKeywords.some(kw => action.includes(kw));
        if (isShortAction) {
          const { data: trade, error: tradeErr } = await supabase.from('trades').insert({
            user_id: userId,
            system_id: systemId,
            symbol,
            action,
            quantity: parseFloat(body.quantity || body.qty || body.size || body.contracts || body.amount || 1),
            price: null,
            order_type: body.order_type || body.orderType || body.type || 'market',
            broker: system.broker || body.broker || body.account || 'paper',
            status: 'failed',
            failure_reason: 'System set to Long Only: Short selling is not allowed. Use "buy" for long entries and "sell" to close long positions only.',
            payload: body,
            created_at: new Date().toISOString(),
          }).select().single();
          
          if (tradeErr) {
            return new Response(JSON.stringify({ error: tradeErr.message }), {
              status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          
          return new Response(JSON.stringify({ 
            success: true, 
            status: 'failed',
            reason: 'Short selling not allowed in Long Only mode',
            trade_id: trade.id 
          }), {
            status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        // Buy action in Long Only - allowed, continues to create new long position
      }
      
      if (tradeDirection === 'short') {
        // SHORT ONLY MODE
        if (action === 'buy') {
          // Buy alerts should only close existing short positions with matching symbol
          const hasMatchingShortPosition = openTrades?.some(t => {
            if (t.action !== 'sell') return false;
            // Normalize the open position symbol
            const openSymbolRaw = (t.symbol || '').toUpperCase();
            const normalizedOpenSymbol = normalizeSymbolForComparison(t.symbol);
            
            // Exact match after normalization: CL=F === CL=F
            if (normalizedOpenSymbol === normalizedAlertSymbol) return true;
            // Also check raw symbol match
            if (openSymbolRaw === symbol.toUpperCase()) return true;
            // Options match: alert ticker "AAPL" matches contract "AAPL250425C190"
            if (openSymbolRaw.startsWith(symbol.toUpperCase()) && /\d{6}[CP]\d+$/.test(openSymbolRaw)) return true;
            return false;
          });
          if (!hasMatchingShortPosition) {
            // No matching short position to close - fail the trade
            const { data: trade, error: tradeErr } = await supabase.from('trades').insert({
              user_id: userId,
              system_id: systemId,
              symbol,
              action,
              quantity: parseFloat(body.quantity || body.qty || body.size || body.contracts || body.amount || 1),
              price: null,
              order_type: body.order_type || body.orderType || body.type || 'market',
              broker: system.broker || body.broker || body.account || 'paper',
              status: 'failed',
              failure_reason: `System set to Short Only: Buy alerts only close existing short positions. No open short position found for ${symbol}.`,
              payload: body,
              created_at: new Date().toISOString(),
            }).select().single();
            
            if (tradeErr) {
              return new Response(JSON.stringify({ error: tradeErr.message }), {
                status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
              });
            }
            
            return new Response(JSON.stringify({ 
              success: true, 
              status: 'failed',
              reason: `No open short position for ${symbol} to close (Short Only mode)`,
              trade_id: trade.id 
            }), {
              status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          // Has matching short position - buy will close it, allow to continue
        }
        // Any action that would open a long position in Short Only mode should be blocked
        // Buy actions that are NOT closing shorts (buy to open) are not allowed
        const isBuyToOpen = action === 'buy' && !openTrades?.some(t => {
          if (t.action !== 'sell') return false;
          const openSymbolRaw = (t.symbol || '').toUpperCase();
          const normalizedOpenSymbol = normalizeSymbolForComparison(t.symbol);
          if (normalizedOpenSymbol === normalizedAlertSymbol) return true;
          if (openSymbolRaw === symbol.toUpperCase()) return true;
          if (openSymbolRaw.startsWith(symbol.toUpperCase()) && /\d{6}[CP]\d+$/.test(openSymbolRaw)) return true;
          return false;
        });
        if (isBuyToOpen) {
          const { data: trade, error: tradeErr } = await supabase.from('trades').insert({
            user_id: userId,
            system_id: systemId,
            symbol,
            action,
            quantity: parseFloat(body.quantity || body.qty || body.size || body.contracts || body.amount || 1),
            price: null,
            order_type: body.order_type || body.orderType || body.type || 'market',
            broker: system.broker || body.broker || body.account || 'paper',
            status: 'failed',
            failure_reason: 'System set to Short Only: Long positions are not allowed. Use "sell" or "short" for short entries and "buy" to close short positions only.',
            payload: body,
            created_at: new Date().toISOString(),
          }).select().single();
          
          if (tradeErr) {
            return new Response(JSON.stringify({ error: tradeErr.message }), {
              status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
            });
          }
          
          return new Response(JSON.stringify({ 
            success: true, 
            status: 'failed',
            reason: 'Long positions not allowed in Short Only mode',
            trade_id: trade.id 
          }), {
            status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          });
        }
        // Sell/Short action in Short Only - allowed, continues to create new short position
      }
    }
    
    // Use already parsed values
    const quantity  = parseFloat(body.quantity || body.qty || body.size || body.contracts || body.amount || 1);
    const orderType = body.order_type || body.orderType || body.type || 'market';
    const broker    = system.broker || body.broker || body.account || 'paper';

    // Parse options data
    const isOption = body.assetType === 'OPTION' || body.optionType || body.expiration;
    let optionsInfo = null;
    if (isOption) {
      const expirationStr = body.expiration || '';
      let daysToExpiration = null;
      
      // Parse "+6 day" format
      if (expirationStr.includes('+') && expirationStr.includes('day')) {
        const match = expirationStr.match(/\+(\d+)\s*day/);
        if (match) daysToExpiration = parseInt(match[1]);
      }
      
      const intrinsicValue = body.intrinsicValue || 'otm';
      const strikesAway = body.strikesAway || body.strikes_away || 0;
      const optionType = body.optionType || body.option_type || 'call';
      
      optionsInfo = {
        isOption: true,
        optionType: optionType.toLowerCase(),
        daysToExpiration,
        intrinsicValue: intrinsicValue.toLowerCase(),
        strikesAway: parseInt(strikesAway) || 0,
        expiration: expirationStr,
        takeProfit: body.takeProfit || body.take_profit || null,
        stopLoss: body.stopLoss || body.stop_loss || null,
      };
    }

    // Fetch live price — accept common aliases
    let price = parseFloat(body.price || body.close || body.entry_price || body.last || 0) || null;
    if (!price) {
      try {
        let ticker = symbol.includes(':') ? symbol.split(':')[1] : symbol;
        
        // Crypto - use Binance for better crypto prices
        if (ticker.endsWith('USDT') || ['BTC','ETH','SOL','ADA','DOT','AVAX','MATIC','LINK','UNI','ATOM','FIL','ETC','ALGO','NEAR','XTZ','VET','THETA','XLM','EOS','TRX','BCH','LTC','XRP'].some(c => ticker.startsWith(c))) {
          const cryptoSymbol = ticker.endsWith('USDT') ? ticker : `${ticker}USDT`;
          const binanceRes = await fetch(`https://api.binance.com/api/v3/ticker/price?symbol=${cryptoSymbol}`);
          const binanceJson = await binanceRes.json();
          price = parseFloat(binanceJson?.price) || null;
          console.log(`[Price] Crypto ${cryptoSymbol}: $${price}`);
        } else {
          // Stocks - use Yahoo Finance
          if (ticker.endsWith('USDT')) ticker = ticker.replace('USDT', '-USD');
          const priceRes = await fetch(
            `https://query1.finance.yahoo.com/v8/finance/chart/${ticker}?interval=1m&range=1d`
          );
          const priceJson = await priceRes.json();
          price = priceJson?.chart?.result?.[0]?.meta?.regularMarketPrice || null;
          console.log(`[Price] Stock ${ticker}: $${price}`);
        }
      } catch (e) { 
        console.log('[Price] Error fetching price:', e);
        price = null; 
      }
    }

    // Handle paper trading with balance check
    const isPaperBroker = broker === 'paper' || broker === 'BoofCapital paper' || broker === 'EasyTrade Paper';
    let tradeStatus = 'open';
    let failureReason = null;
    let finalPrice = price;
    
    if (isPaperBroker && system.auto_submit && price) {
      const cost = price * quantity;
      const { data: acct } = await supabase.from('paper_accounts').select('*').eq('user_id', userId).maybeSingle();
      const currentBalance = acct?.balance ?? 100000;
      
      // Check sufficient balance for buy orders BEFORE creating trade
      if (action === 'buy' && cost > currentBalance) {
        // Go straight to failed - don't even try to fill
        tradeStatus = 'failed';
        failureReason = `Insufficient funds: trade cost $${cost.toFixed(2)} exceeds balance $${currentBalance.toFixed(2)}`;
      } else {
        // Sufficient balance - fill immediately
        tradeStatus = 'filled';
        if (acct) {
          const newBalance = action === 'buy' ? acct.balance - cost : acct.balance + cost;
          await supabase.from('paper_accounts').update({ balance: newBalance, updated_at: new Date().toISOString() }).eq('user_id', userId);
        } else {
          await supabase.from('paper_accounts').insert({ user_id: userId, balance: action === 'buy' ? 100000 - cost : 100000 + cost });
        }
      }
    }

    // Insert trade record with final status
    const now = new Date().toISOString();
    
    // Enhance payload with options info
    const enhancedPayload = {
      ...body,
      options_parsed: optionsInfo,
    };
    
    const { data: trade, error: tradeErr } = await supabase.from('trades').insert({
      user_id: userId,
      system_id: systemId,
      symbol,
      action,
      quantity,
      price: finalPrice,
      order_type: orderType,
      broker,
      status: tradeStatus,
      failure_reason: failureReason,
      filled_at: tradeStatus === 'filled' ? now : null,
      payload: enhancedPayload,
      created_at: now,
    }).select().single();

    if (tradeErr) {
      return new Response(JSON.stringify({ error: tradeErr.message }), {
        status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // Handle tastytrade — place real order via direct API
    if (broker === 'tastytrade' && system.auto_submit) {
      try {
        const { data: credRow } = await supabase
          .from('broker_credentials')
          .select('credentials')
          .eq('user_id', userId)
          .eq('broker', 'tastytrade')
          .maybeSingle();

        if (credRow?.credentials) {
          const { username, password } = credRow.credentials;
          let sessionToken = credRow.credentials.session_token;
          let sessionValid = false;
          let accountNumber = credRow.credentials.account_number;

          // 1. Try to use existing session token first
          if (sessionToken) {
            try {
              // Test if session is still valid by fetching accounts
              const testRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
                headers: { Authorization: sessionToken }
              });
              if (testRes.ok) {
                const testJson = await testRes.json();
                if (testJson?.data?.items?.[0]?.account?.['account-number']) {
                  sessionValid = true;
                  accountNumber = testJson.data.items[0].account['account-number'];
                  console.log('[Tastytrade] Using existing session');
                }
              }
            } catch (_) {
              sessionValid = false;
            }
          }

          // 2. If no valid session, authenticate fresh
          if (!sessionValid) {
            console.log('[Tastytrade] Creating new session');
            const { remember_token } = credRow.credentials;
            const sessionRes = await fetch('https://api.tastytrade.com/sessions', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(
                remember_token
                  ? { login: username, password, 'remember-me': true, 'remember-token': remember_token }
                  : { login: username, password, 'remember-me': true }
              )
            });
            const sessionJson = await sessionRes.json();
            sessionToken = sessionJson?.data?.['session-token'];
            if (!sessionToken) throw new Error('tastytrade auth failed');
            
            // Get account number
            const acctRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
              headers: { Authorization: sessionToken }
            });
            const acctJson = await acctRes.json();
            accountNumber = acctJson?.data?.items?.[0]?.account?.['account-number'];
            if (!accountNumber) throw new Error('No tastytrade account found');
            
            // Store session token for future use
            await supabase.from('broker_credentials').update({
              credentials: {
                ...credRow.credentials,
                session_token: sessionToken,
                account_number: accountNumber,
                session_created_at: new Date().toISOString()
              }
            }).eq('user_id', userId).eq('broker', 'tastytrade');
          }

          // 3. Handle options - find specific contract if needed
          let finalSymbol = symbol;
          let instrumentType = 'Equity';
          
          if (isOption && optionsInfo && optionsInfo.daysToExpiration && optionsInfo.strikesAway) {
            // Get option chain to find matching expiration and strike
            console.log(`[Tastytrade] Looking for ${symbol} options: ${optionsInfo.daysToExpiration} days out, ${optionsInfo.strikesAway} strikes ${optionsInfo.optionType}`);
            
            // Get option chain
            const chainRes = await fetch(`https://api.tastytrade.com/symbols/search/${symbol}/option-chains`, {
              headers: { Authorization: sessionToken }
            });
            const chainJson = await chainRes.json();
            const items = chainJson?.data?.items || [];
            
            // Filter for call/put
            const optionType = optionsInfo.optionType === 'call' ? 'C' : 'P';
            const relevant = items.filter((item: any) => 
              item['option-type'] === optionType && 
              item['strike-price'] && 
              item['expiration-date']
            );
            
            // Find expiration closest to days out
            const targetDate = new Date();
            targetDate.setDate(targetDate.getDate() + optionsInfo.daysToExpiration);
            
            let closestExp = null;
            let minDayDiff = Infinity;
            
            for (const opt of relevant) {
              const expDate = new Date(opt['expiration-date']);
              const dayDiff = Math.abs(expDate.getTime() - targetDate.getTime()) / (1000 * 60 * 60 * 24);
              if (dayDiff < minDayDiff) {
                minDayDiff = dayDiff;
                closestExp = opt['expiration-date'];
              }
            }
            
            // Filter to closest expiration
            const sameExp = relevant.filter((item: any) => item['expiration-date'] === closestExp);
            
            // Sort by strike price
            sameExp.sort((a: any, b: any) => a['strike-price'] - b['strike-price']);
            
            // Find strike closest to current underlying price, then count strikes away
            let selectedStrike = null;
            if (sameExp.length > 0) {
              const underlyingPrice = price || finalPrice || sameExp[0]['strike-price'];
              
              // Find strikes above/below underlying based on call/put and OTM direction
              const isCall = optionsInfo.optionType === 'call';
              const strikes = sameExp.map((s: any) => s['strike-price']);
              
              // For calls OTM: strikes above current price
              // For puts OTM: strikes below current price
              let candidateStrikes;
              if (isCall) {
                candidateStrikes = strikes.filter((s: number) => s > underlyingPrice);
              } else {
                candidateStrikes = strikes.filter((s: number) => s < underlyingPrice);
              }
              
              // Sort and pick the one strikesAway from ATM
              candidateStrikes.sort((a: number, b: number) => isCall ? a - b : b - a);
              const strikeIndex = Math.min(optionsInfo.strikesAway - 1, candidateStrikes.length - 1);
              selectedStrike = candidateStrikes[strikeIndex] || candidateStrikes[0];
            }
            
            if (selectedStrike && closestExp) {
              // Find the option symbol
              const selected = sameExp.find((s: any) => s['strike-price'] === selectedStrike);
              if (selected) {
                finalSymbol = selected['symbol'];
                instrumentType = 'Option';
                console.log(`[Tastytrade] Selected option: ${finalSymbol} (strike: ${selectedStrike}, exp: ${closestExp})`);
              }
            }
          }
          
          // 4. Place order
          const orderAction = action === 'buy' ? 'Buy to Open' : 'Sell to Close';
          const orderRes = await fetch(`https://api.tastytrade.com/accounts/${accountNumber}/orders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: sessionToken },
            body: JSON.stringify({
              'order-type': orderType === 'limit' ? 'Limit' : 'Market',
              'time-in-force': 'Day',
              legs: [{
                'instrument-type': instrumentType,
                symbol: finalSymbol,
                quantity,
                action: orderAction
              }]
            })
          });
          const orderJson = await orderRes.json();
          const orderId = orderJson?.data?.order?.id;

          await supabase.from('trades').update({
            status: 'filled',
            broker_order_id: orderId || null
          }).eq('id', trade.id);

          // Session stays active - user must manually logout from broker page
        }
      } catch (tastyErr) {
        // Log error on trade but don't fail the webhook
        await supabase.from('trades').update({ status: 'open', broker_error: String(tastyErr) }).eq('id', trade.id);
      }
    }

    return new Response(JSON.stringify({ 
      success: true, 
      trade_id: trade.id, 
      symbol, 
      action, 
      price, 
      quantity, 
      status: tradeStatus,
      options: optionsInfo,
      message: optionsInfo 
        ? `Option: ${optionsInfo.optionType.toUpperCase()}, ${optionsInfo.daysToExpiration} days to expiration, ${optionsInfo.strikesAway} strikes ${optionsInfo.intrinsicValue.toUpperCase()}`
        : null,
    }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }
});
