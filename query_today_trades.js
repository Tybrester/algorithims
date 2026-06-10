// Query today's chop vs trend trades for 22.5/23.5 bots
const SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co";
const SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0";

async function queryToday() {
  const today = new Date().toISOString().split('T')[0];
  
  // Get bot IDs for 22.5 / 23.5
  const botUrl = `${SUPABASE_URL}/rest/v1/options_bots?select=id,name,bot_signal&or=(bot_signal.eq.boof22_5,bot_signal.eq.boof23_5)`;
  const botResp = await fetch(botUrl, {
    headers: { 'apikey': SUPABASE_KEY, 'Authorization': `Bearer ${SUPABASE_KEY}` }
  });
  const bots = await botResp.json();
  
  if (!bots || bots.length === 0) {
    console.log("No boof22_5 or boof23_5 bots found.");
    return;
  }
  
  const botIds = bots.map(b => b.id).join(',');
  
  // Query trades for these bots today
  const tradesUrl = `${SUPABASE_URL}/rest/v1/options_trades?select=symbol,pnl,status,entry_reason,exit_reason,created_at,mode&bot_id=in.(${botIds})&created_at=gte.${today}T00:00:00Z&order=created_at.desc`;
  const tradesResp = await fetch(tradesUrl, {
    headers: { 'apikey': SUPABASE_KEY, 'Authorization': `Bearer ${SUPABASE_KEY}` }
  });
  const trades = await tradesResp.json();
  
  console.log(`=== Today's Trades (${today}) for .5 Bots ===\n`);
  console.log(`Bots: ${bots.map(b => `${b.name} (${b.bot_signal})`).join(', ')}\n`);
  console.log(`Total trades today: ${trades.length}\n`);
  
  // Group by mode
  const chopTrades = [];
  const trendTrades = [];
  const unknownTrades = [];
  
  for (const t of trades) {
    const mode = t.mode;
    const entryReason = (t.entry_reason || '').toUpperCase();
    
    if (mode === 'chop' || entryReason.includes('CHOP')) {
      chopTrades.push(t);
    } else if (mode === 'trend') {
      trendTrades.push(t);
    } else {
      unknownTrades.push(t);
    }
  }
  
  // Summary
  console.log(`Chop trades:  ${chopTrades.length}`);
  console.log(`Trend trades: ${trendTrades.length}`);
  console.log(`Unknown:      ${unknownTrades.length}\n`);
  
  // P&L breakdown
  const chopPnl = chopTrades.reduce((s, t) => s + (t.pnl || 0), 0);
  const trendPnl = trendTrades.reduce((s, t) => s + (t.pnl || 0), 0);
  const totalPnl = chopPnl + trendPnl;
  
  console.log(`Chop P&L:  $${chopPnl.toFixed(2)}`);
  console.log(`Trend P&L: $${trendPnl.toFixed(2)}`);
  console.log(`Total P&L: $${totalPnl.toFixed(2)}\n`);
  
  // Detail chop trades
  if (chopTrades.length > 0) {
    console.log("--- CHOP TRADES ---");
    for (const t of chopTrades) {
      const sym = t.symbol || '?';
      const pnl = t.pnl || 0;
      const status = t.status || '?';
      const reason = (t.entry_reason || '').substring(0, 40);
      const created = t.created_at ? t.created_at.substring(11, 19) : '?';
      console.log(`  ${created} | ${sym.padEnd(6)} | ${status.padEnd(8)} | $${pnl.toFixed(2).padStart(7)} | ${reason}`);
    }
    console.log();
  }
  
  // Detail trend trades
  if (trendTrades.length > 0) {
    console.log("--- TREND TRADES ---");
    for (const t of trendTrades) {
      const sym = t.symbol || '?';
      const pnl = t.pnl || 0;
      const status = t.status || '?';
      const reason = (t.entry_reason || '').substring(0, 40);
      const created = t.created_at ? t.created_at.substring(11, 19) : '?';
      console.log(`  ${created} | ${sym.padEnd(6)} | ${status.padEnd(8)} | $${pnl.toFixed(2).padStart(7)} | ${reason}`);
    }
    console.log();
  }
  
  if (unknownTrades.length > 0) {
    console.log(`--- UNKNOWN (${unknownTrades.length}) ---`);
    for (const t of unknownTrades.slice(0, 5)) {
      const sym = t.symbol || '?';
      const pnl = t.pnl || 0;
      const status = t.status || '?';
      const reason = (t.entry_reason || '').substring(0, 40);
      const created = t.created_at ? t.created_at.substring(11, 19) : '?';
      console.log(`  ${created} | ${sym.padEnd(6)} | ${status.padEnd(8)} | $${pnl.toFixed(2).padStart(7)} | ${reason}`);
    }
    console.log();
  }
}

queryToday().catch(err => console.error('Error:', err));
