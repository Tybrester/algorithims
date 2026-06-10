const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

const futuresMap: Record<string, string> = {
  'CL1!': 'CL=F', 'ES1!': 'ES=F', 'NQ1!': 'NQ=F', 'GC1!': 'GC=F',
  'SI1!': 'SI=F', 'NG1!': 'NG=F', 'ZB1!': 'ZB=F', 'ZN1!': 'ZN=F',
  'YM1!': 'YM=F', 'RTY1!': 'RTY=F', 'MES1!': 'MES=F', 'MNQ1!': 'MNQ=F',
};

function normalizeSymbol(symbol: string): string {
  let s = symbol.includes(':') ? symbol.split(':')[1] : symbol;
  if (futuresMap[s]) return futuresMap[s];
  if (s.endsWith('!')) s = s.replace('!', '=F');
  if (s.endsWith('USDT')) s = s.replace('USDT', '-USD');
  return s;
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const url = new URL(req.url);
    const symbol   = url.searchParams.get('symbol');
    const interval = url.searchParams.get('interval') || '5m';
    const count    = parseInt(url.searchParams.get('count') || '500');

    if (!symbol) return new Response(JSON.stringify({ error: 'symbol required' }), {
      status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

    const ticker = normalizeSymbol(symbol);

    const rangeMap: Record<string, string> = {
      '1m': '60d', '5m': '60d', '15m': '60d', '30m': '60d', '1h': '730d', '1d': '5y'
    };
    const range = rangeMap[interval] || '60d';

    const yahooUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=${interval}&range=${range}`;
    const res = await fetch(yahooUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (!res.ok) throw new Error(`Yahoo returned ${res.status}`);

    const json = await res.json();
    const result = json?.chart?.result?.[0];
    if (!result) throw new Error('No data for ' + ticker);

    const timestamps: number[] = result.timestamp || [];
    const q = result.indicators?.quote?.[0] || {};
    const candles = [];
    for (let i = 0; i < timestamps.length; i++) {
      if (q.open[i]==null||q.high[i]==null||q.low[i]==null||q.close[i]==null) continue;
      candles.push({
        time:   timestamps[i],
        open:   q.open[i],
        high:   q.high[i],
        low:    q.low[i],
        close:  q.close[i],
        volume: q.volume?.[i] || 0,
      });
    }

    const trimmed = candles.slice(-count);

    return new Response(JSON.stringify({ candles: trimmed, ticker, count: trimmed.length }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err), candles: [] }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
