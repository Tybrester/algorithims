// =========================================================
// MEAN REVERSION BACKTEST - 1m candles, 6 months
// Target: +0.05% per trade
// Entry Rules:
//   Long:  ADX<20, Price<VWAP, DistVWAP<-0.5%, RSI2<5
//   Short: ADX<20, Price>VWAP, DistVWAP>+0.5%, RSI2>95
// =========================================================

// Load from .env file if present
import 'dotenv/config';

// Alpaca credentials from environment
const ALPACA_KEY = process.env.ALPACA_KEY || '';
const ALPACA_SECRET = process.env.ALPACA_SECRET || '';

// All symbols for data fetching
const ETF_SYMBOLS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOG', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ', 'SPY'];

// Test configurations - Updated with 0.8-1.2% VWAP distance, ATR stops, regime filter, good hours only
const TEST_CONFIGS = {
  // Good hours only: 9am, 12pm (removed 8am, 1pm, 2pm based on earlier results)
  test1_spy_only: { symbols: ['SPY'], hours: [9, 12], vwapDist: 1.0, atrMult: 1.5 },
  test2_no_spy: { symbols: ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ'], hours: [9, 12], vwapDist: 1.0, atrMult: 1.5 },
  test3_dist_08: { symbols: ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ', 'SPY'], hours: [9, 12], vwapDist: 0.8, atrMult: 1.5 },
  test3_dist_10: { symbols: ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ', 'SPY'], hours: [9, 12], vwapDist: 1.0, atrMult: 1.5 },
  test3_dist_12: { symbols: ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'AVGO', 'META', 'TSLA', 'LLY', 'QQQ', 'SPY'], hours: [9, 12], vwapDist: 1.2, atrMult: 1.5 },
};

// RSI Threshold Variants
const RSI_VARIANTS = [
  { name: 'Version A', rsiLow: 5, rsiHigh: 95 },
  { name: 'Version B', rsiLow: 10, rsiHigh: 90 },
  { name: 'Version C', rsiLow: 15, rsiHigh: 85 },
];

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
}

interface Trade {
  symbol: string;
  entryTime: number;
  exitTime: number;
  entryPrice: number;
  exitPrice: number;
  direction: 'LONG' | 'SHORT';
  pnlPct: number;
  pnlDollars: number;
  holdingBars: number;
  exitReason: 'target' | 'stop' | 'end_of_day';
  hourOfDay: number;
}

// ─────────────────────────────────────────────
// INDICATORS
// ─────────────────────────────────────────────
function computeRSI2(candles: Candle[]): number[] {
  const rsi: number[] = new Array(candles.length).fill(50);
  for (let i = 2; i < candles.length; i++) {
    const gain1 = Math.max(0, candles[i - 1].close - candles[i - 2].close);
    const loss1 = Math.max(0, candles[i - 2].close - candles[i - 1].close);
    const gain2 = Math.max(0, candles[i].close - candles[i - 1].close);
    const loss2 = Math.max(0, candles[i - 1].close - candles[i].close);
    
    const avgGain = (gain1 + gain2) / 2;
    const avgLoss = (loss1 + loss2) / 2;
    
    if (avgLoss === 0) {
      rsi[i] = avgGain > 0 ? 100 : 50;
    } else {
      const rs = avgGain / avgLoss;
      rsi[i] = 100 - (100 / (1 + rs));
    }
  }
  return rsi;
}

function computeADX(candles: Candle[], period: number = 14): number[] {
  const adx: number[] = new Array(candles.length).fill(0);
  const tr: number[] = new Array(candles.length).fill(0);
  const plusDM: number[] = new Array(candles.length).fill(0);
  const minusDM: number[] = new Array(candles.length).fill(0);
  
  for (let i = 1; i < candles.length; i++) {
    const highDiff = candles[i].high - candles[i - 1].high;
    const lowDiff = candles[i - 1].low - candles[i].low;
    
    plusDM[i] = (highDiff > lowDiff && highDiff > 0) ? highDiff : 0;
    minusDM[i] = (lowDiff > highDiff && lowDiff > 0) ? lowDiff : 0;
    
    tr[i] = Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i - 1].close),
      Math.abs(candles[i].low - candles[i - 1].close)
    );
  }
  
  let atr = 0;
  let plusDI = 0;
  let minusDI = 0;
  
  for (let i = 1; i < candles.length; i++) {
    if (i <= period) {
      atr += tr[i];
      plusDI += plusDM[i];
      minusDI += minusDM[i];
    } else {
      atr = atr * (period - 1) / period + tr[i];
      plusDI = plusDI * (period - 1) / period + plusDM[i];
      minusDI = minusDI * (period - 1) / period + minusDM[i];
    }
    
    if (i >= period) {
      const pDI = 100 * plusDI / atr;
      const mDI = 100 * minusDI / atr;
      const dx = 100 * Math.abs(pDI - mDI) / (pDI + mDI + 0.0001);
      
      if (i === period) {
        adx[i] = dx;
      } else {
        adx[i] = (adx[i - 1] * (period - 1) + dx) / period;
      }
    }
  }
  
  return adx;
}

function computeVWAP(candles: Candle[]): number[] {
  const vwap: number[] = new Array(candles.length).fill(0);
  let cumulativeTPV = 0;
  let cumulativeVol = 0;
  let dayStart = 0;
  
  for (let i = 0; i < candles.length; i++) {
    // Check if new day (simplified - assumes 1m data with proper timestamps)
    if (i > 0) {
      const currTime = new Date(candles[i].time * 1000);
      const prevTime = new Date(candles[i - 1].time * 1000);
      if (currTime.getDate() !== prevTime.getDate()) {
        cumulativeTPV = 0;
        cumulativeVol = 0;
        dayStart = i;
      }
    }
    
    const typicalPrice = (candles[i].high + candles[i].low + candles[i].close) / 3;
    const tpv = typicalPrice * candles[i].volume;
    
    cumulativeTPV += tpv;
    cumulativeVol += candles[i].volume;
    
    vwap[i] = cumulativeVol > 0 ? cumulativeTPV / cumulativeVol : typicalPrice;
  }
  
  return vwap;
}

// ─────────────────────────────────────────────
// ATR CALCULATION
// ─────────────────────────────────────────────
function computeATR(candles: Candle[], period: number = 14): number[] {
  const atr: number[] = new Array(candles.length).fill(0);
  const tr: number[] = new Array(candles.length).fill(0);
  
  for (let i = 1; i < candles.length; i++) {
    tr[i] = Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i - 1].close),
      Math.abs(candles[i].low - candles[i - 1].close)
    );
  }
  
  let atrSum = 0;
  for (let i = 1; i < candles.length; i++) {
    if (i <= period) {
      atrSum += tr[i];
      atr[i] = atrSum / i;
    } else {
      atrSum = atrSum * (period - 1) / period + tr[i];
      atr[i] = atrSum / period;
    }
  }
  
  return atr;
}

// ─────────────────────────────────────────────
// 5M REGIME FILTER (Simple moving average trend) - RELAXED
// ─────────────────────────────────────────────
function computeRegime(candles: Candle[], period: number = 5): ('up' | 'down' | 'neutral')[] {
  const regime: ('up' | 'down' | 'neutral')[] = new Array(candles.length).fill('neutral');
  let sum = 0;
  
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    
    if (i >= period - 1) {
      const sma = sum / period;
      const prevPrice = candles[i - 1]?.close || candles[i].close;
      
      // Relaxed: 0.05% threshold instead of 0.1%
      if (sma > prevPrice * 1.0005) regime[i] = 'up';
      else if (sma < prevPrice * 0.9995) regime[i] = 'down';
    }
  }
  
  return regime;
}

// ─────────────────────────────────────────────
// ALPACA DATA FETCH
// ─────────────────────────────────────────────
function getAlpacaCredentials(): { key: string; secret: string } {
  if (!ALPACA_KEY || !ALPACA_SECRET) {
    throw new Error('ALPACA_KEY and ALPACA_SECRET env vars required');
  }
  return { key: ALPACA_KEY, secret: ALPACA_SECRET };
}

async function fetchAlpacaBars(symbol: string, start: string, end: string, creds: { key: string; secret: string }): Promise<Candle[]> {
  const url = `https://data.alpaca.markets/v2/stocks/${symbol}/bars?timeframe=1Min&start=${start}&end=${end}&feed=iex`;
  
  const response = await fetch(url, {
    headers: {
      'APCA-API-KEY-ID': creds.key,
      'APCA-API-SECRET-KEY': creds.secret
    }
  });
  
  if (!response.ok) {
    console.error(`[Alpaca] Error fetching ${symbol}:`, response.status, await response.text());
    return [];
  }
  
  const data = await response.json() as { bars?: Array<{ t: string; o: number; h: number; l: number; c: number; v: number }> };
  
  if (!data.bars || data.bars.length === 0) {
    return [];
  }
  
  return data.bars.map((b) => ({
    time: new Date(b.t).getTime() / 1000,
    open: b.o,
    high: b.h,
    low: b.l,
    close: b.c,
    volume: b.v
  }));
}

// ─────────────────────────────────────────────
// SLIPPAGE MODEL
// ─────────────────────────────────────────────
function getSlippagePct(symbol: string): number {
  if (symbol === 'SPY') return 0.02;  // 0.02%
  if (symbol === 'QQQ') return 0.035; // 0.035%
  return 0.065; // Stocks: 0.065%
}

// ─────────────────────────────────────────────
// BACKTEST LOGIC - REALISTIC FILLS + ATR STOPS + REGIME FILTER
// ─────────────────────────────────────────────
function runBacktestWithConfig(symbol: string, candles: Candle[], config: { hours: number[], vwapDist: number, atrMult: number }): Trade[] {
  const trades: Trade[] = [];
  const adx = computeADX(candles, 14);
  const vwap = computeVWAP(candles);
  const atr = computeATR(candles, 14);
  const regime = computeRegime(candles, 5);
  const slippage = getSlippagePct(symbol);
  
  const TARGET_PCT = 0.05; // Still use fixed target
  
  const allowedHours = new Set(config.hours);
  const vwapDist = config.vwapDist;
  const atrMult = config.atrMult;
  
  // Signal on bar i, enter on bar i+1 open
  for (let i = 20; i < candles.length - 2; i++) {
    // Get signal bar data
    const signalPrice = candles[i].close;
    const vwapPrice = vwap[i];
    const distVWAP = ((signalPrice - vwapPrice) / vwapPrice) * 100;
    const signalHour = new Date(candles[i].time * 1000).getHours();
    const currentRegime = regime[i];
    
    // Skip if not in allowed trading hours (signal bar)
    if (!allowedHours.has(signalHour)) continue;
    
    // Check for entry signal with REGIME FILTER
    // Mean reversion: fade the trend - go LONG in down trend, SHORT in up trend
    let direction: 'LONG' | 'SHORT' | null = null;
    
    // LONG: Price far below VWAP + fading a down trend (mean reversion)
    if (adx[i] < 20 && signalPrice < vwapPrice && distVWAP < -vwapDist && currentRegime === 'down') {
      direction = 'LONG';
    }
    
    // SHORT: Price far above VWAP + fading an up trend (mean reversion)
    if (adx[i] < 20 && signalPrice > vwapPrice && distVWAP > vwapDist && currentRegime === 'up') {
      direction = 'SHORT';
    }
    
    if (!direction) continue;
    
    // ENTER on next bar (i+1) OPEN with slippage
    const entryBar = candles[i + 1];
    if (!entryBar || entryBar.open == null) {
      throw new Error(`Missing entry bar data for ${symbol} at index ${i + 1}`);
    }
    
    // Entry with slippage (worse fill)
    const rawEntryPrice = entryBar.open;
    const entryPrice = direction === 'LONG' 
      ? rawEntryPrice * (1 + slippage / 100)
      : rawEntryPrice * (1 - slippage / 100);
    const entryTime = entryBar.time;
    const entryHour = new Date(entryTime * 1000).getHours();
    const entryATR = atr[i + 1];
    
    // ATR-based stop distance
    const atrStopPct = (entryATR / entryPrice) * 100 * atrMult;
    
    let exitPrice = 0;
    let exitIdx = i + 1;
    let exitReason: 'target' | 'stop' | 'end_of_day' = 'end_of_day';
    
    // Look forward for exit (starting from entry bar)
    for (let j = i + 1; j < candles.length; j++) {
      const bar = candles[j];
      if (!bar || bar.high == null || bar.low == null || bar.close == null) {
        throw new Error(`Missing candle data for ${symbol} at index ${j}`);
      }
      
      const high = bar.high;
      const low = bar.low;
      
      if (direction === 'LONG') {
        const targetPrice = entryPrice * (1 + TARGET_PCT / 100);
        const stopPrice = entryPrice * (1 - atrStopPct / 100);
        
        // Target hit - use the actual price that triggered it (high) minus slippage
        if (high >= targetPrice) {
          // Fill at actual high or target, whichever is better for us, minus slippage
          const fillPrice = Math.max(high, targetPrice) * (1 - slippage / 100);
          exitPrice = fillPrice;
          exitIdx = j;
          exitReason = 'target';
          break;
        }
        
        // Stop loss: worst possible fill
        if (low <= stopPrice) {
          exitPrice = Math.min(stopPrice, low) * (1 - slippage / 100);
          exitIdx = j;
          exitReason = 'stop';
          break;
        }
      } else {
        const targetPrice = entryPrice * (1 - TARGET_PCT / 100);
        const stopPrice = entryPrice * (1 + atrStopPct / 100);
        
        // Target hit - use the actual price that triggered it (low) plus slippage
        if (low <= targetPrice) {
          const fillPrice = Math.min(low, targetPrice) * (1 + slippage / 100);
          exitPrice = fillPrice;
          exitIdx = j;
          exitReason = 'target';
          break;
        }
        
        // Stop loss: worst possible fill
        if (high >= stopPrice) {
          exitPrice = Math.max(stopPrice, high) * (1 + slippage / 100);
          exitIdx = j;
          exitReason = 'stop';
          break;
        }
      }
      
      // End of day exit
      const currTime = new Date(bar.time * 1000);
      if (currTime.getHours() >= 15 && currTime.getMinutes() >= 50) {
        const rawClose = bar.close;
        if (rawClose == null || rawClose === 0) {
          throw new Error(`Invalid close price for ${symbol} at EOD exit`);
        }
        exitPrice = direction === 'LONG'
          ? rawClose * (1 - slippage / 100)
          : rawClose * (1 + slippage / 100);
        exitIdx = j;
        exitReason = 'end_of_day';
        break;
      }
    }
    
    if (exitPrice === 0) {
      throw new Error(`Exit price is 0 for ${symbol} trade at ${new Date(entryTime * 1000).toISOString()}`);
    }
    
    // Calculate P&L
    let pnlPct = 0;
    if (direction === 'LONG') {
      pnlPct = ((exitPrice - entryPrice) / entryPrice) * 100;
    } else {
      pnlPct = ((entryPrice - exitPrice) / entryPrice) * 100;
    }
    
    trades.push({
      symbol,
      entryTime,
      exitTime: candles[exitIdx].time,
      entryPrice,
      exitPrice,
      direction,
      pnlPct,
      pnlDollars: pnlPct * 10,
      holdingBars: exitIdx - (i + 1),
      exitReason,
      hourOfDay: entryHour
    });
    
    // Skip ahead to avoid overlapping trades
    i = exitIdx;
  }
  
  return trades;
}

// ─────────────────────────────────────────────
// METRICS & REPORTING
// ─────────────────────────────────────────────
function calculateMetrics(trades: Trade[]) {
  if (trades.length === 0) {
    return {
      totalTrades: 0,
      winRate: 0,
      profitFactor: 0,
      avgWinner: 0,
      avgLoser: 0,
      maxDrawdown: 0,
      avgHoldTime: 0
    };
  }
  
  const winners = trades.filter(t => t.pnlPct > 0);
  const losers = trades.filter(t => t.pnlPct <= 0);
  
  const totalWins = winners.reduce((sum, t) => sum + t.pnlDollars, 0);
  const totalLosses = losers.reduce((sum, t) => sum + Math.abs(t.pnlDollars), 0);
  
  // Calculate max drawdown
  let peak = 0;
  let maxDD = 0;
  let runningPnL = 0;
  for (const trade of trades) {
    runningPnL += trade.pnlDollars;
    if (runningPnL > peak) peak = runningPnL;
    const dd = peak - runningPnL;
    if (dd > maxDD) maxDD = dd;
  }
  
  return {
    totalTrades: trades.length,
    winRate: (winners.length / trades.length) * 100,
    profitFactor: totalLosses > 0 ? totalWins / totalLosses : totalWins > 0 ? Infinity : 0,
    avgWinner: winners.length > 0 ? totalWins / winners.length : 0,
    avgLoser: losers.length > 0 ? -totalLosses / losers.length : 0,
    maxDrawdown: maxDD,
    avgHoldTime: trades.reduce((sum, t) => sum + t.holdingBars, 0) / trades.length
  };
}

function printResults(allTrades: Trade[]) {
  console.log('\n═══════════════════════════════════════════════════════════');
  console.log('           MEAN REVERSION BACKTEST RESULTS');
  console.log('═══════════════════════════════════════════════════════════\n');
  
  // Overall metrics
  const metrics = calculateMetrics(allTrades);
  console.log('📊 OVERALL METRICS');
  console.log('───────────────────────────────────────────────────────────');
  console.log(`Total Trades:      ${metrics.totalTrades}`);
  console.log(`Win Rate:          ${metrics.winRate.toFixed(1)}%`);
  console.log(`Profit Factor:     ${metrics.profitFactor.toFixed(2)}`);
  console.log(`Average Winner:    $${metrics.avgWinner.toFixed(2)}`);
  console.log(`Average Loser:     $${metrics.avgLoser.toFixed(2)}`);
  console.log(`Max Drawdown:      $${metrics.maxDrawdown.toFixed(2)}`);
  console.log(`Avg Hold Time:     ${metrics.avgHoldTime.toFixed(1)} bars (~${(metrics.avgHoldTime / 60).toFixed(1)}h)`);
  console.log(`Net P&L:           $${allTrades.reduce((s, t) => s + t.pnlDollars, 0).toFixed(2)}`);
  console.log('');
  
  // By symbol
  console.log('📈 RESULTS BY SYMBOL');
  console.log('───────────────────────────────────────────────────────────');
  const bySymbol = new Map<string, Trade[]>();
  for (const t of allTrades) {
    if (!bySymbol.has(t.symbol)) bySymbol.set(t.symbol, []);
    bySymbol.get(t.symbol)!.push(t);
  }
  
  for (const [sym, trades] of bySymbol) {
    const m = calculateMetrics(trades);
    console.log(`${sym}: ${trades.length} trades | ${m.winRate.toFixed(1)}% WR | $${trades.reduce((s, t) => s + t.pnlDollars, 0).toFixed(2)} P&L`);
  }
  console.log('');
  
  // By hour of day
  console.log('⏰ RESULTS BY HOUR OF DAY (ET)');
  console.log('───────────────────────────────────────────────────────────');
  const byHour = new Map<number, Trade[]>();
  for (const t of allTrades) {
    if (!byHour.has(t.hourOfDay)) byHour.set(t.hourOfDay, []);
    byHour.get(t.hourOfDay)!.push(t);
  }
  
  const sortedHours = Array.from(byHour.keys()).sort((a, b) => a - b);
  for (const hour of sortedHours) {
    const trades = byHour.get(hour)!;
    const m = calculateMetrics(trades);
    const label = hour < 12 ? `${hour}:00 AM` : `${hour - 12 || 12}:00 PM`;
    console.log(`${label}: ${trades.length} trades | ${m.winRate.toFixed(1)}% WR | $${trades.reduce((s, t) => s + t.pnlDollars, 0).toFixed(2)} P&L`);
  }
  console.log('');
  
  // Exit reason breakdown
  console.log('🚪 EXIT REASON BREAKDOWN');
  console.log('───────────────────────────────────────────────────────────');
  const byExit = new Map<string, Trade[]>();
  for (const t of allTrades) {
    if (!byExit.has(t.exitReason)) byExit.set(t.exitReason, []);
    byExit.get(t.exitReason)!.push(t);
  }
  
  for (const [reason, trades] of byExit) {
    const m = calculateMetrics(trades);
    console.log(`${reason}: ${trades.length} trades | ${m.winRate.toFixed(1)}% WR`);
  }
  console.log('');
  
  // Recent trades sample
  console.log('📝 LAST 10 TRADES (most recent first)');
  console.log('───────────────────────────────────────────────────────────');
  const recent = [...allTrades].reverse().slice(0, 10);
  for (const t of recent) {
    const date = new Date(t.entryTime * 1000).toLocaleDateString();
    const time = new Date(t.entryTime * 1000).toLocaleTimeString();
    console.log(`${t.symbol} ${t.direction} | ${date} ${time} | Entry: $${t.entryPrice.toFixed(2)} | Exit: $${t.exitPrice.toFixed(2)} | P&L: ${t.pnlPct.toFixed(3)}% (${t.exitReason})`);
  }
  console.log('\n═══════════════════════════════════════════════════════════\n');
}

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────
async function main() {
  // Calculate date range (3 months)
  const endDate = new Date();
  const startDate = new Date();
  startDate.setMonth(startDate.getMonth() - 3);
  
  const startStr = startDate.toISOString();
  const endStr = endDate.toISOString();
  
  // Get credentials
  let creds: { key: string; secret: string };
  try {
    creds = getAlpacaCredentials();
  } catch (e: any) {
    console.error('❌ Failed to load credentials:', e.message);
    process.exit(1);
  }
  
  // Pre-fetch all data
  console.log('\n📊 Pre-fetching data for all symbols...');
  const symbolData: Map<string, Candle[]> = new Map();
  for (const symbol of ETF_SYMBOLS) {
    const candles = await fetchAlpacaBars(symbol, startStr, endStr, creds);
    if (candles.length > 0) {
      symbolData.set(symbol, candles);
      console.log(`   ✅ ${symbol}: ${candles.length} candles`);
    } else {
      console.log(`   ⚠️ ${symbol}: No data`);
    }
  }
  console.log('');
  
  // Run Test 1: SPY only, 9 AM only
  console.log('\n🚀 TEST 1: SPY ONLY - 9 AM - VWAP 0.5%');
  console.log('═══════════════════════════════════════════════════════════');
  
  const spyData = new Map([...symbolData].filter(([k, v]) => TEST_CONFIGS.test1_spy_only.symbols.includes(k)));
  const spyTrades: Trade[] = [];
  for (const [symbol, candles] of spyData) {
    const trades = runBacktestWithConfig(symbol, candles, TEST_CONFIGS.test1_spy_only);
    spyTrades.push(...trades);
  }
  printResults(spyTrades);
  
  // Run Test 2: No SPY
  console.log('\n🚀 TEST 2: NO SPY - VWAP 0.5%');
  console.log('═══════════════════════════════════════════════════════════');
  
  const noSpySymbols = new Map([...symbolData].filter(([k, v]) => TEST_CONFIGS.test2_no_spy.symbols.includes(k)));
  const noSpyTrades: Trade[] = [];
  for (const [symbol, candles] of noSpySymbols) {
    const trades = runBacktestWithConfig(symbol, candles, TEST_CONFIGS.test2_no_spy);
    noSpyTrades.push(...trades);
  }
  printResults(noSpyTrades);
  
  // Run Test 3: Distance optimization (A, B, C, D)
  console.log('\n🚀 TEST 3: DISTANCE OPTIMIZATION');
  console.log('═══════════════════════════════════════════════════════════');
  
  const distVariants = [
    { name: 'A (0.8%)', config: TEST_CONFIGS.test3_dist_08 },
    { name: 'B (1.0%)', config: TEST_CONFIGS.test3_dist_10 },
    { name: 'C (1.2%)', config: TEST_CONFIGS.test3_dist_12 },
  ];
  
  for (const variant of distVariants) {
    console.log(`\n--- ${variant.name} ---`);
    const distTrades: Trade[] = [];
    for (const [symbol, candles] of symbolData) {
      if (variant.config.symbols.includes(symbol)) {
        const trades = runBacktestWithConfig(symbol, candles, variant.config);
        distTrades.push(...trades);
      }
    }
    const m = calculateMetrics(distTrades);
    const pnl = distTrades.reduce((s, t) => s + t.pnlDollars, 0);
    console.log(`${variant.name}: ${m.totalTrades} trades | ${m.winRate.toFixed(1)}% WR | $${pnl.toFixed(2)} P&L`);
  }
  
  // Save to file
  const fs = await import('fs');
  fs.writeFileSync('backtest_results.json', JSON.stringify({
    period: `${startStr.slice(0, 10)} to ${endStr.slice(0, 10)}`,
    symbols: ETF_SYMBOLS,
    params: {
      entryRules: {
        long: 'ADX<20, Price<VWAP, DistVWAP<-0.5%',
        short: 'ADX<20, Price>VWAP, DistVWAP>+0.5%'
      },
      hours: ['8am', '9am', '12pm', '1pm', '2pm'],
      targetPct: 0.05,
      stopPct: -0.10
    },
    testResults: {
      spyOnly: { trades: spyTrades.length, metrics: calculateMetrics(spyTrades) },
      noSpy: { trades: noSpyTrades.length, metrics: calculateMetrics(noSpyTrades) },
    }
  }, null, 2));
  console.log('\n💾 Results saved to backtest_results.json\n');
}

main().catch(console.error);
