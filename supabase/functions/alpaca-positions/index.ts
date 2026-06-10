// Fetch Alpaca positions with real P&L for UI display
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'GET, OPTIONS'
};

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  try {
    const url = new URL(req.url);
    const userId = url.searchParams.get('user_id');
    if (!userId) {
      return new Response(JSON.stringify({ error: 'user_id required' }), {
        status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    // Get Alpaca credentials
    const { data: creds } = await supabase
      .from('broker_credentials')
      .select('credentials')
      .eq('user_id', userId)
      .eq('broker', 'alpaca')
      .maybeSingle();

    if (!creds?.credentials?.api_key) {
      return new Response(JSON.stringify({ error: 'No Alpaca credentials' }), {
        status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const { api_key, secret_key } = creds.credentials;

    // Fetch positions from Alpaca
    const positionsRes = await fetch('https://api.alpaca.markets/v2/positions', {
      headers: {
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key
      }
    });

    if (!positionsRes.ok) {
      const err = await positionsRes.text();
      return new Response(JSON.stringify({ error: `Alpaca API error: ${err}` }), {
        status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const positions = await positionsRes.json();

    // Filter options positions and format for UI
    const optionsPositions = positions
      .filter((p: any) => p.asset_class === 'option' || /\d{6}[CP]\d{8}/.test(p.symbol))
      .map((p: any) => ({
        symbol: p.symbol,
        underlying: p.symbol.replace(/\d{6}[CP]\d{8}/, ''), // Extract underlying
        qty: Number(p.qty),
        avg_entry_price: Number(p.avg_entry_price),
        current_price: Number(p.current_price),
        market_value: Number(p.market_value),
        unrealized_pl: Number(p.unrealized_pl),
        unrealized_plpc: Number(p.unrealized_plpc) * 100, // Convert to percentage
        change_today: Number(p.change_today),
        cost_basis: Number(p.cost_basis),
        lastday_price: Number(p.lastday_price)
      }));

    // Calculate totals
    const totalUnrealizedPL = optionsPositions.reduce((sum: number, p: any) => sum + p.unrealized_pl, 0);
    const totalMarketValue = optionsPositions.reduce((sum: number, p: any) => sum + p.market_value, 0);

    return new Response(JSON.stringify({
      positions: optionsPositions,
      summary: {
        total_positions: optionsPositions.length,
        total_unrealized_pl: totalUnrealizedPL,
        total_market_value: totalMarketValue,
        total_cost_basis: optionsPositions.reduce((sum: number, p: any) => sum + p.cost_basis, 0)
      },
      fetched_at: new Date().toISOString()
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
