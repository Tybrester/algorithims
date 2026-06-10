/**
 * boof23-log-trade — Edge Function
 * Called by boof23_paper.py to insert/close trades in the trades table
 * Uses service role key so RLS is bypassed
 *
 * POST /boof23-log-trade
 * Body: { action: "open"|"close", symbol, entry_px, exit_px?, shares, order_id, trade_id?, pnl?, user_id, direction? }
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const body = await req.json();
    const { action, symbol, entry_px, exit_px, shares, order_id, trade_id, pnl, user_id, direction, bot_id } = body;

    if (!action || !user_id) {
      return new Response(JSON.stringify({ error: "Missing required fields" }), {
        status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    if (action === "open") {
      const { data, error } = await supabase.from("trades").insert({
        user_id,
        bot_id,
        symbol,
        action:      direction === "short" ? "sell" : "buy",
        direction:   direction === "short" ? "Short" : "Long",
        quantity:    shares,
        price:       entry_px,
        entry_price: entry_px,
        order_type:  "market",
        broker:      "paper",
        source:      "Boof 23 Paper",
        status:      "filled",
        filled_at:   new Date().toISOString(),
        created_at:  new Date().toISOString(),
      }).select("id").single();

      if (error) {
        console.error("[boof23-log] Insert error:", error.message);
        return new Response(JSON.stringify({ error: error.message }), {
          status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }

      return new Response(JSON.stringify({ ok: true, trade_id: data.id }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });

    } else if (action === "close") {
      if (!trade_id) {
        return new Response(JSON.stringify({ error: "trade_id required for close" }), {
          status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }

      const { error } = await supabase.from("trades").update({
        status:     "closed",
        exit_price: exit_px,
        pnl:        pnl,
        closed_at:  new Date().toISOString(),
      }).eq("id", trade_id);

      if (error) {
        console.error("[boof23-log] Close error:", error.message);
        return new Response(JSON.stringify({ error: error.message }), {
          status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }

      return new Response(JSON.stringify({ ok: true }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ error: "Unknown action" }), {
      status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" },
    });

  } catch (e) {
    console.error("[boof23-log] Error:", e);
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
