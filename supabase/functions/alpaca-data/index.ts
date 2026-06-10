import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    const adCl = Number(req.headers.get('content-length') || 0);
    if (adCl > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    const adRaw = await req.text();
    if (adRaw.length > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    let adParsed: any;
    try { adParsed = JSON.parse(adRaw); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 422, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }); }
    const user_id  = typeof adParsed.user_id === 'string' ? adParsed.user_id.trim().slice(0, 64) : '';
    const symbol   = typeof adParsed.symbol === 'string' ? adParsed.symbol.toUpperCase().replace(/[^A-Z0-9./:!=-]/g, '').slice(0, 30) : '';
    const interval = typeof adParsed.interval === 'string' ? adParsed.interval : '1h';
    const bars     = Math.min(Math.max(1, Number(adParsed.bars) || 150), 1000);
    const type     = typeof adParsed.type === 'string' ? adParsed.type : 'candles';
    if (!user_id || !symbol) {
      return new Response(JSON.stringify({ error: 'user_id and symbol are required' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    if (!/^[0-9a-f-]{36}$/i.test(user_id)) return new Response(JSON.stringify({ error: 'Invalid user_id' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    // Check if it's a crypto symbol
    const cryptoSymbols = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'BNB-USD', 'DOGE-USD', 'ADA-USD', 'AVAX-USD', 'LINK-USD', 'MATIC-USD', 'LTC-USD', 'UNI-USD', 'SHIB-USD'];
    const isCrypto = cryptoSymbols.includes(symbol.toUpperCase()) || symbol.includes('-USD');
    
    // Hardcoded crypto prices as reliable fallback
    const cryptoPrices: Record<string, number> = {
      'BTC-USD': 65000, 'ETH-USD': 3500, 'SOL-USD': 150, 'XRP-USD': 0.60,
      'BNB-USD': 600, 'DOGE-USD': 0.15, 'ADA-USD': 0.45, 'AVAX-USD': 35,
      'LINK-USD': 18, 'MATIC-USD': 0.70, 'LTC-USD': 75, 'UNI-USD': 8,
      'SHIB-USD': 0.000025
    };
    
    // Handle crypto via Yahoo Finance or hardcoded fallback
    if (isCrypto) {
      let price = 0;
      let candles: Candle[] = [];
      let source = 'hardcoded';
      
      // Try Yahoo Finance first
      try {
        const yahooSymbol = symbol.toUpperCase();
        const url = `https://query1.finance.yahoo.com/v8/finance/chart/${yahooSymbol}?interval=1h&range=5d`;
        
        const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
        if (res.ok) {
          const data = await res.json();
          const result = data?.chart?.result?.[0];
          if (result) {
            const meta = result.meta;
            const timestamps = result.timestamp || [];
            const quotes = result.indicators?.quote?.[0] || {};
            price = meta?.regularMarketPrice || meta?.previousClose || quotes?.close?.[quotes.close.length - 1] || 0;
            
            if (type !== 'price') {
              candles = timestamps.map((t: number, i: number) => ({
                time: t * 1000,
                open: quotes?.open?.[i] || 0,
                high: quotes?.high?.[i] || 0,
                low: quotes?.low?.[i] || 0,
                close: quotes?.close?.[i] || 0,
                volume: quotes?.volume?.[i] || 0
              })).filter((c: Candle) => c.close > 0);
            }
            source = 'yahoo';
          }
        }
      } catch (cryptoErr) {
        console.log('[AlpacaData] Yahoo fetch failed, using hardcoded:', cryptoErr);
      }
      
      // Fallback to hardcoded prices if Yahoo failed
      if (!price && cryptoPrices[symbol.toUpperCase()]) {
        price = cryptoPrices[symbol.toUpperCase()];
        console.log(`[AlpacaData] Using hardcoded price for ${symbol}: $${price}`);
        
        // Generate synthetic candles for hardcoded price
        if (type !== 'price') {
          const now = Date.now();
          for (let i = bars - 1; i >= 0; i--) {
            const variation = (Math.random() - 0.5) * 0.02; // ±1% variation
            const closePrice = price * (1 + variation);
            candles.push({
              time: now - (i * 60 * 60 * 1000), // hourly candles
              open: closePrice * (1 - variation * 0.5),
              high: closePrice * (1 + Math.abs(variation)),
              low: closePrice * (1 - Math.abs(variation)),
              close: closePrice,
              volume: Math.floor(Math.random() * 1000000)
            });
          }
        }
      }
      
      if (price) {
        if (type === 'price') {
          return new Response(JSON.stringify({
            symbol: symbol.toUpperCase(),
            price,
            timestamp: Date.now(),
            source
          }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' }});
        } else {
          return new Response(JSON.stringify({
            symbol: symbol.toUpperCase(),
            candles,
            count: candles.length,
            source
          }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' }});
        }
      }
    }

    // Fetch Alpaca credentials for stocks
    const { data: creds } = await supabase
      .from('broker_credentials')
      .select('credentials')
      .eq('user_id', user_id)
      .eq('broker', 'alpaca')
      .maybeSingle();

    if (!creds?.credentials?.apiKey || !creds?.credentials?.secretKey) {
      return new Response(JSON.stringify({ error: 'Alpaca credentials not found' }), {
        status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const { apiKey, secretKey } = creds.credentials;
    const alpacaSymbol = symbol.toUpperCase();

    // Map intervals to Alpaca format
    const alpacaTimeframe: Record<string, string> = {
      '1m': '1Min', '5m': '5Min', '15m': '15Min', '30m': '30Min',
      '1h': '1Hour', '4h': '4Hour', '1d': '1Day'
    };
    const timeframe = alpacaTimeframe[interval] || '1Hour';

    if (type === 'price') {
      // Get latest quote/snapshot
      const url = `https://data.alpaca.markets/v2/stocks/${alpacaSymbol}/snapshot`;
      const res = await fetch(url, {
        headers: {
          'APCA-API-KEY-ID': apiKey,
          'APCA-API-SECRET-KEY': secretKey,
        }
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Alpaca API error: ${res.status} - ${text}`);
      }

      const data = await res.json();
      const price = data?.latestTrade?.p || data?.quote?.ap || data?.quote?.bp || null;

      return new Response(JSON.stringify({ 
        symbol: alpacaSymbol, 
        price,
        timestamp: data?.latestTrade?.t,
        source: 'alpaca'
      }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' }});

    } else {
      // Get historical bars (candles)
      // Calculate start date based on bars needed
      const end = new Date().toISOString();
      const start = new Date(Date.now() - (bars * 24 * 60 * 60 * 1000)).toISOString(); // Conservative: request more days
      
      const url = `https://data.alpaca.markets/v2/stocks/${alpacaSymbol}/bars?timeframe=${timeframe}&start=${start}&end=${end}&limit=${bars}`;
      
      const res = await fetch(url, {
        headers: {
          'APCA-API-KEY-ID': apiKey,
          'APCA-API-SECRET-KEY': secretKey,
        }
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Alpaca API error: ${res.status} - ${text}`);
      }

      const data = await res.json();
      const barsData = data?.bars || [];

      const candles: Candle[] = barsData.map((b: any) => ({
        time: new Date(b.t).getTime(),
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
        volume: b.v
      }));

      return new Response(JSON.stringify({ 
        symbol: alpacaSymbol, 
        candles,
        count: candles.length,
        source: 'alpaca'
      }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' }});
    }

  } catch (err) {
    console.error('[AlpacaData] Error:', err);
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
