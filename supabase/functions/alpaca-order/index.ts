import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    const cl = Number(req.headers.get('content-length') || 0);
    if (cl > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    const raw = await req.text();
    if (raw.length > 8192) return new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    let parsed: any;
    try { parsed = JSON.parse(raw); } catch { return new Response(JSON.stringify({ error: 'Invalid JSON' }), { status: 422, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }); }
    const user_id    = typeof parsed.user_id === 'string' ? parsed.user_id.trim().slice(0, 64) : '';
    const symbol     = typeof parsed.symbol === 'string' ? parsed.symbol.toUpperCase().replace(/[^A-Z0-9./:!-]/g, '').slice(0, 20) : '';
    const side       = typeof parsed.side === 'string' && ['buy','sell'].includes(parsed.side.toLowerCase()) ? parsed.side.toLowerCase() : '';
    const order_type = typeof parsed.order_type === 'string' ? parsed.order_type.toLowerCase() : 'market';
    const qty        = parsed.qty != null ? Number(parsed.qty) : null;
    const notional   = parsed.notional != null ? Number(parsed.notional) : null;
    const limit_price = parsed.limit_price != null ? Number(parsed.limit_price) : null;
    if (!user_id || !symbol || !side) {
      return new Response(JSON.stringify({ error: 'user_id, symbol, side are required' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    if (!/^[0-9a-f-]{36}$/i.test(user_id)) return new Response(JSON.stringify({ error: 'Invalid user_id' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    if (qty !== null && (isNaN(qty) || qty <= 0 || qty > 100000)) return new Response(JSON.stringify({ error: 'Invalid qty' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    if (notional !== null && (isNaN(notional) || notional <= 0 || notional > 1000000)) return new Response(JSON.stringify({ error: 'Invalid notional' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    // Fetch Alpaca credentials
    const { data: creds } = await supabase
      .from('broker_credentials')
      .select('credentials')
      .eq('user_id', user_id)
      .eq('broker', 'alpaca')
      .maybeSingle();

    if (!creds) {
      return new Response(JSON.stringify({ error: 'No Alpaca credentials found' }), {
        status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const { api_key, secret_key, env } = creds.credentials;
    const baseUrl = env === 'live'
      ? 'https://api.alpaca.markets'
      : 'https://paper-api.alpaca.markets';

    // Build order — use notional (dollar amount) if no qty specified
    const isLimit = order_type === 'limit' && limit_price;
    const orderBody: Record<string, unknown> = {
      symbol: symbol.toUpperCase(),
      side,           // 'buy' or 'sell'
      type: isLimit ? 'limit' : 'market',
      time_in_force: 'day',
    };

    if (isLimit) {
      orderBody.limit_price = String(limit_price);
    }

    if (qty) {
      orderBody.qty = String(qty);
    } else if (notional) {
      orderBody.notional = String(notional);
    } else {
      return new Response(JSON.stringify({ error: 'qty or notional required' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const res = await fetch(`${baseUrl}/v2/orders`, {
      method: 'POST',
      headers: {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(orderBody),
    });

    const order = await res.json();

    if (!res.ok) {
      return new Response(JSON.stringify({ error: order.message || 'Alpaca order failed', detail: order }), {
        status: res.status, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    return new Response(JSON.stringify({ success: true, order_id: order.id, status: order.status, order }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
