import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': 'https://boofcapital.com', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

// ─────────────────────────────────────────────
// BOOF 15.0 - CONTINUOUS EV ESTIMATOR
// ─────────────────────────────────────────────

// Symbol multipliers derived from backtest results
const SYMBOL_MULTIPLIER: Record<string, number> = {
  'AMD': 1.25,
  'TSLA': 1.10,
  'SPY': 1.00,
  'QQQ': 0.85,
  'NVDA': 1.15,
  'default': 1.00
};

// Regime multipliers
const REGIME_MULTIPLIER: Record<string, number> = {
  'EXPANSION': 1.1,
  'NORMAL': 0.8,  // CHOP
  'COMPRESSION': 0.9,
  'default': 1.0
};

// Session multipliers (time-of-day adjustments)
const SESSION_MULTIPLIER: Record<string, Record<string, number>> = {
  'SPY': {
    'OPEN': 1.2,
    'MID': 0.9,
    'CLOSE': 1.0
  },
  'QQQ': {
    'OPEN': 1.3,
    'MID': 0.7,
    'CLOSE': 0.9
  },
  'TSLA': {
    'OPEN': 1.1,
    'MID': 1.0,
    'CLOSE': 1.1
  },
  'AMD': {
    'OPEN': 1.25,
    'MID': 1.05,
    'CLOSE': 1.15
  },
  'NVDA': {
    'OPEN': 1.2,
    'MID': 1.0,
    'CLOSE': 1.1
  }
};

// Risk Management: Symbol-aware TP adjustments
const SYMBOL_TP_MULTIPLIER: Record<string, number> = {
  // Stocks
  'AMD': 1.2,
  'TSLA': 1.0,
  'SPY': 0.9,
  'QQQ': 0.8,
  'NVDA': 1.0,
  // Crypto (higher volatility = tighter TP)
  'BTC': 0.7,
  'ETH': 0.75,
  'SOL': 0.8,
  'XRP': 0.85,
  'DOGE': 0.9,
  'default': 1.0
};

/**
 * Determine trading session from timestamp
 * OPEN: 9:30-10:30, MID: 10:30-14:00, CLOSE: 14:00-16:00
 */
function getSession(timestamp: Date): string {
  const hours = timestamp.getHours();
  const minutes = timestamp.getMinutes();
  const timeInMinutes = hours * 60 + minutes;

  const openStart = 9 * 60 + 30;  // 9:30
  const openEnd = 10 * 60 + 30;   // 10:30
  const midEnd = 14 * 60;          // 14:00

  if (timeInMinutes >= openStart && timeInMinutes < openEnd) {
    return 'OPEN';
  } else if (timeInMinutes >= openEnd && timeInMinutes < midEnd) {
    return 'MID';
  } else {
    return 'CLOSE';
  }
}

/**
 * Map EV to TP multiplier (reward: risk ratio)
 * EV < 0.05: 1.2R (weak edge, quick exit)
 * EV < 0.15: 1.5R (moderate edge)
 * EV >= 0.15: 2.0R (strong edge, let it run)
 */
function calculateTPMultiplier(ev: number): number {
  if (ev < 0.05) {
    return 1.2;
  } else if (ev < 0.15) {
    return 1.5;
  } else {
    return 2.0;
  }
}

/**
 * Calculate ATR-based stop loss and EV-based take profit
 *
 * Args:
 *   symbol: Trading symbol
 *   ev: Expected value from continuous estimator
 *   atrValue: Current ATR value
 *
 * Returns:
 *   slDistance: Stop loss distance in price units (0.8 * ATR)
 *   tpDistance: Take profit distance in price units (EV-based * symbol adjustment)
 */
function calculateRiskParameters(symbol: string, ev: number, atrValue: number): { slDistance: number; tpDistance: number } {
  // Step 1: ATR-based stop loss
  const slDistance = 0.8 * atrValue;

  // Step 2: EV → TP multiplier
  const tpMultiplier = calculateTPMultiplier(ev);

  // Step 3: Symbol-aware adjustment
  const symbolTPMult = SYMBOL_TP_MULTIPLIER[symbol] || SYMBOL_TP_MULTIPLIER['default'];

  // Final TP distance
  const tpDistance = slDistance * tpMultiplier * symbolTPMult;

  return { slDistance, tpDistance };
}

/**
 * Compute continuous EV from score, symbol, regime, volatility, and session
 * EV = base_ev(score) * symbol_multiplier(symbol) * session_multiplier(symbol, session) * regime_multiplier(regime) * volatility_adjustment(atr_state)
 */
function computeContinuousEV(
  symbol: string,
  score: number,
  regime: string,
  atrPercentile: number = 0.5,
  session: string = 'MID'
): number {
  // Base EV from score
  const baseEV = (score - 3.0) * 0.08;

  // Symbol multiplier
  const symMult = SYMBOL_MULTIPLIER[symbol] || SYMBOL_MULTIPLIER['default'];

  // Session multiplier
  const sessionMults = SESSION_MULTIPLIER[symbol] || { 'OPEN': 1.0, 'MID': 1.0, 'CLOSE': 1.0 };
  const sessMult = sessionMults[session] || 1.0;

  // Regime multiplier
  const regMult = REGIME_MULTIPLIER[regime] || REGIME_MULTIPLIER['default'];

  // Volatility adjustment
  let volAdj = 1.0;
  if (atrPercentile > 0.7) {
    volAdj = 0.9;  // High volatility - slight reduction
  } else if (atrPercentile < 0.3) {
    volAdj = 1.1;  // Low volatility - slight boost
  }

  // Final EV
  const ev = baseEV * symMult * sessMult * regMult * volAdj;

  return ev;
}

/**
 * Calculate position size based on EV and volatility
 * size = base_size * min(ev * 5, 2.0) * (1 / (1 + volatility * 0.5))
 */
function calculatePositionSize(
  ev: number,
  volatility: number,
  baseSize: number = 1.0
): number {
  // Higher EV = larger size (capped at 2x)
  const evFactor = Math.min(ev * 5, 2.0);

  // Higher volatility = smaller size
  const volFactor = 1.0 / (1.0 + volatility * 0.5);

  const adjustedSize = baseSize * evFactor * volFactor;

  return Math.max(adjustedSize, 0.1);  // Minimum 10% of base
}

/**
 * Calculate regime from price data (simplified version)
 */
function classifyRegime(closes: number[]): string {
  if (closes.length < 20) return 'NORMAL';

  const recent = closes.slice(-20);
  const earlier = closes.slice(-40, -20);

  const recentVol = recent.reduce((sum, val) => sum + Math.abs(val - recent[0]), 0) / recent.length;
  const earlierVol = earlier.reduce((sum, val) => sum + Math.abs(val - earlier[0]), 0) / earlier.length;

  const ratio = recentVol / earlierVol;

  if (ratio > 1.1) return 'EXPANSION';
  if (ratio < 0.9) return 'COMPRESSION';
  return 'NORMAL';
}

/**
 * Calculate ATR percentile for volatility adjustment
 */
function calculateATRPercentile(atrValues: number[], currentATR: number): number {
  if (atrValues.length === 0) return 0.5;

  const sorted = [...atrValues].sort((a, b) => a - b);
  const rank = sorted.filter(v => v < currentATR).length;
  return rank / sorted.length;
}

/**
 * Boof 15.0 Signal Generator with EV-based entries
 * Features: score → symbol context → EV → position size → trade
 */
function generateSignalBoof15(
  candles: Candle[],
  tradeDirection = 'both',
  symbol = 'SPY'
): SignalResult {
  const n = candles.length;
  if (n < 30) {
    return {
      signal: 'none',
      price: candles[n - 1]?.close || 0,
      trend: 0,
      ema: 0,
      adx: 0,
      reason: 'Boof 15.0: insufficient data (need 30+ candles)'
    };
  }

  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume);

  // Calculate indicators
  const ema9 = calcEMA(closes, 9);
  const ema20 = calcEMA(closes, 20);
  const atr = calcATR(highs, lows, closes, 14);

  // Calculate VWAP (simplified)
  const typicalPrice = closes.map((c, i) => (c + highs[i] + lows[i]) / 3);
  const cumTP = typicalPrice.reduce((sum, val) => sum + (val || 0), 0);
  const cumVol = volumes.reduce((sum, val) => sum + (val || 0), 0);
  const vwap = cumVol > 0 ? cumTP / cumVol : closes[n - 1];

  // Calculate relative volume
  const recentVol = volumes.slice(-20);
  const avgVol = recentVol.length > 0 ? recentVol.reduce((sum, val) => sum + (val || 0), 0) / recentVol.length : 1;
  const rvol = avgVol > 0 ? volumes[n - 1] / avgVol : 1;

  // Calculate regime
  const regime = classifyRegime(closes);

  // Calculate ATR percentile
  const atrPercentile = calculateATRPercentile(atr.slice(-20), atr[n - 1]);

  // Calculate score
  const lookback = 10;
  const i = n - 1;
  const window = candles.slice(i - lookback, i);
  const rangeHigh = Math.max(...window.map(c => c.high));
  const rangeLow = Math.min(...window.map(c => c.low));

  let score = 0;

  // SCORE 1: ATR rising
  const atrSeries = atr.slice(i - 20, i);
  const atrAvg = atrSeries.reduce((sum, val) => sum + val, 0) / atrSeries.length;
  const atrCurrent = atr[i];
  if (atrCurrent > atrAvg * 1.02) score += 1;

  // SCORE 1: ATR compression (relative percentile)
  if (atrPercentile < 0.4) score += 1;

  // SCORE 1: Clean consolidation
  const recentRanges: number[] = [];
  for (let j = i - lookback - 5; j < i - lookback; j++) {
    if (j >= lookback) {
      const pastWindow = candles.slice(j - lookback, j);
      recentRanges.push(
        Math.max(...pastWindow.map(c => c.high)) - Math.min(...pastWindow.map(c => c.low))
      );
    }
  }
  const avgRecentRange = recentRanges.length > 0
    ? recentRanges.reduce((sum, val) => sum + val, 0) / recentRanges.length
    : rangeHigh - rangeLow;
  if (rangeHigh - rangeLow < avgRecentRange * 1.3) score += 1;

  // SCORE 1: Time-of-day filter (simplified - assume always valid for now)
  score += 1;

  // Check breakout conditions
  const curClose = closes[i];
  const longBreakout = curClose > rangeHigh;
  const shortBreakout = curClose < rangeLow;

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = '';

  if (longBreakout) {
    // Base entry conditions
    const longEntry = curClose > vwap && ema9[i] > ema20[i] && rvol > 1.3;

    if (longEntry) {
      // SCORE 2: First impulse confirmation
      let impulseScore = 0;
      if (i + 2 < n) {
        if (closes[i + 1] > curClose) impulseScore += 1;
        if (closes[i + 2] > closes[i + 1]) impulseScore += 1;
      }
      score += impulseScore;

  // Compute EV with session
      const session = getSession(new Date(candles[n - 1].time));
      const ev = computeContinuousEV(symbol, score, regime, atrPercentile, session);

      if (ev > 0) {
        signal = 'buy';
        reason = `Boof 15.0: LONG | score=${score.toFixed(1)} EV=${ev.toFixed(3)} regime=${regime}`;

        // Calculate dynamic risk parameters
        const { slDistance, tpDistance } = calculateRiskParameters(symbol, ev, atrCurrent);
        const stopLoss = curClose - slDistance;
        const takeProfit = curClose + tpDistance;

        // Store in local variables for final return
        const resultSignal: 'buy' | 'sell' | 'none' = 'buy';
        const resultPrice = curClose;
        const resultTrend = 0;
        const resultEma = ema9[i];
        const resultAdx = 0;
        const resultReason = reason;
        const resultRegime = regime;
        const resultEv = ev;
        const resultStopLoss = stopLoss;
        const resultTakeProfit = takeProfit;

        // Apply trade direction filter
        if (tradeDirection === 'short') {
          return {
            signal: 'none',
            price: resultPrice,
            trend: resultTrend,
            ema: resultEma,
            adx: resultAdx,
            reason: resultReason + ' (filtered by direction)'
          };
        }

        return {
          signal: resultSignal,
          price: resultPrice,
          trend: resultTrend,
          ema: resultEma,
          adx: resultAdx,
          reason: resultReason,
          regime: resultRegime,
          ev: resultEv,
          stopLoss: resultStopLoss,
          takeProfit: resultTakeProfit
        };
      } else {
        reason = `Boof 15.0: LONG skipped | score=${score.toFixed(1)} EV=${ev.toFixed(3)} <= 0`;
      }
    }
  } else if (shortBreakout) {
    // Base entry conditions
    const shortEntry = curClose < vwap && ema9[i] < ema20[i] && rvol > 1.3;

    if (shortEntry) {
      // SCORE 2: First impulse confirmation
      let impulseScore = 0;
      if (i + 2 < n) {
        if (closes[i + 1] < curClose) impulseScore += 1;
        if (closes[i + 2] < closes[i + 1]) impulseScore += 1;
      }
      score += impulseScore;

      // Compute EV with session
      const session = getSession(new Date(candles[n - 1].time));
      const ev = computeContinuousEV(symbol, score, regime, atrPercentile, session);

      if (ev > 0) {
        signal = 'sell';
        reason = `Boof 15.0: SHORT | score=${score.toFixed(1)} EV=${ev.toFixed(3)} regime=${regime}`;

        // Calculate dynamic risk parameters
        const { slDistance, tpDistance } = calculateRiskParameters(symbol, ev, atrCurrent);
        const stopLoss = curClose + slDistance;
        const takeProfit = curClose - tpDistance;

        // Store in local variables for final return
        const resultSignal: 'buy' | 'sell' | 'none' = 'sell';
        const resultPrice = curClose;
        const resultTrend = 0;
        const resultEma = ema9[i];
        const resultAdx = 0;
        const resultReason = reason;
        const resultRegime = regime;
        const resultEv = ev;
        const resultStopLoss = stopLoss;
        const resultTakeProfit = takeProfit;

        // Apply trade direction filter
        if (tradeDirection === 'long') {
          return {
            signal: 'none',
            price: resultPrice,
            trend: resultTrend,
            ema: resultEma,
            adx: resultAdx,
            reason: resultReason + ' (filtered by direction)'
          };
        }

        return {
          signal: resultSignal,
          price: resultPrice,
          trend: resultTrend,
          ema: resultEma,
          adx: resultAdx,
          reason: resultReason,
          regime: resultRegime,
          ev: resultEv,
          stopLoss: resultStopLoss,
          takeProfit: resultTakeProfit
        };
      } else {
        reason = `Boof 15.0: SHORT skipped | score=${score.toFixed(1)} EV=${ev.toFixed(3)} <= 0`;
      }
    }
  } else {
    reason = `Boof 15.0: no breakout | range=[${rangeLow.toFixed(2)}-${rangeHigh.toFixed(2)}]`;
  }

  return {
    signal: 'none',
    price: curClose,
    trend: ema9[i] > ema20[i] ? 1 : -1,
    ema: ema20[i],
    adx: atr[i],
    reason
  };
}

// ─────────────────────────────────────────────
// INDICATOR MATH
// ─────────────────────────────────────────────

function calcEMA(values: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const result: number[] = new Array(values.length).fill(NaN);
  // Find first valid index
  let start = period - 1;
  result[start] = values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = start + 1; i < values.length; i++) {
    result[i] = values[i] * k + result[i - 1] * (1 - k);
  }
  return result;
}

function calcATR(highs: number[], lows: number[], closes: number[], period: number): number[] {
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < highs.length; i++) {
    tr.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    ));
  }
  // Wilder's smoothing (RMA)
  const atr: number[] = new Array(highs.length).fill(NaN);
  atr[period - 1] = tr.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < highs.length; i++) {
    atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;
  }
  return atr;
}

function calcSuperTrend(
  highs: number[], lows: number[], closes: number[],
  atrPeriod: number, multiplier: number
): { trend: number[], upper: number[], lower: number[] } {
  const hl2 = highs.map((h, i) => (h + lows[i]) / 2);
  const atr = calcATR(highs, lows, closes, atrPeriod);

  const upper: number[] = new Array(highs.length).fill(NaN);
  const lower: number[] = new Array(highs.length).fill(NaN);
  const trend: number[] = new Array(highs.length).fill(1);

  for (let i = atrPeriod; i < highs.length; i++) {
    const basicUpper = hl2[i] + multiplier * atr[i];
    const basicLower = hl2[i] - multiplier * atr[i];

    upper[i] = (isNaN(upper[i - 1]) || basicUpper < upper[i - 1] || closes[i - 1] > upper[i - 1])
      ? basicUpper : upper[i - 1];

    lower[i] = (isNaN(lower[i - 1]) || basicLower > lower[i - 1] || closes[i - 1] < lower[i - 1])
      ? basicLower : lower[i - 1];

    if (closes[i] > upper[i - 1]) {
      trend[i] = 1;
    } else if (closes[i] < lower[i - 1]) {
      trend[i] = -1;
    } else {
      trend[i] = trend[i - 1];
    }
  }
  return { trend, upper, lower };
}

function calcDMI(
  highs: number[], lows: number[], closes: number[], period: number
): { plusDI: number[], minusDI: number[], adx: number[] } {
  const n = highs.length;
  const plusDM: number[] = new Array(n).fill(0);
  const minusDM: number[] = new Array(n).fill(0);
  const tr: number[] = new Array(n).fill(0);

  for (let i = 1; i < n; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    plusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0;
    minusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0;
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
  }

  // Wilder smoothing
  const smoothTR: number[] = new Array(n).fill(NaN);
  const smoothPlus: number[] = new Array(n).fill(NaN);
  const smoothMinus: number[] = new Array(n).fill(NaN);

  smoothTR[period] = tr.slice(1, period + 1).reduce((a, b) => a + b, 0);
  smoothPlus[period] = plusDM.slice(1, period + 1).reduce((a, b) => a + b, 0);
  smoothMinus[period] = minusDM.slice(1, period + 1).reduce((a, b) => a + b, 0);

  for (let i = period + 1; i < n; i++) {
    smoothTR[i] = smoothTR[i - 1] - smoothTR[i - 1] / period + tr[i];
    smoothPlus[i] = smoothPlus[i - 1] - smoothPlus[i - 1] / period + plusDM[i];
    smoothMinus[i] = smoothMinus[i - 1] - smoothMinus[i - 1] / period + minusDM[i];
  }

  const plusDI: number[] = new Array(n).fill(NaN);
  const minusDI: number[] = new Array(n).fill(NaN);
  const dx: number[] = new Array(n).fill(NaN);
  const adx: number[] = new Array(n).fill(NaN);

  for (let i = period; i < n; i++) {
    plusDI[i] = (smoothPlus[i] / smoothTR[i]) * 100;
    minusDI[i] = (smoothMinus[i] / smoothTR[i]) * 100;
    dx[i] = Math.abs(plusDI[i] - minusDI[i]) / (plusDI[i] + minusDI[i]) * 100;
  }

  // ADX = EMA of DX (Wilder)
  const start2 = period * 2 - 1;
  const validDx = dx.slice(period, start2 + 1).filter(v => !isNaN(v));
  if (validDx.length === period) {
    adx[start2] = validDx.reduce((a, b) => a + b, 0) / period;
    for (let i = start2 + 1; i < n; i++) {
      adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period;
    }
  }

  return { plusDI, minusDI, adx };
}

// ─────────────────────────────────────────────
// FUTURES P&L CALCULATION (Real contract specs)
// ─────────────────────────────────────────────

function getFuturesMultiplier(symbol: string): number {
  // Contract multipliers for major futures ($ per point)
  const multipliers: Record<string, number> = {
    'ES=F': 50,      // E-mini S&P 500: $50 per point
    'NQ=F': 20,      // E-mini NASDAQ: $20 per point
    'YM=F': 5,       // E-mini Dow: $5 per point
    'RTY=F': 50,     // E-mini Russell 2000: $50 per point
    'CL=F': 1000,    // Crude Oil: 1000 barrels, $1 = $1000
    'GC=F': 100,     // Gold: 100 oz, $1 = $100
    'SI=F': 5000,    // Silver: 5000 oz, $0.01 = $50, but priced in cents so $1 = $50... actually simpler: 5000 * $0.01 = $50 per $0.01 move. Let me use actual dollar value.
    'HG=F': 25000,   // Copper: 25,000 lbs, $0.01 = $250, but priced differently
    'NG=F': 10000,   // Natural Gas: 10,000 MMBtu, $0.001 = $10
    'ZN=F': 1000,    // 10-Year T-Note: $1000 per point
    'ZB=F': 1000,    // 30-Year T-Bond: $1000 per point
    'ZF=F': 1000,    // 5-Year T-Note: $1000 per point
    '6E=F': 125000,  // Euro FX: 125,000 EUR, $0.0001 = $12.50
    '6J=F': 12500000, // Japanese Yen: 12.5M YEN, $0.0001 = $12.50 (but priced as 0.01 yen = $12.50)
    '6B=F': 62500,   // British Pound: 62,500 GBP, $0.0001 = $6.25
    '6C=F': 100000,  // Canadian Dollar: 100,000 CAD, $0.0001 = $10
    '6A=F': 100000,  // Australian Dollar: 100,000 AUD, $0.0001 = $10
    'ZW=F': 5000,    // Wheat: 5,000 bushels, $0.01 = $50
    'ZC=F': 5000,    // Corn: 5,000 bushels, $0.01 = $50
    'ZS=F': 5000,    // Soybeans: 5,000 bushels, $0.01 = $50
    'ZL=F': 60000,   // Soybean Oil: 60,000 lbs, $0.01 = $600
  };
  return multipliers[symbol] || 1; // Default to 1 (like stocks) if unknown
}

function getFuturesTickValue(symbol: string): { tickSize: number; tickValue: number } {
  // Tick size and value for realistic P&L
  const specs: Record<string, { tickSize: number; tickValue: number }> = {
    'ES=F': { tickSize: 0.25, tickValue: 12.50 },      // 0.25 point = $12.50
    'NQ=F': { tickSize: 0.25, tickValue: 5.00 },       // 0.25 point = $5.00
    'YM=F': { tickSize: 1, tickValue: 5.00 },          // 1 point = $5.00
    'RTY=F': { tickSize: 0.1, tickValue: 5.00 },       // 0.1 point = $5.00
    'CL=F': { tickSize: 0.01, tickValue: 10.00 },      // $0.01 = $10
    'GC=F': { tickSize: 0.1, tickValue: 10.00 },       // $0.10 = $10
    'SI=F': { tickSize: 0.005, tickValue: 25.00 },     // $0.005 = $25
    'HG=F': { tickSize: 0.0005, tickValue: 12.50 },    // $0.0005 = $12.50
    'NG=F': { tickSize: 0.001, tickValue: 10.00 },     // $0.001 = $10
    'ZN=F': { tickSize: 0.015625, tickValue: 15.625 }, // 1/64 = $15.625
    'ZB=F': { tickSize: 0.03125, tickValue: 31.25 },   // 1/32 = $31.25
    'ZF=F': { tickSize: 0.0078125, tickValue: 7.8125 },// 1/128 = $7.8125
    '6E=F': { tickSize: 0.0001, tickValue: 12.50 },    // $0.0001 = $12.50
    '6J=F': { tickSize: 0.000001, tickValue: 12.50 },  // $0.000001 (actually 0.01 yen but displayed differently)
    '6B=F': { tickSize: 0.0001, tickValue: 6.25 },     // $0.0001 = $6.25
    '6C=F': { tickSize: 0.0001, tickValue: 10.00 },    // $0.0001 = $10
    '6A=F': { tickSize: 0.0001, tickValue: 10.00 },    // $0.0001 = $10
    'ZW=F': { tickSize: 0.25, tickValue: 12.50 },      // $0.0025 = $12.50
    'ZC=F': { tickSize: 0.25, tickValue: 12.50 },      // $0.0025 = $12.50
    'ZS=F': { tickSize: 0.25, tickValue: 12.50 },      // $0.0025 = $12.50
    'ZL=F': { tickSize: 0.01, tickValue: 600.00 },     // $0.01 = $600
  };
  return specs[symbol] || { tickSize: 0.01, tickValue: 1 }; // Default to stock-like
}

function calcFuturesPnL(symbol: string, entryPrice: number, exitPrice: number, qty: number, action: 'buy' | 'sell'): number {
  if (!symbol.includes('=F')) {
    // Not a futures symbol - use stock calculation
    return action === 'buy'
      ? (exitPrice - entryPrice) * qty
      : (entryPrice - exitPrice) * qty;
  }

  // Calculate point difference
  const pointDiff = action === 'buy'
    ? exitPrice - entryPrice
    : entryPrice - exitPrice;

  // Get contract specs
  const multiplier = getFuturesMultiplier(symbol);
  const { tickSize, tickValue } = getFuturesTickValue(symbol);

  // Calculate P&L: (point difference / tick size) * tick value * quantity
  // This gives realistic futures P&L based on actual contract specifications
  const ticks = pointDiff / tickSize;
  const pnl = ticks * tickValue * qty;

  return pnl;
}

function calcRSI(closes: number[], period: number): number[] {
  const rsi: number[] = new Array(closes.length).fill(NaN);
  if (closes.length < period + 1) return rsi;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  rsi[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const g = diff > 0 ? diff : 0;
    const l = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return rsi;
}

function calcMACD(closes: number[], fast: number, slow: number, signal: number): { macdLine: number[], signalLine: number[], hist: number[] } {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macdLine = closes.map((_, i) => (isNaN(emaFast[i]) || isNaN(emaSlow[i])) ? NaN : emaFast[i] - emaSlow[i]);
  const validStart = macdLine.findIndex(v => !isNaN(v));
  const signalLine: number[] = new Array(closes.length).fill(NaN);
  if (validStart >= 0) {
    const validMacd = macdLine.slice(validStart);
    const emaSignal = calcEMA(validMacd, signal);
    for (let i = 0; i < emaSignal.length; i++) signalLine[validStart + i] = emaSignal[i];
  }
  const hist = macdLine.map((v, i) => (isNaN(v) || isNaN(signalLine[i])) ? NaN : v - signalLine[i]);
  return { macdLine, signalLine, hist };
}

function calcBollinger(closes: number[], period: number, stdDev: number): { upper: number[], mid: number[], lower: number[] } {
  const upper: number[] = new Array(closes.length).fill(NaN);
  const mid: number[]   = new Array(closes.length).fill(NaN);
  const lower: number[] = new Array(closes.length).fill(NaN);
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / period;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    mid[i]   = mean;
    upper[i] = mean + stdDev * sd;
    lower[i] = mean - stdDev * sd;
  }
  return { upper, mid, lower };
}

// ─────────────────────────────────────────────
// BOOF 2.0 ML-STYLE INDICATOR
// ─────────────────────────────────────────────

interface Boof20Result {
  predictedReturn: number;
  signal: number;  // 1 = buy, -1 = sell, 0 = neutral
  pastReturn: number;
  maDiff: number;
  rsi: number;
  atr: number;
}

function calcBoof20(
  highs: number[],
  lows: number[],
  closes: number[],
  length = 14,
  maFast = 5,
  maSlow = 20,
  volLength = 14,
  thresholdBuy = 0.0,
  thresholdSell = 0.0
): Boof20Result[] {
  const n = closes.length;
  const result: Boof20Result[] = new Array(n).fill({ predictedReturn: 0, signal: 0, pastReturn: 0, maDiff: 0, rsi: 50, atr: 0 });

  if (n < maSlow + 1) return result;

  // Calculate past return (momentum)
  const pastReturn: number[] = new Array(n).fill(0);
  for (let i = length; i < n; i++) {
    pastReturn[i] = (closes[i] - closes[i - length]) / closes[i - length];
  }

  // Calculate fast and slow MAs
  const maFastVals: number[] = new Array(n).fill(NaN);
  const maSlowVals: number[] = new Array(n).fill(NaN);

  for (let i = maFast - 1; i < n; i++) {
    const slice = closes.slice(i - maFast + 1, i + 1);
    maFastVals[i] = slice.reduce((a, b) => a + b, 0) / maFast;
  }

  for (let i = maSlow - 1; i < n; i++) {
    const slice = closes.slice(i - maSlow + 1, i + 1);
    maSlowVals[i] = slice.reduce((a, b) => a + b, 0) / maSlow;
  }

  // Calculate MA difference (trend)
  const maDiff: number[] = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    if (!isNaN(maFastVals[i]) && !isNaN(maSlowVals[i])) {
      maDiff[i] = maFastVals[i] - maSlowVals[i];
    }
  }

  // Calculate RSI
  const rsi = calcRSI(closes, length);

  // Calculate simplified ATR (high-low range over volLength)
  const atr: number[] = new Array(n).fill(0);
  for (let i = volLength - 1; i < n; i++) {
    const highSlice = highs.slice(i - volLength + 1, i + 1);
    const lowSlice = lows.slice(i - volLength + 1, i + 1);
    atr[i] = Math.max(...highSlice) - Math.min(...lowSlice);
  }

  // Calculate predicted return using weighted formula
  for (let i = maSlow; i < n; i++) {
    const rPast = pastReturn[i] || 0;
    const rMa = maDiff[i] / closes[i] || 0;
    const rRsi = (rsi[i] - 50) / 50 || 0;
    const rAtr = atr[i] / closes[i] || 0;

    // ML-style predicted return
    const predictedReturn = (
      0.4 * rPast +
      0.3 * rMa +
      0.2 * rRsi -
      0.1 * rAtr
    );

    // Generate signal
    let signal = 0;
    if (predictedReturn > thresholdBuy) signal = 1;      // buy
    else if (predictedReturn < thresholdSell) signal = -1;  // sell

    result[i] = {
      predictedReturn,
      signal,
      pastReturn: rPast,
      maDiff: maDiff[i],
      rsi: rsi[i],
      atr: atr[i]
    };
  }

  return result;
}

function generateSignalRSIMACD(candles: Candle[], tradeDirection = 'both'): SignalResult {
  const closes = candles.map(c => c.close);
  const n = closes.length;
  const i = n - 2; // last completed bar

  const rsi  = calcRSI(closes, 14);
  const ema50 = calcEMA(closes, 50);
  const { hist } = calcMACD(closes, 12, 26, 9);

  const curRSI   = rsi[i];
  const curEma   = ema50[i];
  const curHist  = hist[i];
  const curClose = closes[i];

  // Replay state to track inLong like PineScript (exact match)
  // Pine: if not inLong and buyCond -> inLong := true
  //       if inLong and sellCond -> inLong := false
  let inLong = false;
  for (let j = 50; j <= i; j++) {
    const r = rsi[j], h = hist[j], e = ema50[j], c = closes[j];
    if (isNaN(r) || isNaN(h) || isNaN(e)) continue;
    const buyCond  = (r < 30 || h > 0) && c > e;
    const sellCond = (r > 70 || h < 0) && c < e;
    if (!inLong && buyCond)  inLong = true;
    if (inLong  && sellCond) inLong = false;
  }

  // PineScript logic (exact match):
  // buyCond = (rsi < 30 or macdHist > 0) and close > ema50
  // sellCond = (rsi > 70 or macdHist < 0) and close < ema50
  const buyCond  = (curRSI < 30 || curHist > 0) && curClose > curEma;
  const sellCond = (curRSI > 70 || curHist < 0) && curClose < curEma;

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `rsi=${curRSI?.toFixed(1)}, macd_hist=${curHist?.toFixed(4)}, ema=${curEma?.toFixed(2)}, close=${curClose?.toFixed(2)}, inLong=${inLong}`;

  // Pine: if not inLong and buyCond -> BUY
  //       if inLong and sellCond -> SELL
  if (!inLong && buyCond)  { signal = 'buy';  reason = `PineScript BUY. ${reason}`; }
  if (inLong  && sellCond) { signal = 'sell'; reason = `PineScript SELL. ${reason}`; }

  return { signal, price: curClose, trend: curClose > curEma ? 1 : -1, ema: curEma, adx: curRSI, reason };
}

function generateSignalBoof20(candles: Candle[], tradeDirection = 'both', thresholdBuy = 0.0, thresholdSell = 0.0): SignalResult {
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const n = closes.length;

  if (n < 25) {
    return { signal: 'none', price: closes[n - 1], trend: 0, ema: closes[n - 1], adx: 50, reason: 'Insufficient data for Boof 2.0' };
  }

  const boofResults = calcBoof20(highs, lows, closes, 14, 5, 20, 14, thresholdBuy, thresholdSell);
  const i = n - 2; // last completed bar
  const current = boofResults[i];
  const prev = boofResults[i - 1];
  const curClose = closes[i];

  if (!current) {
    return { signal: 'none', price: curClose, trend: 0, ema: curClose, adx: 50, reason: 'Boof 2.0 calculation error' };
  }

  // Track position state — only last 30 bars to avoid stale history blocking signals
  let inLong = false;
  const replayStart = Math.max(20, i - 30);
  for (let j = replayStart; j <= i; j++) {
    if (boofResults[j].signal === 1 && !inLong) inLong = true;
    else if (boofResults[j].signal === -1 && inLong) inLong = false;
  }

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `predicted_return=${current.predictedReturn?.toFixed(4)}, rsi=${current.rsi?.toFixed(1)}, past_ret=${current.pastReturn?.toFixed(4)}, inLong=${inLong}`;

  // Generate signal based on Boof 2.0 prediction
  if (!inLong && current.signal === 1) {
    signal = 'buy';
    reason = `Boof 2.0 BUY. ${reason}`;
  } else if (inLong && current.signal === -1) {
    signal = 'sell';
    reason = `Boof 2.0 SELL. ${reason}`;
  }

  // Apply trade direction filter
  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  return {
    signal,
    price: curClose,
    trend: current.predictedReturn > 0 ? 1 : -1,
    ema: closes.slice(i - 19, i + 1).reduce((a, b) => a + b, 0) / 20,
    adx: current.rsi,
    reason
  };
}

// ─────────────────────────────────────────────
// BOOF 3.0 KMEANS REGIME DETECTION
// ─────────────────────────────────────────────

type MarketRegime = 'Trend' | 'Range' | 'HighVol';

interface Boof30Result {
  regime: MarketRegime;
  returnStd: number;
  maSlope: number;
  rsi: number;
  volumeStd: number;
  signal: number; // 1 = buy, -1 = sell, 0 = neutral
}

// Simple KMeans implementation for 3 clusters
function kMeansClustering(data: number[][], k: number, maxIterations = 100): { clusters: number[], centroids: number[][] } {
  const n = data.length;
  const dims = data[0].length;

  // Initialize centroids randomly
  const centroids: number[][] = [];
  const usedIndices = new Set<number>();
  for (let i = 0; i < k; i++) {
    let idx = Math.floor(Math.random() * n);
    while (usedIndices.has(idx)) idx = Math.floor(Math.random() * n);
    usedIndices.add(idx);
    centroids.push([...data[idx]]);
  }

  let clusters: number[] = new Array(n).fill(0);
  let iterations = 0;
  let changed = true;

  while (changed && iterations < maxIterations) {
    changed = false;
    iterations++;

    // Assign points to nearest centroid
    for (let i = 0; i < n; i++) {
      let minDist = Infinity;
      let bestCluster = 0;
      for (let j = 0; j < k; j++) {
        const dist = euclideanDistance(data[i], centroids[j]);
        if (dist < minDist) {
          minDist = dist;
          bestCluster = j;
        }
      }
      if (clusters[i] !== bestCluster) {
        clusters[i] = bestCluster;
        changed = true;
      }
    }

    // Update centroids
    const newCentroids: number[][] = Array(k).fill(null).map(() => Array(dims).fill(0));
    const counts = Array(k).fill(0);
    for (let i = 0; i < n; i++) {
      const c = clusters[i];
      counts[c]++;
      for (let d = 0; d < dims; d++) {
        newCentroids[c][d] += data[i][d];
      }
    }
    for (let j = 0; j < k; j++) {
      if (counts[j] > 0) {
        for (let d = 0; d < dims; d++) {
          newCentroids[j][d] /= counts[j];
        }
        centroids[j] = newCentroids[j];
      }
    }
  }

  return { clusters, centroids };
}

function euclideanDistance(a: number[], b: number[]): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    sum += (a[i] - b[i]) ** 2;
  }
  return Math.sqrt(sum);
}

function calcBoof30(
  candles: Candle[],
  lookback = 14
): Boof30Result[] {
  const n = candles.length;
  const result: Boof30Result[] = new Array(n).fill({
    regime: 'Range', returnStd: 0, maSlope: 0, rsi: 50, volumeStd: 0, signal: 0
  });

  if (n < lookback + 20) return result;

  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => (c as any).volume || 1000000); // Default volume if not available

  // Calculate returns
  const returns: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    returns[i] = (closes[i] - closes[i - 1]) / closes[i - 1];
  }

  // Feature 1: return_std (volatility)
  const returnStd: number[] = new Array(n).fill(0);
  for (let i = lookback; i < n; i++) {
    const slice = returns.slice(i - lookback + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / lookback;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / lookback;
    returnStd[i] = Math.sqrt(variance);
  }

  // Feature 2: ma_slope (trend strength)
  const maFast: number[] = new Array(n).fill(NaN);
  const maSlow: number[] = new Array(n).fill(NaN);
  for (let i = 4; i < n; i++) {
    maFast[i] = closes.slice(i - 4, i + 1).reduce((a, b) => a + b, 0) / 5;
  }
  for (let i = 19; i < n; i++) {
    maSlow[i] = closes.slice(i - 19, i + 1).reduce((a, b) => a + b, 0) / 20;
  }
  const maSlope: number[] = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    if (!isNaN(maFast[i]) && !isNaN(maSlow[i])) {
      maSlope[i] = maFast[i] - maSlow[i];
    }
  }

  // Feature 3: RSI
  const rsi = calcRSI(closes, lookback);

  // Feature 4: volume_std
  const volumeStd: number[] = new Array(n).fill(0);
  for (let i = lookback; i < n; i++) {
    const slice = volumes.slice(i - lookback + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / lookback;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / lookback;
    volumeStd[i] = Math.sqrt(variance);
  }

  // Prepare data for clustering (only valid rows)
  const validStart = Math.max(lookback, 20);
  const features: number[][] = [];
  const validIndices: number[] = [];

  for (let i = validStart; i < n; i++) {
    if (!isNaN(rsi[i])) {
      features.push([
        returnStd[i] * 100, // Scale up for better clustering
        maSlope[i],
        rsi[i],
        volumeStd[i] / 1000000 // Scale down volume
      ]);
      validIndices.push(i);
    }
  }

  if (features.length < 10) return result;

  // Run KMeans clustering
  const { clusters } = kMeansClustering(features, 3, 50);

  // Map clusters to regimes based on ma_slope
  const clusterStats: { cluster: number, avgSlope: number }[] = [];
  for (let c = 0; c < 3; c++) {
    const indices = validIndices.filter((_, idx) => clusters[idx] === c);
    const avgSlope = indices.reduce((a, idx) => a + maSlope[idx], 0) / indices.length;
    clusterStats.push({ cluster: c, avgSlope });
  }

  // Sort by ma_slope: lowest = Range, middle = HighVol, highest = Trend
  clusterStats.sort((a, b) => a.avgSlope - b.avgSlope);
  const regimeMap: Record<number, MarketRegime> = {
    [clusterStats[0].cluster]: 'Range',
    [clusterStats[1].cluster]: 'HighVol',
    [clusterStats[2].cluster]: 'Trend'
  };

  // Assign regimes and generate signals
  for (let idx = 0; idx < validIndices.length; idx++) {
    const i = validIndices[idx];
    const cluster = clusters[idx];
    const regime = regimeMap[cluster];

    // Generate signal based on regime
    let signal = 0;
    if (regime === 'Trend') {
      // Trend-following: buy if slope positive, sell if negative
      if (maSlope[i] > 0 && rsi[i] > 50) signal = 1;
      else if (maSlope[i] < 0 && rsi[i] < 50) signal = -1;
    } else if (regime === 'Range') {
      // Mean reversion: buy if oversold, sell if overbought
      if (rsi[i] < 35) signal = 1;
      else if (rsi[i] > 65) signal = -1;
    } else if (regime === 'HighVol') {
      // High volatility: be cautious, use tight criteria
      if (rsi[i] < 25 && maSlope[i] > 0) signal = 1;
      else if (rsi[i] > 75 && maSlope[i] < 0) signal = -1;
    }

    result[i] = {
      regime,
      returnStd: returnStd[i],
      maSlope: maSlope[i],
      rsi: rsi[i],
      volumeStd: volumeStd[i],
      signal
    };
  }

  return result;
}

function generateSignalBoof30(candles: Candle[], tradeDirection = 'both'): SignalResult {
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const volumes = candles.map(c => (c as any).volume || 1000000);
  const n = closes.length;

  if (n < 35) return { signal: 'none', price: closes[n - 1], trend: 0, ema: closes[n - 1], adx: 50, reason: 'Insufficient data' };

  const lookback = 14;

  // Returns
  const returns: number[] = new Array(n).fill(0);
  for (let i = 1; i < n; i++) returns[i] = (closes[i] - closes[i - 1]) / closes[i - 1];

  // Return std
  const returnStd: number[] = new Array(n).fill(0);
  for (let i = lookback; i < n; i++) {
    const slice = returns.slice(i - lookback + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / lookback;
    returnStd[i] = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / lookback);
  }

  // MA slope
  const maFast: number[] = new Array(n).fill(NaN);
  const maSlow: number[] = new Array(n).fill(NaN);
  for (let i = 4; i < n; i++) maFast[i] = closes.slice(i - 4, i + 1).reduce((a, b) => a + b, 0) / 5;
  for (let i = 19; i < n; i++) maSlow[i] = closes.slice(i - 19, i + 1).reduce((a, b) => a + b, 0) / 20;
  const maSlope = maFast.map((f, i) => !isNaN(f) && !isNaN(maSlow[i]) ? f - maSlow[i] : 0);

  // RSI
  const rsi = calcRSI(closes, lookback);

  // Volume std
  const volumeStd: number[] = new Array(n).fill(0);
  for (let i = lookback; i < n; i++) {
    const slice = volumes.slice(i - lookback + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / lookback;
    volumeStd[i] = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / lookback);
  }

  // Prepare features for clustering
  const validStart = Math.max(lookback, 20);
  const features: number[][] = [];
  const validIndices: number[] = [];
  for (let i = validStart; i < n; i++) {
    if (!isNaN(rsi[i])) {
      features.push([returnStd[i] * 100, maSlope[i], rsi[i], volumeStd[i] / 1000000]);
      validIndices.push(i);
    }
  }

  if (features.length < 10) return { signal: 'none', price: closes[n - 1], trend: 0, ema: closes[n - 1], adx: 50, reason: 'Not enough data' };

  // KMeans clustering
  const { clusters } = kMeansClustering(features, 3, 50);

  // Map clusters to regimes by avg slope
  const clusterStats: { cluster: number, avgSlope: number }[] = [];
  for (let c = 0; c < 3; c++) {
    const indices = validIndices.filter((_, idx) => clusters[idx] === c);
    const avgSlope = indices.reduce((a, idx) => a + maSlope[idx], 0) / indices.length;
    clusterStats.push({ cluster: c, avgSlope });
  }
  clusterStats.sort((a, b) => a.avgSlope - b.avgSlope);
  const regimeMap: Record<number, MarketRegime> = {
    [clusterStats[0].cluster]: 'Range',
    [clusterStats[1].cluster]: 'HighVol',
    [clusterStats[2].cluster]: 'Trend'
  };

  // Generate signals for each point
  const signals: { regime: MarketRegime, signal: number }[] = [];
  for (let idx = 0; idx < validIndices.length; idx++) {
    const i = validIndices[idx];
    const regime = regimeMap[clusters[idx]];
    let signal = 0;
    if (regime === 'Trend') {
      signal = maSlope[i] > 0 ? 1 : -1;
    } else if (regime === 'Range') {
      if (rsi[i] < 45) signal = 1;
      else if (rsi[i] > 55) signal = -1;
    } else if (regime === 'HighVol') {
      signal = maSlope[i] > 0 ? 1 : -1;
    }
    signals.push({ regime, signal });
  }

  // Current bar - only fire on crossover (signal changed from prev bar)
  const i = n - 2;
  const idx = validIndices.indexOf(i);
  const prevIdx = validIndices.indexOf(i - 1);
  const current = idx >= 0 ? signals[idx] : { regime: 'Range' as MarketRegime, signal: 0 };
  const prev = prevIdx >= 0 ? signals[prevIdx] : { signal: 0 };
  const curClose = closes[i];
  const justFlipped = current.signal !== prev.signal;

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `regime=${current.regime}, rsi=${rsi[i]?.toFixed(1)}, slope=${maSlope[i]?.toFixed(4)}`;

  if (current.signal === 1 && justFlipped) {
    signal = 'buy';
    reason = `Boof 3.0 BUY CROSSOVER [${current.regime}]. ${reason}`;
  } else if (current.signal === -1 && justFlipped) {
    signal = 'sell';
    reason = `Boof 3.0 SELL CROSSOVER [${current.regime}]. ${reason}`;
  } else {
    reason = `Boof 3.0 NONE [${current.regime}]. ${reason}`;
  }

  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  return { signal, price: curClose, trend: maSlope[i] > 0 ? 1 : -1, ema: maSlow[i], adx: rsi[i], reason };
}

// ─────────────────────────────────────────────
// BOOF 5.0 - SIX-FACTOR QUANT MODEL
// ─────────────────────────────────────────────

function b50SMA(data: number[], period: number): number[] {
  const result: number[] = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    result.push(slice.reduce((a, b) => a + b, 0) / period);
  }
  return result;
}

function b50StdDev(data: number[], period: number): number {
  if (data.length < period) return 0;
  const slice = data.slice(-period);
  const mean = slice.reduce((a, b) => a + b, 0) / period;
  return Math.sqrt(slice.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / period);
}

function b50Mean(data: number[]): number {
  return data.length > 0 ? data.reduce((a, b) => a + b, 0) / data.length : 0;
}

function b50ATR(highs: number[], lows: number[], closes: number[], period: number): number {
  const tr: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    tr.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i-1]), Math.abs(lows[i] - closes[i-1])));
  }
  return tr.length >= period ? b50Mean(tr.slice(-period)) : 0;
}

function b50ADX(highs: number[], lows: number[], closes: number[], period: number): number {
  const dmP: number[] = [], dmM: number[] = [], trV: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const up = highs[i] - highs[i-1], dn = lows[i-1] - lows[i];
    dmP.push(up > dn && up > 0 ? up : 0);
    dmM.push(dn > up && dn > 0 ? dn : 0);
    trV.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i-1]), Math.abs(lows[i] - closes[i-1])));
  }
  if (dmP.length < period) return 25;
  const diP = 100 * b50Mean(dmP.slice(-period)) / b50Mean(trV.slice(-period));
  const diM = 100 * b50Mean(dmM.slice(-period)) / b50Mean(trV.slice(-period));
  return (diP + diM) > 0 ? 100 * Math.abs(diP - diM) / (diP + diM) : 0;
}

function generateSignalBoof50(candles: any[], tradeDirection = 'both'): SignalResult {
  const highs = candles.map(c => c.high);
  const lows  = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const opens  = candles.map(c => c.open);
  const volumes = candles.map(c => c.volume || 1000000);
  const n = closes.length;

  if (n < 50) return { signal: 'none', price: closes[n-1], trend: 0, ema: closes[n-1], adx: 0, reason: 'Boof 5.0: insufficient data' };

  const i = n - 2;

  // Factor 1: Momentum
  const momentum = ((closes[i] - closes[i-10]) / closes[i-10]) * 100;
  const momentumAccel = momentum - ((closes[i-1] - closes[i-11]) / closes[i-11]) * 100;
  let momScore = 0;
  if (momentum > 1.5 && momentumAccel > 0) momScore = 2;
  else if (momentum > 0.5) momScore = 1;
  else if (momentum < -1.5 && momentumAccel < 0) momScore = -2;
  else if (momentum < -0.5) momScore = -1;

  // Factor 2: Mean Reversion
  const sma20 = b50SMA(closes, 20);
  const std20 = b50StdDev(closes, 20);
  const zScore = std20 > 0 ? (closes[i] - sma20[sma20.length-1]) / std20 : 0;
  const bbUpper = sma20[sma20.length-1] + 2*std20;
  const bbLower = sma20[sma20.length-1] - 2*std20;
  const bbPos = bbUpper !== bbLower ? (closes[i] - bbLower) / (bbUpper - bbLower) : 0.5;
  let mrScore = 0;
  if (zScore < -1.5 && bbPos < 0.1) mrScore = 1;
  else if (zScore > 1.5 && bbPos > 0.9) mrScore = -1;

  // Factor 3: Volatility
  const returns: number[] = [];
  for (let j = 1; j < n; j++) returns.push((closes[j] - closes[j-1]) / closes[j-1]);
  const currentVol = b50StdDev(returns.slice(-20), 20);
  const volMean = b50Mean(returns.slice(-50).map(r => Math.abs(r)));
  const volPercentile = volMean > 0 ? Math.min(1, currentVol / (volMean * 2)) : 0.5;
  const highVol = volPercentile > 0.85; // Relaxed from 0.8 for crypto
  const lowVol  = volPercentile < 0.2;
  const atr = b50ATR(highs, lows, closes, 14);

  // Factor 4: Trend
  const ema20 = calcEMA(closes, 20);
  const ema50 = calcEMA(closes, 50);
  const ema200 = n >= 200 ? calcEMA(closes, 200) : ema50;
  const adx = b50ADX(highs, lows, closes, 14);
  const strongTrend = adx > 20; // Relaxed from 25 for crypto
  const weakTrend   = adx < 15;
  const aboveEMA20  = closes[i] > ema20[ema20.length-1];
  const aboveEMA50  = closes[i] > ema50[ema50.length-1];
  const aboveEMA200 = closes[i] > ema200[ema200.length-1];
  let trendScore = 0;
  if (strongTrend && aboveEMA20 && aboveEMA50 && aboveEMA200) trendScore = 2;
  else if (aboveEMA20 && aboveEMA50) trendScore = 1;
  else if (strongTrend && !aboveEMA20 && !aboveEMA50 && !aboveEMA200) trendScore = -2;
  else if (!aboveEMA20 && !aboveEMA50) trendScore = -1;

  // Factor 5: Volume
  const volSMA = b50SMA(volumes, 20);
  const relVol = volumes[i] / (volSMA[volSMA.length-1] || 1);
  let obv = 0;
  for (let j = Math.max(1, n-20); j < n; j++) {
    obv += closes[j] > closes[j-1] ? volumes[j] : closes[j] < closes[j-1] ? -volumes[j] : 0;
  }
  const volScore = (relVol > 1.2 && obv > 0) ? 1 : 0;

  // Factor 6: Microstructure
  const body = Math.abs(closes[i] - opens[i]);
  const wick = highs[i] - lows[i];
  const bodyRatio = wick > 0 ? body / wick : 0;
  const upperWick = highs[i] - Math.max(opens[i], closes[i]);
  const lowerWick = Math.min(opens[i], closes[i]) - lows[i];
  let microScore = 0;
  if (wick > 0 && lowerWick / wick > 0.6 && bodyRatio > 0.3) microScore = 1;
  else if (wick > 0 && upperWick / wick > 0.6 && bodyRatio > 0.3) microScore = -1;

  // Regime
  let regime = 'UNCERTAIN';
  if (strongTrend && !weakTrend) regime = aboveEMA50 ? 'TREND_UP' : 'TREND_DOWN';
  else if (weakTrend && Math.abs(zScore) < 1) regime = 'RANGING';
  else if (highVol) regime = 'VOLATILE';

  // Composite
  let composite = momScore + trendScore + mrScore + volScore + microScore;
  if (regime === 'RANGING') composite = -composite * 0.5;
  else if (regime === 'VOLATILE' && !strongTrend) composite = composite * 0.4; // Relaxed from 0.3

  // Signal — relaxed threshold for crypto (1.2 instead of 1.5)
  const threshold = 1.2;
  let signal: 'buy' | 'sell' | 'none' = 'none';
  if (composite > threshold && regime !== 'VOLATILE') signal = 'buy';
  else if (composite < -threshold && regime !== 'VOLATILE') signal = 'sell';

  if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';

  const reason = `Boof 5.0 [${regime}] MOM=${momScore} TREND=${trendScore} MR=${mrScore} VOL=${volScore} MICRO=${microScore} COMPOSITE=${composite.toFixed(2)}`;
  return { signal, price: closes[i], trend: trendScore, ema: ema50[ema50.length-1], adx, reason, regime, rsi: zScore*10+50, slope: momentum, atr };
}

// ─────────────────────────────────────────────
// BOOF 6.0 - MULTI-TIMEFRAME SCALPING
// ─────────────────────────────────────────────

function generateSignalBoof60(candles: any[], candles1h: any[], candles15m: any[], candles1m: any[], tradeDirection: string, isCrypto = false): SignalResult {
  const n = candles.length;
  if (n < 30) return { signal: 'none', price: 0, trend: 0, ema: 0, adx: 0, reason: 'Boof 6.0: not enough candles' };

  const closes  = candles.map(c => c.close);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume ?? 0);
  const curClose  = closes[n-1];
  const prevClose = closes[n-2];
  const prev2Close = closes[n-3];

  const avgSpacingSec = n > 10 ? (candles[n-1].time - candles[n-10].time) / (9 * 1000) : 300;
  const is1m = avgSpacingSec < 90;

  // 1H trend lock
  let trendBias: 'up' | 'down' | 'flat' = 'flat';
  if (candles1h.length >= 25) {
    const c1h = candles1h.map((c: any) => c.close);
    const ema1h = calcEMA(c1h, 20);
    const emaLast = ema1h[ema1h.length-1];
    const emaPrev = ema1h[ema1h.length-5];
    const slope = (emaLast - emaPrev) / emaPrev;
    const price1h = c1h[c1h.length-1];
    if (price1h > emaLast && slope > 0.0003) trendBias = 'up';
    else if (price1h < emaLast && slope < -0.0003) trendBias = 'down';
  }
  if (trendBias === 'flat') return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: 0, reason: 'Boof 6.0: 1h trend flat' };

  // ADX filter - check if rising too
  const { adx: adxArr } = calcDMI(highs, lows, closes, 14);
  const adxVal = adxArr[adxArr.length-1] ?? 0;
  const adxPrev = adxArr[adxArr.length-2] ?? 0;
  const adxRising = adxVal > adxPrev;
  const adxMin = is1m ? 14 : 18;
  if (adxVal < adxMin) return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: adxVal, reason: `Boof 6.0: ADX=${adxVal.toFixed(1)} too low` };
  // NEW: ADX must be rising or very strong (>25)
  if (!adxRising && adxVal < 25) return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: adxVal, reason: `Boof 6.0: ADX=${adxVal.toFixed(1)} falling, trend exhausting` };

  // NEW: Choppiness Index filter - skip choppy markets (same as 7.0/8.0)
  const ci = calcChoppinessIndex(highs, lows, closes, 14);
  const ciThreshold = isCrypto ? 65 : 55; // Crypto naturally choppier
  if (ci > ciThreshold) return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: adxVal, reason: `Boof 6.0: too choppy (CI=${ci.toFixed(1)})` };

  // EMA side
  let ema15Val = 0;
  if (candles15m.length >= 22) {
    const c15m = candles15m.map((c: any) => c.close);
    const ema15 = calcEMA(is1m ? closes : c15m, is1m ? 50 : 20);
    ema15Val = ema15[ema15.length-1] ?? 0;
  }
  if (ema15Val > 0) {
    if (trendBias === 'up'   && curClose < ema15Val) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: close below EMA (up bias)' };
    if (trendBias === 'down' && curClose > ema15Val) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: close above EMA (down bias)' };
  }

  // VWAP
  let vwapConfirmed = false;
  let vwapVal = 0;
  if (candles1m.length >= 30) {
    vwapVal = calcVWAP(candles1m);
    if (trendBias === 'up'   && curClose >= vwapVal && prevClose >= vwapVal) vwapConfirmed = true;
    if (trendBias === 'down' && curClose <= vwapVal && prevClose <= vwapVal) vwapConfirmed = true;
  } else {
    vwapConfirmed = true; // Skip VWAP if no 1m data
  }
  if (!vwapConfirmed) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: VWAP not confirmed' };

  // MACD
  const { hist } = is1m ? calcMACD(closes, 5, 13, 4) : calcMACD(closes, 12, 26, 9);
  const histLast = hist[hist.length-1] ?? 0;
  const histPrev = hist[hist.length-2] ?? 0;
  const macdOK = trendBias === 'up'
    ? ((histLast > histPrev && histLast > 0) || (histPrev <= 0 && histLast > 0))
    : ((histLast < histPrev && histLast < 0) || (histPrev >= 0 && histLast < 0));
  if (!macdOK) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: MACD not confirming' };

  // Momentum
  let momOK = false;
  if (is1m) {
    const ref5 = closes[n-6] ?? closes[0];
    momOK = trendBias === 'up' ? curClose > ref5 : curClose < ref5;
  } else {
    const momUp   = curClose > prevClose && prevClose > prev2Close;
    const momDown  = curClose < prevClose && prevClose < prev2Close;
    const momUpR   = curClose > prev2Close && (curClose > prevClose || prevClose > prev2Close);
    const momDownR = curClose < prev2Close && (curClose < prevClose || prevClose < prev2Close);
    momOK = trendBias === 'up' ? (momUp || momUpR) : (momDown || momDownR);
  }
  if (!momOK) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: momentum not building' };

  // Volume
  const avgVol = volumes.slice(-20).reduce((a: number, b: number) => a + b, 0) / 20;
  if (avgVol > 0 && volumes[n-1] < avgVol * 0.8) return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: 'Boof 6.0: volume too low' };

  // NEW: Pullback filter - wait for small pullback before entering (prevents V-bottom/top entries)
  // For SELL (puts): need 0.3% bounce from recent low (0.5% for crypto)
  // For BUY (calls): need 0.3% pullback from recent high (0.5% for crypto)
  const recentHigh = Math.max(...highs.slice(Math.max(0, n-6), n));
  const recentLow  = Math.min(...lows.slice(Math.max(0, n-6), n));
  const atrVals: number[] = [];
  for (let j = 1; j < n; j++) atrVals.push(Math.max(highs[j]-lows[j], Math.abs(highs[j]-closes[j-1]), Math.abs(lows[j]-closes[j-1])));
  const atrNow = b50Mean(atrVals.slice(-14));
  const rangeSize = recentHigh - recentLow;
  const pullbackPct = isCrypto ? 0.005 : 0.003; // 0.5% for crypto, 0.3% for stocks

  if (trendBias === 'down') {
    // For puts: wait for bounce from low
    const bounceNeeded = recentLow * (1 + pullbackPct);
    if (curClose < bounceNeeded && rangeSize > atrNow * 3) {
      return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: waiting for bounce from low (CI=${ci.toFixed(1)})` };
    }
  } else if (trendBias === 'up') {
    // For calls: wait for pullback from high
    const pullbackNeeded = recentHigh * (1 - pullbackPct);
    if (curClose > pullbackNeeded && rangeSize > atrNow * 3) {
      return { signal: 'none', price: curClose, trend: 0, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: waiting for pullback from high (CI=${ci.toFixed(1)})` };
    }
  }

  let signal: 'buy' | 'sell' | 'none' = trendBias === 'up' ? 'buy' : 'sell';
  if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';

  const reason = `Boof 6.0 [${trendBias.toUpperCase()}${is1m?'/1m':'/5m+'}] adx=${adxVal.toFixed(1)}${adxRising?'↑':'↓'} ci=${ci.toFixed(1)} macd=${histLast.toFixed(4)} vwap=$${vwapVal.toFixed(2)} pullback=ok`;
  return { signal, price: curClose, trend: trendBias === 'up' ? 1 : -1, ema: ema15Val, adx: adxVal, reason };
}

// ─────────────────────────────────────────────
// BOOF 7.0 — THE ADAPTIVE SCALPER
// "Only trade when the market is in the right mood"
//
// Features:
//   1. Regime detection (Trend/Range/HighVol/LowVol/Explosive)
//   2. Dynamic TP/SL from ATR × regime multiplier
//   3. Volatility-adjusted + drawdown-aware position sizing
//   4. Trade filters (volume, liquidity windows, kill-switch)
//   5. Strategy switching per regime
//   6. No-trade zones (dead market hours)
// ─────────────────────────────────────────────

interface Boof70Regime {
  type: 'TREND_UP' | 'TREND_DOWN' | 'RANGE' | 'HIGH_VOL' | 'LOW_VOL' | 'EXPLOSIVE';
  adx: number;
  atr: number;
  atrPercent: number;
  bbWidth: number;
  maSlope: number;
  volatilityPercentile: number;
  shouldTrade: boolean;
  noTradeReason?: string;
}

interface Boof70Result extends SignalResult {
  regime: string;
  dynamicTP: number;
  dynamicSL: number;
  positionSizePct: number;
  killSwitch: boolean;
  killReason?: string;
  regimeDetails: Boof70Regime;
  ci?: number;
}

// ── Regime Detector ──────────────────────────────────────────────────────────
function detectRegime70(
  highs: number[], lows: number[], closes: number[], volumes: number[]
): Boof70Regime {
  const n = closes.length;

  // ATR (14)
  const atrVals: number[] = [];
  for (let i = 1; i < n; i++) {
    atrVals.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i-1]),
      Math.abs(lows[i] - closes[i-1])
    ));
  }
  const atr = b50Mean(atrVals.slice(-14));
  const atrPercent = atr / closes[n-1] * 100;

  // ADX (14)
  const adx = b50ADX(highs, lows, closes, 14);

  // Bollinger Band width (20)
  const sma20 = b50SMA(closes, 20);
  const std20 = b50StdDev(closes, 20);
  const bbUpper = sma20[sma20.length-1] + 2 * std20;
  const bbLower = sma20[sma20.length-1] - 2 * std20;
  const bbWidth = sma20[sma20.length-1] > 0
    ? (bbUpper - bbLower) / sma20[sma20.length-1]
    : 0;

  // MA slope (20-period SMA slope, normalized)
  const maRecent = sma20[sma20.length-1];
  const maOld    = sma20[Math.max(0, sma20.length-6)];
  const maSlope  = maOld > 0 ? (maRecent - maOld) / maOld * 100 : 0;

  // Volatility percentile: current ATR vs 50-period rolling ATR
  const atrHistory: number[] = [];
  for (let i = Math.max(1, n-50); i < n; i++) {
    atrHistory.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i-1]),
      Math.abs(lows[i] - closes[i-1])
    ));
  }
  const atrMed = b50Mean(atrHistory);
  const volPercentile = atrMed > 0 ? Math.min(1, atr / (atrMed * 2)) : 0.5;

  // Volume check: current vs 20-period avg
  const avgVol = b50Mean(volumes.slice(-20));
  const curVol = volumes[n-1] || 0;
  const relVol = avgVol > 0 ? curVol / avgVol : 1;

  // ── Classify Regime ────────────────────────────────────────────────────────
  let type: Boof70Regime['type'];
  let shouldTrade = true;
  let noTradeReason: string | undefined;

  const isExplosive = bbWidth > 0.08 && adx > 35 && volPercentile > 0.85;
  const isHighVol   = volPercentile > 0.75 || atrPercent > 3.5;
  const isLowVol    = volPercentile < 0.20 && bbWidth < 0.02;
  const isTrending  = adx > 22 && Math.abs(maSlope) > 0.15;
  const isRange     = adx < 18 && bbWidth < 0.04;

  if (isExplosive) {
    type = 'EXPLOSIVE';
    // Explosive: trade with reduced size, wide stops
  } else if (isHighVol && !isTrending) {
    type = 'HIGH_VOL';
    // High vol + no trend = choppy spikes — skip
    shouldTrade = false;
    noTradeReason = `HIGH_VOL chop: ATR=${atrPercent.toFixed(2)}% ADX=${adx.toFixed(1)}`;
  } else if (isLowVol) {
    type = 'LOW_VOL';
    // Dead market — not worth scalping
    shouldTrade = false;
    noTradeReason = `LOW_VOL dead zone: bbWidth=${bbWidth.toFixed(4)} volPct=${volPercentile.toFixed(2)}`;
  } else if (isTrending) {
    type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN';
  } else if (isRange) {
    type = 'RANGE';
  } else {
    type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN';
  }

  // Volume filter — skip if volume too thin (except crypto 24/7)
  if (relVol < 0.4 && avgVol > 0) {
    shouldTrade = false;
    noTradeReason = `Low volume: ${curVol.toFixed(0)} = ${(relVol*100).toFixed(0)}% of avg`;
  }

  return { type, adx, atr, atrPercent, bbWidth, maSlope, volatilityPercentile: volPercentile, shouldTrade, noTradeReason };
}

// ── Dynamic TP/SL from ATR × Regime Multiplier ───────────────────────────────
function calcDynamicTPSL(regime: Boof70Regime, entryPrice: number): { tp: number; sl: number; tpPct: number; slPct: number } {
  // Base ATR multipliers per regime
  const multipliers: Record<string, { tp: number; sl: number }> = {
    TREND_UP:   { tp: 3.0, sl: 1.2 },  // Ride the trend, tight SL
    TREND_DOWN: { tp: 3.0, sl: 1.2 },
    RANGE:      { tp: 1.5, sl: 1.0 },  // Mean reversion = smaller targets
    HIGH_VOL:   { tp: 4.0, sl: 2.0 },  // Wide stops, big targets
    LOW_VOL:    { tp: 1.0, sl: 0.8 },  // Tiny moves
    EXPLOSIVE:  { tp: 5.0, sl: 2.5 },  // Let explosive moves run
  };

  const m = multipliers[regime.type] || multipliers['TREND_UP'];
  const atr = regime.atr;

  const tpPrice = entryPrice + atr * m.tp;
  const slPrice = entryPrice - atr * m.sl;
  const tpPct   = ((tpPrice - entryPrice) / entryPrice) * 100;
  const slPct   = ((slPrice - entryPrice) / entryPrice) * 100;

  // Enforce minimum/maximum guardrails
  const tpFinal = Math.max(1.5, Math.min(30, tpPct));
  const slFinal = Math.max(-20, Math.min(-0.8, slPct));

  return {
    tp: entryPrice * (1 + tpFinal / 100),
    sl: entryPrice * (1 + slFinal / 100),
    tpPct: tpFinal,
    slPct: slFinal,
  };
}

// ── Position Sizing: Volatility + Drawdown Aware ─────────────────────────────
function calcPositionSize70(
  regime: Boof70Regime,
  recentWinRate: number,   // 0-1, last 20 trades
  consecutiveLosses: number
): number {
  // Base size by regime
  const baseSizes: Record<string, number> = {
    TREND_UP:   1.0,
    TREND_DOWN: 1.0,
    RANGE:      0.75,  // Smaller in ranging — more uncertain
    HIGH_VOL:   0.5,   // Half size in high vol
    LOW_VOL:    0.5,
    EXPLOSIVE:  0.6,   // Reduced — explosive moves reverse hard
  };
  let size = baseSizes[regime.type] || 1.0;

  // Win rate adjustment
  if (recentWinRate >= 0.60) size *= 1.25;       // Hot streak → slightly more
  else if (recentWinRate < 0.40) size *= 0.60;   // Cold streak → back off
  else if (recentWinRate < 0.30) size *= 0.40;   // Really cold → very small

  // Consecutive loss kill-switch levels
  if (consecutiveLosses >= 5) size *= 0.25;      // 5 losses → quarter size
  else if (consecutiveLosses >= 3) size *= 0.50; // 3 losses → half size

  // Volatility percentile adjustment
  if (regime.volatilityPercentile > 0.80) size *= 0.70;
  else if (regime.volatilityPercentile < 0.25) size *= 0.85;

  return Math.max(0.10, Math.min(1.50, size));
}

// ── Time-Based No-Trade Zone (UTC) ────────────────────────────────────────────
function isNoTradeZone(isCrypto: boolean): { skip: boolean; reason: string } {
  const utcHour = new Date().getUTCHours();
  if (isCrypto) {
    // Crypto: skip 3-5 AM UTC (dead zone, Sunday night US = thin liquidity)
    if (utcHour >= 3 && utcHour < 5) {
      return { skip: true, reason: 'Crypto dead zone: 03-05 UTC thin liquidity' };
    }
    return { skip: false, reason: '' };
  }
  // Stocks: only trade 13:30-20:00 UTC (NYSE hours)
  if (utcHour < 13 || utcHour >= 20) {
    return { skip: true, reason: `Outside NYSE hours (UTC ${utcHour}:00)` };
  }
  return { skip: false, reason: '' };
}

// ── Strategy per Regime ───────────────────────────────────────────────────────
function runRegimeStrategy(
  regime: Boof70Regime,
  candles: any[],
  tradeDirection: string
): { signal: 'buy' | 'sell' | 'none'; reason: string } {
  const closes  = candles.map((c: any) => c.close);
  const highs   = candles.map((c: any) => c.high);
  const lows    = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1);
  const n = closes.length;
  const i = n - 2;

  // ── SHARED: RSI + ATR + ADX for all strategies ──
  const rsi    = calcRSI(closes, 14);
  const curRSI = rsi[rsi.length-2] ?? 50;
  const atrVals: number[] = [];
  for (let j = 1; j < n; j++) atrVals.push(Math.max(highs[j]-lows[j], Math.abs(highs[j]-closes[j-1]), Math.abs(lows[j]-closes[j-1])));
  const atrNow = b50Mean(atrVals.slice(-14));
  const atrAvg = b50Mean(atrVals.slice(-34, -14));

  // Calculate ADX for trend strength confirmation (use b50ADX which exists)
  const curADX = b50ADX(highs, lows, closes, 14);
  // Previous bar ADX for rising check
  const prevHighs = highs.slice(0, -1);
  const prevLows = lows.slice(0, -1);
  const prevCloses = closes.slice(0, -1);
  const prevADX = b50ADX(prevHighs, prevLows, prevCloses, 14);
  const adxRising = curADX > prevADX;

  // ── FLUSH DETECTOR: big body + ATR spike + volume surge ──
  const candleBody    = Math.abs(closes[i] - candles[i].open);
  const candleBodyPct = candles[i].open > 0 ? candleBody / candles[i].open * 100 : 0;
  const atrSpike      = atrNow > atrAvg * 2.0;
  const volAvg        = b50Mean(volumes.slice(-20));
  const volSpike      = volumes[i] > volAvg * 1.8;
  const bearFlush     = closes[i] < candles[i].open && candleBodyPct > 0.12 && atrSpike && volSpike;
  const bullFlush     = closes[i] > candles[i].open && candleBodyPct > 0.12 && atrSpike && volSpike;

  // ── RECOVERY MODE: oversold bounce after flush (below 15m gate) ──
  // Previous candle was a big flush down, RSI now oversold, price crossing back above EMA21
  const ema21Early   = calcEMA(closes, 21);
  const ema21Now     = ema21Early[ema21Early.length-1];
  const ema21Prev    = ema21Early[ema21Early.length-2];
  const prevBearFlush = ((): boolean => {
    if (i < 1) return false;
    const prevBody = Math.abs(closes[i-1] - candles[i-1].open);
    const prevBodyPct = candles[i-1].open > 0 ? prevBody / candles[i-1].open * 100 : 0;
    return closes[i-1] < candles[i-1].open && prevBodyPct > 0.10;
  })();
  const recoveryBuy = curRSI < 30 &&
    closes[i] > ema21Now &&
    closes[i-1] <= ema21Prev &&
    (prevBearFlush || curRSI < 25);  // either prev flush or deeply oversold

  if (regime.type === 'TREND_UP' || regime.type === 'TREND_DOWN' || regime.type === 'EXPLOSIVE') {
    // ── BREAKOUT / MOMENTUM STRATEGY ──
    const ema9  = calcEMA(closes, 9);
    const ema21 = calcEMA(closes, 21);
    const { hist } = calcMACD(closes, 12, 26, 9);
    const histLast = hist[hist.length-1] ?? 0;
    const histPrev = hist[hist.length-2] ?? 0;

    const emaUp          = ema9[ema9.length-1] > ema21[ema21.length-1];
    const emaCrossedUp   = ema9[ema9.length-2] <= ema21[ema21.length-2] && emaUp;
    const emaCrossedDown = ema9[ema9.length-2] >= ema21[ema21.length-2] && !emaUp;
    const macdBull = histLast > 0 && histLast > histPrev;
    const macdBear = histLast < 0 && histLast < histPrev;

    // Continuation entries
    const contBull = emaUp  && macdBull && closes[i] > closes[i-1];
    const contBear = !emaUp && macdBear && closes[i] < closes[i-1];

    // RSI filter: don't buy overbought, don't sell oversold
    const rsiBuyOk  = curRSI > 40 && curRSI < 75;
    const rsiSellOk = curRSI < 60 && curRSI > 25;

    // ── NEW: ADX Rising Confirmation ──
    // Only enter when trend is building (ADX rising), not exhausting
    const adxRisingOk = adxRising || curADX > 30; // Either rising OR very strong trend

    // ── NEW: Pullback Filter ──
    // Wait for small pullback after big move (prevents V-bottom entries)
    // For SELL (puts): wait for 0.3% bounce from recent low before entering
    // For BUY (calls): wait for 0.3% pullback from recent high before entering
    const recentHigh = Math.max(...highs.slice(Math.max(0, i-5), i+1));
    const recentLow  = Math.min(...lows.slice(Math.max(0, i-5), i+1));
    const pullbackToEnterSell = recentLow * 1.003; // Need 0.3% bounce from low
    const pullbackToEnterBuy  = recentHigh * 0.997; // Need 0.3% pullback from high
    const sellPullbackOk = closes[i] > pullbackToEnterSell || (recentHigh - recentLow) < atrNow * 3;
    const buyPullbackOk  = closes[i] < pullbackToEnterBuy || (recentHigh - recentLow) < atrNow * 3;

    let signal: 'buy' | 'sell' | 'none' = 'none';
    let reason = '';

    // Sell slope gate: block sells if long-term EMA still sloping up
    const ema50arr    = calcEMA(closes, 50);
    const ema50slope  = ema50arr[ema50arr.length-1] > ema50arr[Math.max(0, ema50arr.length-4)];
    const sellSlopeOk = !ema50slope;

    // Flush detector overrides — catches sudden moves before ADX confirms
    if (recoveryBuy && tradeDirection !== 'short') {
      signal = 'buy';
      reason = `Boof7.0 RECOVERY_BUY [${regime.type}] rsi=${curRSI.toFixed(1)} ema21cross prevFlush=${prevBearFlush}`;
    } else if (bearFlush && regime.type !== 'TREND_UP' && sellSlopeOk) {
      signal = 'sell';
      reason = `Boof7.0 FLUSH_BEAR [${regime.type}] body=${candleBodyPct.toFixed(2)}% atr=${atrNow.toFixed(3)} vol=${(volumes[i]/volAvg).toFixed(1)}x`;
    } else if (bullFlush && regime.type !== 'TREND_DOWN') {
      signal = 'buy';
      reason = `Boof7.0 FLUSH_BULL [${regime.type}] body=${candleBodyPct.toFixed(2)}% atr=${atrNow.toFixed(3)} vol=${(volumes[i]/volAvg).toFixed(1)}x`;
    } else if ((emaCrossedUp || contBull) && regime.type !== 'TREND_DOWN' && rsiBuyOk && adxRisingOk && buyPullbackOk) {
      signal = 'buy';
      reason = `Boof7.0 BREAKOUT [${regime.type}] ema9=${ema9[ema9.length-1].toFixed(2)} macd=${histLast.toFixed(4)} rsi=${curRSI.toFixed(1)} adx=${curADX.toFixed(1)}${adxRising ? '↑' : '↓'} pullback=ok`;
    } else if ((emaCrossedDown || contBear) && regime.type !== 'TREND_UP' && rsiSellOk && sellSlopeOk && adxRisingOk && sellPullbackOk) {
      signal = 'sell';
      reason = `Boof7.0 BREAKOUT [${regime.type}] ema9=${ema9[ema9.length-1].toFixed(2)} macd=${histLast.toFixed(4)} rsi=${curRSI.toFixed(1)} adx=${curADX.toFixed(1)}${adxRising ? '↑' : '↓'} pullback=ok`;
    } else {
      reason = `Boof7.0 NO_ENTRY [${regime.type}] ema9=${ema9[ema9.length-1].toFixed(2)} macd=${histLast.toFixed(4)} rsi=${curRSI.toFixed(1)}`;
    }

    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason };

  } else if (regime.type === 'RANGE') {
    // ── MEAN REVERSION STRATEGY ──
    const sma20   = b50SMA(closes, 20);
    const std20   = b50StdDev(closes, 20);
    const bbUpper = sma20[sma20.length-1] + 2 * std20;
    const bbLower = sma20[sma20.length-1] - 2 * std20;

    let signal: 'buy' | 'sell' | 'none' = 'none';
    if      (recoveryBuy && tradeDirection !== 'short') signal = 'buy';
    else if (closes[i] <= bbLower * 1.005 && curRSI < 40) signal = 'buy';
    else if (closes[i] >= bbUpper * 0.995 && curRSI > 60) signal = 'sell';

    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 MEAN_REV [RANGE] rsi=${curRSI.toFixed(1)} bb=[${bbLower.toFixed(2)}-${bbUpper.toFixed(2)}]` };

  } else {
    return { signal: 'none', reason: `Boof7.0 NO_STRATEGY for regime=${regime.type}` };
  }
}

// ── MAIN BOOF 7.0 ENTRY POINT ─────────────────────────────────────────────────
function generateSignalBoof70(
  candles: any[],
  tradeDirection = 'both',
  recentWinRate = 0.50,
  consecutiveLosses = 0,
  isCrypto = false
): Boof70Result {
  const closes  = candles.map((c: any) => c.close);
  const highs   = candles.map((c: any) => c.high);
  const lows    = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1000000);
  const n = closes.length;
  const curPrice = closes[n-2] ?? closes[n-1];

  const noResult = (reason: string, kill = false, killReason?: string): Boof70Result => ({
    signal: 'none', price: curPrice, trend: 0, ema: curPrice, adx: 0,
    reason, regime: 'NONE', dynamicTP: 0, dynamicSL: 0, positionSizePct: 0,
    killSwitch: kill, killReason,
    regimeDetails: { type: 'RANGE', adx: 0, atr: 0, atrPercent: 0, bbWidth: 0, maSlope: 0, volatilityPercentile: 0.5, shouldTrade: false }
  });

  if (n < 50) return noResult('Boof 7.0: insufficient data (need 50 bars)');

  // ── 1. KILL-SWITCH CHECK ──────────────────────────────────────────────────
  if (consecutiveLosses >= 7) {
    return noResult(`Kill-switch: ${consecutiveLosses} consecutive losses — paused`, true, `${consecutiveLosses} consecutive losses`);
  }

  // ── 2. TIME-BASED NO-TRADE ZONE ───────────────────────────────────────────
  const timeCheck = isNoTradeZone(isCrypto);
  if (timeCheck.skip) return noResult(`Boof 7.0: ${timeCheck.reason}`);

  // ── 3. REGIME DETECTION ───────────────────────────────────────────────────
  const regime = detectRegime70(highs, lows, closes, volumes);

  if (!regime.shouldTrade) {
    return noResult(`Boof 7.0: skipping — ${regime.noTradeReason}`, false, undefined);
  }

  // ── 4. CHOPPINESS INDEX FILTER ────────────────────────────────────────────
  // Skip trading in choppy markets (same logic as Boof 8.0)
  const ci = calcChoppinessIndex(highs, lows, closes, 14);
  const ciThreshold = isCrypto ? 65 : 55; // Crypto naturally choppier
  if (ci > ciThreshold) {
    return noResult(`Boof 7.0: skipping — too choppy (CI=${ci.toFixed(1)})`, false, undefined);
  }

  // ── 5. DYNAMIC TP/SL ─────────────────────────────────────────────────────
  const { tpPct, slPct } = calcDynamicTPSL(regime, curPrice);

  // ── 6. POSITION SIZING ────────────────────────────────────────────────────
  const positionSizePct = calcPositionSize70(regime, recentWinRate, consecutiveLosses);

  // ── 7. REGIME-BASED STRATEGY ─────────────────────────────────────────────
  const { signal, reason } = runRegimeStrategy(regime, candles, tradeDirection);

  // ── 8. EMA for display ────────────────────────────────────────────────────
  const ema21 = calcEMA(closes, 21);
  const ema21Val = ema21[ema21.length-1] ?? curPrice;

  const marketState = ci > 62 ? 'CHOPPY' : ci < 38 ? 'TRENDING' : 'MIXED';
  const fullReason = `${reason} | CI=${ci.toFixed(1)}[${marketState}] regime=${regime.type} adx=${regime.adx.toFixed(1)} atr=${regime.atrPercent.toFixed(2)}% tp=+${tpPct.toFixed(1)}% sl=${slPct.toFixed(1)}% size=${(positionSizePct*100).toFixed(0)}%`;

  return {
    signal,
    price:  curPrice,
    trend:  regime.maSlope > 0 ? 1 : -1,
    ema:    ema21Val,
    adx:    regime.adx,
    reason: fullReason,
    regime: regime.type,
    dynamicTP: tpPct,
    dynamicSL: slPct,
    positionSizePct,
    killSwitch: false,
    regimeDetails: regime,
    ci,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// BOOF 9.0 — PRECISION SNIPER
// Ultra-strict multi-timeframe confluence: Only 1 trade per 3 days per stock
// Requires: Daily trend + 4h/1h alignment, strong ADX, low CI, volume spike, pullback
// Target: 10-15 high-conviction trades per day across 50 stocks
// ═══════════════════════════════════════════════════════════════════════════════
function generateSignalBoof90(
  candles: any[],
  candles1d: any[],
  candles4h: any[],
  tradeDirection = 'both'
): SignalResult {
  const closes = candles.map((c: any) => c.close);
  const highs = candles.map((c: any) => c.high);
  const lows = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1000000);
  const n = closes.length;
  const curClose = closes[n - 1];

  if (n < 50) return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: 0, reason: 'Boof 9.0: insufficient data' };

  // ── 1. DAILY TREND CONFIRMATION ─────────────────────────────────────────
  const closes1d = candles1d.map((c: any) => c.close);
  const highs1d = candles1d.map((c: any) => c.high);
  const lows1d = candles1d.map((c: any) => c.low);
  const ema50d = calcEMA(closes1d, 50);
  const ema200d = calcEMA(closes1d, 200);
  const curEMA50d = ema50d[ema50d.length - 1];
  const curEMA200d = ema200d[ema200d.length - 1];
  
  // Daily trend: price above both EMAs and EMAs in bullish alignment
  const dailyBullish = curClose > curEMA50d && curClose > curEMA200d && curEMA50d > curEMA200d;
  const dailyBearish = curClose < curEMA50d && curClose < curEMA200d && curEMA50d < curEMA200d;
  
  if (!dailyBullish && !dailyBearish) {
    return { signal: 'none', price: curClose, trend: 0, ema: curEMA50d, adx: 0, reason: 'Boof 9.0: no daily trend alignment' };
  }

  // ── 2. 4H TIMEFRAME ALIGNMENT ─────────────────────────────────────────────
  const closes4h = candles4h.map((c: any) => c.close);
  const ema20_4h = calcEMA(closes4h, 20);
  const curEMA20_4h = ema20_4h[ema20_4h.length - 1];
  const ema50_4h = calcEMA(closes4h, 50);
  const curEMA50_4h = ema50_4h[ema50_4h.length - 1];
  
  const trend4h = dailyBullish ? (curEMA20_4h > curEMA50_4h) : (curEMA20_4h < curEMA50_4h);
  if (!trend4h) {
    return { signal: 'none', price: curClose, trend: 0, ema: curEMA50d, adx: 0, reason: 'Boof 9.0: 4h trend misaligned' };
  }

  // ── 3. STRONG ADX (TREND STRENGTH) ─────────────────────────────────────────
  const { adx: adxArr } = calcDMI(highs, lows, closes, 14);
  const adxVal = adxArr[adxArr.length - 1] || 0;
  if (adxVal < 30) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: ADX too weak (${adxVal.toFixed(1)} < 30)` };
  }

  // ── 4. LOW CHOPPINESS INDEX ───────────────────────────────────────────────
  const ci = calcChoppinessIndex(highs, lows, closes, 14);
  if (ci > 38) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: too choppy (CI=${ci.toFixed(1)})` };
  }

  // ── 5. RSI IN SWEET SPOT ───────────────────────────────────────────────────
  const rsi = calcRSI(closes, 14);
  const curRSI = rsi[rsi.length - 1];
  const rsiOK = dailyBullish ? (curRSI > 40 && curRSI < 70) : (curRSI > 30 && curRSI < 60);
  if (!rsiOK) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: RSI not in sweet spot (${curRSI.toFixed(1)})` };
  }

  // ── 6. MACD HISTOGRAM CONFIRMATION ───────────────────────────────────────
  const { hist } = calcMACD(closes, 12, 26, 9);
  const histLast = hist[hist.length - 1] || 0;
  const histPrev = hist[hist.length - 2] || 0;
  const macdOK = dailyBullish ? (histLast > 0 && histLast > histPrev) : (histLast < 0 && histLast < histPrev);
  if (!macdOK) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: MACD not confirming (hist=${histLast.toFixed(4)})` };
  }

  // ── 7. VOLUME SPIKE CONFIRMATION ───────────────────────────────────────────
  const avgVol = volumes.slice(-20).reduce((a: number, b: number) => a + b, 0) / 20;
  const curVol = volumes[n - 1];
  const volSpike = curVol > avgVol * 1.5; // 50% above average
  if (!volSpike) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: no volume spike` };
  }

  // ── 8. PULLBACK FROM SWING HIGH/LOW ────────────────────────────────────────
  const recentHighs = highs.slice(-20);
  const recentLows = lows.slice(-20);
  const swingHigh = Math.max(...recentHighs);
  const swingLow = Math.min(...recentLows);
  
  const prevClose = closes[n - 2];
  const prev2Close = closes[n - 3];
  const isPullbackUp = curClose < prevClose && prevClose > prev2Close; // Pulled back from high
  const isPullbackDown = curClose > prevClose && prevClose < prev2Close; // Pulled back from low
  
  if (dailyBullish && !isPullbackUp) {
    return { signal: 'none', price: curClose, trend: 1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: no pullback detected' };
  }
  if (dailyBearish && !isPullbackDown) {
    return { signal: 'none', price: curClose, trend: -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: no pullback detected' };
  }

  // ── 9. NOT NEAR RECENT EXTREMES ─────────────────────────────────────────────
  const nearHigh = (swingHigh - curClose) / swingHigh * 100 < 0.3; // Within 0.3% of swing high
  const nearLow = (curClose - swingLow) / swingLow * 100 < 0.3; // Within 0.3% of swing low
  
  if (dailyBullish && nearHigh) {
    return { signal: 'none', price: curClose, trend: 1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: too close to swing high' };
  }
  if (dailyBearish && nearLow) {
    return { signal: 'none', price: curClose, trend: -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: too close to swing low' };
  }

  // ── 10. TIME OF DAY FILTER (avoid open/close volatility) ─────────────────
  const utcHour = new Date().getUTCHours();
  const isMarketHours = utcHour >= 14 && utcHour < 20; // 9:30 AM - 4:00 PM ET
  if (!isMarketHours) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: outside market hours' };
  }

  // ── ALL FILTERS PASSED ─────────────────────────────────────────────────────
  const signal = dailyBullish ? 'buy' : 'sell';
  const fullReason = `Boof 9.0: ${signal.toUpperCase()} | ADX=${adxVal.toFixed(1)} CI=${ci.toFixed(1)} RSI=${curRSI.toFixed(1)} Vol=${(curVol/avgVol).toFixed(1)}x | Daily trend aligned | 4h aligned | Pullback confirmed`;
  
  return {
    signal: signal as 'buy' | 'sell' | 'none',
    price: curClose,
    trend: dailyBullish ? 1 : -1,
    ema: curEMA50d,
    adx: adxVal,
    reason: fullReason
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// BOOF 8.0 — ADAPTIVE AI SCALPER
// Builds on 7.0 with: Choppiness Index, pattern-weight learning, adaptive TP/SL
// The bot reads its own recent trade history and self-tunes TP/SL every run
// ═══════════════════════════════════════════════════════════════════════════════

interface Boof80PatternWeight {
  pattern: string;       // e.g. 'TREND_UP:BREAKOUT', 'RANGE:MEAN_REV'
  wins: number;
  losses: number;
  avgWinPct: number;
  avgLossPct: number;
}

interface Boof80Context {
  recentTrades: { reason: string; pnlPct: number; regime: string }[];  // last 20 trades
  consecutiveLosses: number;
  recentWinRate: number;
  expiryType?: string;  // '0dte', 'weekly', 'monthly' - for adaptive TP/SL
  isCrypto: boolean;
  interval?: string;  // '1m', '5m', '15m', etc - for CI threshold adjustment
}

interface Boof80Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  trend: number;
  ema: number;
  adx: number;
  reason: string;
  regime: string;
  dynamicTP: number;
  dynamicSL: number;
  positionSizePct: number;
  killSwitch: boolean;
  killReason?: string;
  choppiness: number;
  patternWeight: number;
  adaptedFromHistory: boolean;
}

// ── Choppiness Index (14) ─────────────────────────────────────────────────────
// 0-100: < 38 = strong trend, > 62 = choppy/ranging, 38-62 = mixed
function calcChoppinessIndex(highs: number[], lows: number[], closes: number[], period = 14): number {
  const n = closes.length;
  if (n < period + 1) return 50;

  // Sum of ATR over period
  let atrSum = 0;
  for (let i = n - period; i < n; i++) {
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    atrSum += tr;
  }

  // Highest high - Lowest low over period
  const periodHighs = highs.slice(n - period);
  const periodLows  = lows.slice(n - period);
  const hh = Math.max(...periodHighs);
  const ll = Math.min(...periodLows);
  const range = hh - ll;

  if (range === 0) return 50;
  const ci = 100 * Math.log10(atrSum / range) / Math.log10(period);
  return Math.max(0, Math.min(100, ci));
}

// ── Pattern Weight Scorer ─────────────────────────────────────────────────────
// Reads recent trade reasons + PnL and returns a weight (0.5-1.5) for TP/SL scaling
// High weight = pattern has been winning → wider TP, slightly tighter SL
// Low weight  = pattern has been losing  → tighter TP, tighter SL (risk reduction)
function scorePatternWeight(
  patternKey: string,   // e.g. 'TREND_UP:BREAKOUT'
  recentTrades: Boof80Context['recentTrades']
): { weight: number; wins: number; losses: number; avgWin: number; avgLoss: number } {
  if (!recentTrades.length) return { weight: 1.0, wins: 0, losses: 0, avgWin: 0, avgLoss: 0 };

  // Match trades that fired with this pattern (fuzzy match on reason string)
  const [regime, pattern] = patternKey.split(':');
  const patternMatched = recentTrades.filter(t =>
    t.reason?.includes(pattern) && t.regime === regime
  );
  // Fall back to all trades for this regime if not enough pattern-specific data
  const regimeMatched = recentTrades.filter(t => t.regime === regime);
  const matched = patternMatched.length >= 2 ? patternMatched
    : regimeMatched.length >= 2 ? regimeMatched
    : recentTrades;

  if (matched.length < 2) return { weight: 1.0, wins: 0, losses: 0, avgWin: 0, avgLoss: 0 };

  const wins   = matched.filter(t => t.pnlPct > 0);
  const losses = matched.filter(t => t.pnlPct <= 0);
  const winRate = wins.length / matched.length;
  const avgWin  = wins.length  > 0 ? wins.reduce((a, t) => a + t.pnlPct, 0) / wins.length  : 0;
  const avgLoss = losses.length > 0 ? losses.reduce((a, t) => a + t.pnlPct, 0) / losses.length : 0;

  // Expectancy-based weight: (winRate * avgWin + (1-winRate) * avgLoss) normalized
  const expectancy = winRate * avgWin + (1 - winRate) * avgLoss;
  // Map expectancy to weight: expectancy > 2% = 1.4, < -2% = 0.6
  const weight = Math.max(0.5, Math.min(1.5, 1.0 + expectancy / 4));

  return { weight, wins: wins.length, losses: losses.length, avgWin, avgLoss };
}

// ── Adaptive TP/SL ────────────────────────────────────────────────────────────
// Combines regime base, choppiness index, volatility percentile, and pattern weight
// 0DTE AGGRESSIVE MODE: Targets 50-100% moves when trending, skips chop entirely
function calcAdaptiveTPSL(
  regime: Boof70Regime,
  entryPrice: number,
  ci: number,                 // Choppiness Index 0-100
  patternWeight: number,      // 0.5-1.5 from pattern scorer
  recentWinRate: number,      // 0-1
  expiryType: string = 'weekly',  // '0dte', 'weekly', 'monthly'
  interval: string = '5m'      // '1m', '5m', '15m', etc - for CI threshold
): { tpPct: number; slPct: number; trailingSlPct: number; shouldTrade: boolean; reason?: string } {
  const is0DTE = expiryType === '0dte';

  // ── 0DTE AGGRESSIVE: Skip entirely if choppy ──
  // Timeframe-aware: 1m is stricter (55), 5m+ is looser (62) for learning
  const ciSkipThreshold = interval === '1m' ? 55 : 62;
  if (is0DTE && ci > ciSkipThreshold) {
    return { tpPct: 0, slPct: 0, trailingSlPct: 0, shouldTrade: false, reason: `0DTE skip: too choppy (CI=${ci.toFixed(1)}, ${interval})` };
  }

  // Base ATR multipliers per regime
  // 0DTE AGGRESSIVE: Much wider TP multipliers for bigger moves
  const baseMultipliers: Record<string, { tp: number; sl: number }> = is0DTE
    ? {  // 0DTE AGGRESSIVE MODE - targeting 50-100% moves
        TREND_UP:   { tp: 8.0, sl: 1.5 },   // Was 3.0 → now 8.0 (2.6x wider)
        TREND_DOWN: { tp: 8.0, sl: 1.5 },
        RANGE:      { tp: 4.0, sl: 1.2 },   // Skip range in 0DTE (below)
        HIGH_VOL:   { tp: 10.0, sl: 2.5 }, // Volatile = bigger moves possible
        LOW_VOL:    { tp: 6.0, sl: 1.0 },
        EXPLOSIVE:  { tp: 12.0, sl: 3.0 }, // EXPLOSIVE = 100%+ target
      }
    : {  // Normal mode (weekly/monthly)
        TREND_UP:   { tp: 3.0, sl: 1.2 },
        TREND_DOWN: { tp: 3.0, sl: 1.2 },
        RANGE:      { tp: 1.5, sl: 1.0 },
        HIGH_VOL:   { tp: 4.0, sl: 2.0 },
        LOW_VOL:    { tp: 1.0, sl: 0.8 },
        EXPLOSIVE:  { tp: 5.0, sl: 2.5 },
      };

  // 0DTE: Skip RANGE regime entirely (not worth theta burn)
  if (is0DTE && regime.type === 'RANGE') {
    return { tpPct: 0, slPct: 0, trailingSlPct: 0, shouldTrade: false, reason: '0DTE skip: range-bound market' };
  }

  const m = baseMultipliers[regime.type] || baseMultipliers['TREND_UP'];

  // ── CI adjustment: EXTREME scaling based on trend strength ──
  // CI 0-20: Strong trend → MASSIVE TP (2-3x base)
  // CI 20-35: Moderate trend → Bigger TP (1.5-2x base)
  // CI 35-50: Weak trend → Normal TP (0.8-1.2x base)
  // CI 50-60: Choppy → TIGHT TP (0.4-0.6x base)
  // CI 60+: Skip entirely (handled above)
  const ciScale = is0DTE
    ? (ci < 20 ? 2.50      // EXTREME trend: 2.5x wider TP
       : ci < 30 ? 2.00     // Strong trend: 2x wider TP
       : ci < 40 ? 1.50     // Moderate trend: 1.5x wider TP
       : ci < 50 ? 1.00     // Normal: base TP
       : ci < 55 ? 0.50     // Getting choppy: tight TP
       : 0.40)              // Very choppy: ultra tight before skip kicks in
    : (ci > 70 ? 0.50       // EXTREME chop for weekly: 0.5x tighter
       : ci > 62 ? 0.70     // Choppy: 0.7x tighter
       : ci < 25 ? 1.80     // Strong trend: 1.8x wider
       : ci < 38 ? 1.30     // Moderate trend: 1.3x wider
       : 1.0 + (50 - ci) / 100);  // Gradual scale between

  // ── Volatility percentile adjustment ──
  const volScale = regime.volatilityPercentile > 0.75 ? 1.25
                 : regime.volatilityPercentile < 0.25 ? 0.80
                 : 1.0;

  // ── Win rate adjustment ──
  // 0DTE: Hot streak = even wider TP (let winners run to 100%+)
  const winRateTpScale = is0DTE
    ? (recentWinRate > 0.55 ? 1.30 : recentWinRate < 0.30 ? 0.60 : 1.0)
    : (recentWinRate > 0.60 ? 1.15 : recentWinRate < 0.35 ? 0.75 : 1.0);

  // ── Combine all factors ──
  const tpMultiplier = m.tp * ciScale * volScale * patternWeight * winRateTpScale;
  const slMultiplier = m.sl * ciScale * volScale;

  const atr = regime.atr;
  const tpPrice = entryPrice + atr * tpMultiplier;
  const slPrice = entryPrice - atr * slMultiplier;
  const tpPct   = ((tpPrice - entryPrice) / entryPrice) * 100;
  const slPct   = ((slPrice - entryPrice) / entryPrice) * 100;

  // 0DTE Trailing SL: trail tighter once +25% in profit (protect gains)
  const trailingSlPct = is0DTE
    ? (atr * 1.0 / entryPrice) * 100  // Wider initial trail for 0DTE volatility
    : (atr * 0.5 / entryPrice) * 100;

  // Cap TP: Center on 50% for average day (CI ~40), scale from 20% to 100%
  const maxTp = is0DTE
    ? (ci < 20 ? 100      // Extreme trend: 100%
       : ci < 30 ? 80      // Strong trend: 80%
       : ci < 40 ? 65      // Moderate trend: 65%
       : ci < 50 ? 50      // Average day: 50% (target)
       : ci < 55 ? 35      // Weak trend: 35%
       : 25)               // Choppy: 25%
    : (ci < 25 ? 80 : 50); // Weekly: 50-80%
  const minTp = is0DTE
    ? (ci > 55 ? 20       // Choppy min: 20%
       : ci > 50 ? 25      // Weak min: 25%
       : ci > 40 ? 40      // Below average: 40%
       : 45)               // Strong trend min: 45%
    : (ci > 70 ? 20 : 40); // Weekly min: 20-40%

  // SL scales with CI: -15% (strong trend) to -25% (choppy)
  // CI < 50: -15% to -20%, CI 50-55: -20%, CI > 55: -25% or skip

  return {
    tpPct:         Math.max(minTp, Math.min(maxTp, tpPct)),
    // SL centered on -20% for 0DTE, scales -10% to -30%
    slPct:         Math.max(is0DTE ? -30 : -25, Math.min(is0DTE ? -15 : -10, slPct)),
    trailingSlPct: Math.max(0.5, Math.min(5.0, trailingSlPct)),
    shouldTrade:   true,
  };
}

// ── MAIN BOOF 8.0 ENTRY POINT ─────────────────────────────────────────────────
function generateSignalBoof80(
  candles: any[],
  tradeDirection = 'both',
  context: Boof80Context = { recentTrades: [], consecutiveLosses: 0, recentWinRate: 0.5, isCrypto: false }
): Boof80Result {
  const closes  = candles.map((c: any) => c.close);
  const highs   = candles.map((c: any) => c.high);
  const lows    = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1000000);
  const n = closes.length;
  const curPrice = closes[n-2] ?? closes[n-1];
  const { recentTrades, consecutiveLosses, recentWinRate, isCrypto } = context;

  const noResult = (reason: string, kill = false, killReason?: string): Boof80Result => ({
    signal: 'none', price: curPrice, trend: 0, ema: curPrice, adx: 0,
    reason, regime: 'NONE', dynamicTP: 0, dynamicSL: 0, positionSizePct: 0,
    killSwitch: kill, killReason, choppiness: 50, patternWeight: 1.0, adaptedFromHistory: false
  });

  if (n < 50) return noResult('Boof 8.0: insufficient data (need 50 bars)');
  if (consecutiveLosses >= 7) return noResult(`Kill-switch: ${consecutiveLosses} consecutive losses`, true, `${consecutiveLosses} consecutive losses`);

  const timeCheck = isNoTradeZone(isCrypto);
  if (timeCheck.skip) return noResult(`Boof 8.0: ${timeCheck.reason}`);

  // ── 1. REGIME DETECTION (reuse 7.0) ──────────────────────────────────────
  const regime = detectRegime70(highs, lows, closes, volumes);
  if (!regime.shouldTrade) return noResult(`Boof 8.0: skipping — ${regime.noTradeReason}`);

  // ── 2. CHOPPINESS INDEX ───────────────────────────────────────────────────
  const ci = calcChoppinessIndex(highs, lows, closes, 14);
  const marketState = ci > 62 ? 'CHOPPY' : ci < 38 ? 'TRENDING' : 'MIXED';

  // Skip trading in extremely choppy markets (CI > 72) unless explosive
  if (ci > 72 && regime.type !== 'EXPLOSIVE') {
    return noResult(`Boof 8.0: market too choppy (CI=${ci.toFixed(1)}) — skipping`);
  }

  // ── 3. SIGNAL GENERATION (reuse 7.0 strategy) ────────────────────────────
  const { signal, reason } = runRegimeStrategy(regime, candles, tradeDirection);
  if (signal === 'none') {
    return noResult(`Boof 8.0 NO_ENTRY [${regime.type}] CI=${ci.toFixed(1)} ${marketState}`);
  }

  // ── 4. PATTERN WEIGHT SCORING ─────────────────────────────────────────────
  // Extract pattern label from reason string (e.g. "BREAKOUT", "MEAN_REV", "FLUSH_BULL")
  const patternMatch = reason.match(/Boof7\.0\s+(\w+)/);
  const patternLabel = patternMatch?.[1] ?? 'UNKNOWN';
  const patternKey   = `${regime.type}:${patternLabel}`;
  const { weight: patternWeight, wins: pWins, losses: pLosses } = scorePatternWeight(patternKey, recentTrades);
  const adaptedFromHistory = recentTrades.length >= 2;

  // Block signal if pattern has been consistently losing
  // Learning phase: lower threshold (0.55) until 10+ trades, then tighten (0.65)
  const weightThreshold = recentTrades.length >= 10 ? 0.65 : 0.55;
  if (patternWeight < weightThreshold && recentTrades.length >= 5) {
    return noResult(`Boof 8.0: pattern ${patternKey} underperforming (weight=${patternWeight.toFixed(2)}, ${pWins}W/${pLosses}L, thresh=${weightThreshold}) — skipping`);
  }

  // ── 5. ADAPTIVE TP/SL ─────────────────────────────────────────────────────
  const interval = context.interval || '5m';
  const { tpPct, slPct, trailingSlPct, shouldTrade: tpSlOk, reason: tpSlReason } = calcAdaptiveTPSL(regime, curPrice, ci, patternWeight, recentWinRate, context.expiryType || 'weekly', interval);

  // 0DTE: Skip if adaptive TP/SL says conditions aren't right
  if (!tpSlOk) {
    return noResult(`Boof 8.0: ${tpSlReason}`, false, tpSlReason);
  }

  // ── 6. POSITION SIZING (reuse 7.0) ────────────────────────────────────────
  const positionSizePct = calcPositionSize70(regime, recentWinRate, consecutiveLosses);

  // ── 7. EMA for display ────────────────────────────────────────────────────
  const ema21 = calcEMA(closes, 21);
  const ema21Val = ema21[ema21.length-1] ?? curPrice;

  const fullReason = `${reason} | CI=${ci.toFixed(1)}[${marketState}] pw=${patternWeight.toFixed(2)}(${pWins}W/${pLosses}L) tp=+${tpPct.toFixed(1)}% sl=${slPct.toFixed(1)}% trail=${trailingSlPct.toFixed(1)}% size=${(positionSizePct*100).toFixed(0)}% adapted=${adaptedFromHistory}`;

  return {
    signal,
    price:    curPrice,
    trend:    regime.maSlope > 0 ? 1 : -1,
    ema:      ema21Val,
    adx:      regime.adx,
    reason:   fullReason,
    regime:   regime.type,
    dynamicTP:  tpPct,
    dynamicSL:  slPct,
    positionSizePct,
    killSwitch: false,
    choppiness: ci,
    patternWeight,
    adaptedFromHistory,
  };
}

// ─────────────────────────────────────────────
// FETCH CANDLES (Yahoo Finance - Live)
// ─────────────────────────────────────────────

interface Candle { time: number; open: number; high: number; low: number; close: number; volume?: number; }

async function fetchCandles(symbol: string, interval = '1h', bars = 150, userId?: string): Promise<Candle[]> {
  const isCrypto = symbol.includes('-USD') || symbol.includes('/USD');
  const isFutures = symbol.includes('=F');
  
  // Fix renamed/delisted Yahoo tickers
  const tickerFixMap: Record<string, string> = {
    'MATIC-USD': 'POL-USD',  // MATIC renamed to POL
  };
  
  // Use Alpaca for crypto, Yahoo for stocks
  if (isCrypto) {
    // Fetch from Alpaca for crypto
    try {
      let alpacaKey, alpacaSecret;
      
      // Try to get from database first (user's broker credentials)
      if (userId) {
        const { data: ac } = await supabase.from('broker_credentials').select('credentials').eq('user_id', userId).eq('broker', 'alpaca').maybeSingle();
        alpacaKey = ac?.credentials?.api_key;
        alpacaSecret = ac?.credentials?.secret_key;
      }
      
      // Fallback to environment variables
      if (!alpacaKey || !alpacaSecret) {
        alpacaKey = Deno.env.get('ALPACA_API_KEY') || '';
        alpacaSecret = Deno.env.get('ALPACA_API_SECRET') || '';
      }
      
      if (!alpacaKey || !alpacaSecret) {
        console.warn('[AutoBot] Alpaca credentials not found, falling back to Yahoo for crypto');
        // Fall through to Yahoo
      } else {
        // Map interval to Alpaca format
        const alpacaIntervalMap: Record<string, string> = {
          '1m': '1Min', '2m': '2Min', '5m': '5Min', '15m': '15Min', '30m': '30Min',
          '1h': '1Hour', '4h': '4Hour', '1d': '1Day'
        };
        const alpacaInterval = alpacaIntervalMap[interval] || '1Hour';
        
        // Alpaca uses different symbol format for crypto (e.g., BTC/USD instead of BTC-USD)
        const alpacaSymbol = symbol.replace('-USD', '/USD');
        
        const alpacaUrl = `https://data.alpaca.markets/v2/stocks/${alpacaSymbol}/bars?timeframe=${alpacaInterval}&limit=${bars}&adjustment=raw&feed=iex`;
        
        console.log(`[AutoBot] Fetching Alpaca candles for ${alpacaSymbol} (${alpacaInterval})`);
        
        const alpacaRes = await fetch(alpacaUrl, {
          headers: {
            'APCA-API-KEY-ID': alpacaKey,
            'APCA-API-SECRET-KEY': alpacaSecret
          }
        });
        
        if (alpacaRes.ok) {
          const data = await alpacaRes.json();
          const barsData = data?.bars;
          
          if (barsData && barsData.length > 0) {
            const candles: Candle[] = barsData.map((bar: any) => ({
              time: new Date(bar.t).getTime(),
              open: bar.o,
              high: bar.h,
              low: bar.l,
              close: bar.c,
              volume: bar.v
            }));
            
            console.log(`[AutoBot] Alpaca ${symbol}: ${candles.length} candles, latest close=$${candles[candles.length-1]?.close?.toFixed(2)}`);
            return candles;
          }
        }
        
        console.warn(`[AutoBot] Alpaca: no data for ${symbol}, falling back to Yahoo`);
        // Fall through to Yahoo
      }
    } catch (err) {
      console.error(`[AutoBot] Alpaca candle fetch error for ${symbol}:`, err);
      console.warn('[AutoBot] Falling back to Yahoo Finance');
      // Fall through to Yahoo
    }
  }
  
  // Fetch from Yahoo Finance for stocks (and fallback for crypto)
  try {
    const yahooSymbol = tickerFixMap[symbol.toUpperCase()] || symbol;
    
    // Map interval to Yahoo Finance format
    const yahooIntervalMap: Record<string, string> = {
      '1m': '1m', '2m': '2m', '5m': '5m', '15m': '15m', '30m': '30m',
      '1h': '1h', '4h': '4h', '1d': '1d', '1w': '1wk'
    };
    const yahooInterval = yahooIntervalMap[interval] || '1h';
    
    // Yahoo Finance requires range based on interval
    const rangeMap: Record<string, string> = {
      '1m': '5d', '2m': '5d', '5m': '5d', '15m': '5d', '30m': '1mo',
      '1h': '1mo', '4h': '3mo', '1d': '1y', '1wk': '5y'
    };
    const range = rangeMap[yahooInterval] || '1mo';
    
    const yahooUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol)}?interval=${yahooInterval}&range=${range}`;
    console.log(`[AutoBot] Fetching Yahoo Finance candles for ${yahooSymbol} (${yahooInterval}, ${range})`);
    
    const yahooRes = await fetch(yahooUrl, {
      headers: { 'User-Agent': 'Mozilla/5.0' }
    });
    
    if (yahooRes.ok) {
      const data = await yahooRes.json();
      const result = data?.chart?.result?.[0];
      const timestamps = result?.timestamp;
      const quote = result?.indicators?.quote?.[0];
      
      if (timestamps && quote && timestamps.length > 0) {
        const candles: Candle[] = [];
        for (let i = 0; i < timestamps.length; i++) {
          const o = quote.open?.[i];
          const h = quote.high?.[i];
          const l = quote.low?.[i];
          const c = quote.close?.[i];
          if (o != null && h != null && l != null && c != null) {
            candles.push({
              time: timestamps[i] * 1000,
              open: o, high: h, low: l, close: c
            });
          }
        }
        
        // Return last N bars
        const trimmed = candles.slice(-bars);
        if (trimmed.length > 0) {
          console.log(`[AutoBot] Yahoo Finance ${symbol}: ${trimmed.length} real candles, latest close=$${trimmed[trimmed.length-1]?.close?.toFixed(2)}`);
          return trimmed;
        }
      }
    }
    
    console.warn(`[AutoBot] Yahoo Finance: no data for ${symbol}, skipping`);
    throw new Error(`No candle data available for ${symbol}`);
    
  } catch (err) {
    console.error(`[AutoBot] Yahoo candle fetch error for ${symbol}:`, err);
    throw err;
  }
}

// ─────────────────────────────────────────────
// SIGNAL GENERATION
// ─────────────────────────────────────────────

interface SignalResult {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  trend: number;
  ema: number;
  adx: number;
  reason: string;
  regime?: string;
  rsi?: number;
  slope?: number;
  atr?: number;
  compositeScore?: number;
  ev?: number;
  stopLoss?: number;
  takeProfit?: number;
}

function calcVWAP(candles: any[]): number {
  let cumTPV = 0, cumVol = 0;
  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    const vol = c.volume ?? 1;
    cumTPV += tp * vol;
    cumVol += vol;
  }
  return cumVol > 0 ? cumTPV / cumVol : 0;
}

function generateSignal(candles: Candle[], settings: BotSettings): SignalResult {
  const highs  = candles.map(c => c.high);
  const lows   = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const n = closes.length;
  const tradeDirection = settings.tradeDirection || 'both';

  // Calculate EMA50
  const emaArr = calcEMA(closes, 50);

  // Calculate Supertrend components
  const atrPeriod = 10;
  const stMultiplier = 3;
  const hl2 = highs.map((h, i) => (h + lows[i]) / 2);
  const atr = calcATR(highs, lows, closes, atrPeriod);

  // Calculate Supertrend upper and lower bands
  const stUpper: number[] = new Array(n).fill(NaN);
  const stLower: number[] = new Array(n).fill(NaN);
  const supertrend: number[] = new Array(n).fill(0);

  for (let i = atrPeriod; i < n; i++) {
    stUpper[i] = hl2[i] + stMultiplier * atr[i];
    stLower[i] = hl2[i] - stMultiplier * atr[i];

    // Initialize Supertrend
    if (i === atrPeriod) {
      supertrend[i] = closes[i - 1] <= stUpper[i - 1] ? stUpper[i] : stLower[i];
    } else {
      // Update Supertrend
      if (closes[i - 1] <= stUpper[i - 1]) {
        supertrend[i] = stUpper[i];
      } else {
        supertrend[i] = stLower[i];
      }
    }
  }

  // Calculate ADX (14-period)
  const { adx } = calcDMI(highs, lows, closes, 14);

  // Current bar (last completed)
  const i = n - 2;
  const curClose = closes[i];
  const curEma = emaArr[i];
  const curSupertrend = supertrend[i];
  const curAdx = adx[i];

  const adxThreshold = 25;

  // Signal logic matching Python: close > EMA50, close > Supertrend, ADX > 25
  const longOK = curClose > curEma && curClose > curSupertrend && curAdx > adxThreshold;
  const shortOK = curClose < curEma && curClose < curSupertrend && curAdx > adxThreshold;

  // Replay state to track position
  let inLong = false;
  let inShort = false;
  for (let j = 50; j < i; j++) {
    const longCond = closes[j] > emaArr[j] && closes[j] > supertrend[j] && adx[j] > adxThreshold;
    const shortCond = closes[j] < emaArr[j] && closes[j] < supertrend[j] && adx[j] > adxThreshold;
    if (longCond && !inLong) { inLong = true; inShort = false; }
    else if (shortCond && !inShort) { inShort = true; inLong = false; }
  }

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `close=${curClose.toFixed(2)}, ema50=${curEma?.toFixed(2)}, supertrend=${curSupertrend?.toFixed(2)}, adx=${curAdx?.toFixed(1)}, inLong=${inLong}, inShort=${inShort}`;

  if (!inLong && longOK) {
    signal = 'buy';
    reason = `Boof 1.0 BUY. ${reason}`;
  } else if (!inShort && shortOK) {
    signal = 'sell';
    reason = `Boof 1.0 SELL. ${reason}`;
  }

  // Apply trade direction filter
  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  return {
    signal,
    price: curClose,
    trend: curClose > curEma ? 1 : -1,
    ema: curEma,
    adx: curAdx,
    reason
  };
}

// ─────────────────────────────────────────────
// TASTYTRADE ORDER PLACEMENT
// ─────────────────────────────────────────────

interface BotSettings {
  atrLength: number;
  atrMultiplier: number;
  emaLength: number;
  adxLength: number;
  adxThreshold: number;
  symbol: string;
  dollarAmount: number;
  interval: string;
  tradeDirection: string;
}

async function placeTastyOrder(
  supabase: ReturnType<typeof createClient>,
  userId: string,
  action: 'buy' | 'sell',
  symbol: string,
  price: number,
  dollarAmount: number
) {
  const { data: credRow } = await supabase
    .from('broker_credentials')
    .select('credentials')
    .eq('user_id', userId)
    .eq('broker', 'tastytrade')
    .maybeSingle();

  if (!credRow?.credentials) throw new Error('No Tastytrade credentials found');

  const { username, password, remember_token } = credRow.credentials;
  let sessionToken: string = credRow.credentials.session_token;
  let accountNumber: string = credRow.credentials.account_number;
  let sessionValid = false;

  // Try existing session
  if (sessionToken) {
    try {
      const testRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
        headers: { Authorization: sessionToken }
      });
      if (testRes.ok) {
        const tj = await testRes.json();
        if (tj?.data?.items?.[0]?.account?.['account-number']) {
          sessionValid = true;
          accountNumber = tj.data.items[0].account['account-number'];
        }
      }
    } catch (_) { sessionValid = false; }
  }

  // Re-authenticate if needed
  if (!sessionValid) {
    const sessRes = await fetch('https://api.tastytrade.com/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(
        remember_token
          ? { login: username, password, 'remember-me': true, 'remember-token': remember_token }
          : { login: username, password, 'remember-me': true }
      )
    });
    const sessJson = await sessRes.json();
    sessionToken = sessJson?.data?.['session-token'];
    if (!sessionToken) throw new Error('Tastytrade auth failed');

    const acctRes = await fetch('https://api.tastytrade.com/customers/me/accounts', {
      headers: { Authorization: sessionToken }
    });
    const acctJson = await acctRes.json();
    accountNumber = acctJson?.data?.items?.[0]?.account?.['account-number'];
    if (!accountNumber) throw new Error('No account number found');

    await supabase.from('broker_credentials').update({
      credentials: { ...credRow.credentials, session_token: sessionToken, account_number: accountNumber, session_created_at: new Date().toISOString() }
    }).eq('user_id', userId).eq('broker', 'tastytrade');
  }

  // Calculate quantity from dollar amount
  const quantity = Math.max(1, Math.round(dollarAmount / price));
  const orderAction = action === 'buy' ? 'Buy to Open' : 'Sell to Close';

  const orderRes = await fetch(`https://api.tastytrade.com/accounts/${accountNumber}/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: sessionToken },
    body: JSON.stringify({
      'order-type': 'Market',
      'time-in-force': 'Day',
      legs: [{ 'instrument-type': 'Equity', symbol, quantity, action: orderAction }]
    })
  });

  const orderJson = await orderRes.json();
  console.log('[AutoBot] Order response:', JSON.stringify(orderJson));
  return { orderId: orderJson?.data?.order?.id, quantity, orderJson };
}

// ─────────────────────────────────────────────
// MAIN HANDLER
// ─────────────────────────────────────────────

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  const supabaseGET = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  );

  // GET /portfolio-value?bot_id=xxx — cash + current value of open stock positions
  if (req.method === 'GET') {
    const url = new URL(req.url);
    const botId = url.searchParams.get('bot_id');
    if (!botId) return new Response(JSON.stringify({ error: 'bot_id required' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    const { data: bot } = await supabaseGET.from('stock_bots').select('paper_balance, user_id').eq('id', botId).single();
    const cash = Number(bot?.paper_balance ?? 100000);

    // Fetch open (filled, no pnl) trades
    const { data: openTrades } = await supabaseGET.from('stock_trades').select('*').eq('bot_id', botId).eq('status', 'filled').is('pnl', null);
    let openValue = 0;
    if (openTrades && openTrades.length > 0) {
      for (const t of openTrades) {
        try {
          const candles = await fetchCandles(t.symbol, '1h', 5, bot?.user_id as string);
          const price = candles.length ? candles[candles.length - 1].close : Number(t.price);
          openValue += price * Number(t.quantity);
        } catch (_) { openValue += Number(t.price) * Number(t.quantity); }
      }
    }

    return new Response(JSON.stringify({ cash, open_value: openValue, total: cash + openValue }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  // Allow cron (no auth header) OR user JWT OR service role key
  const authHeader = req.headers.get('Authorization') || '';
  const anonKey = Deno.env.get('SUPABASE_ANON_KEY') || '';
  const serviceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '';
  const isCronOrInternal = authHeader === '' || authHeader === `Bearer ${serviceKey}` || authHeader === `Bearer ${anonKey}`;
  if (!isCronOrInternal) {
    // Validate as user JWT — just allow it through, service role client handles data access
    const bearerToken = authHeader.replace('Bearer ', '');
    if (!bearerToken || bearerToken.split('.').length !== 3) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  );

  try {
    // Can be triggered by cron OR manually with { bot_id, user_id } in body
    let targetBotId: string | null = null;
    let targetUserId: string | null = null;

    if (req.method === 'POST') {
      try {
        const body = await req.json();
        targetBotId = body.bot_id || body.system_id || null;
        targetUserId = body.user_id || null;
      } catch (_) {}
    }

    // Load all auto-bot enabled stock bots (or just the one requested)
    let query = supabase
      .from('stock_bots')
      .select('*')
      .eq('enabled', true)
      .eq('auto_submit', true);

    if (targetBotId) query = query.eq('id', targetBotId);
    if (targetUserId)   query = query.eq('user_id', targetUserId);

    const { data: bots, error: botErr } = await query;
    if (botErr) throw botErr;
    if (!bots || bots.length === 0) {
      return new Response(JSON.stringify({ message: 'No active stock bots found' }), {
        status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
    console.log(`[AutoBot] Found ${bots.length} active stock bots`);

    // ── Symbol lists for scan mode ──────────────────────────────────────────
    const SCAN_STOCKS = [
      // Mega-cap / most liquid
      'AAPL','MSFT','AMZN','NVDA','TSLA','GOOG','GOOGL','META','NFLX','BRK-B',
      'JPM','BAC','WFC','V','MA','PG','KO','PFE','UNH','HD',
      // Tech / consumer
      'INTC','CSCO','ADBE','CRM','ORCL','AMD','QCOM','TXN','IBM','AVGO',
      // Energy / industrial
      'XOM','CVX','BA','CAT','MMM','GE','HON','LMT','NOC','DE',
      // Financial / banking
      'C','GS','MS','AXP','BLK','SCHW','BK','SPGI','ICE',
      // Healthcare / pharma
      'MRK','ABBV','AMGN','BMY','LLY','GILD','JNJ','REGN','VRTX','BIIB',
      // Consumer / retail
      'WMT','COST','TGT','LOW','MCD','SBUX','NKE','BKNG',
      // Communications / internet
      'SNAP','UBER','LYFT','SPOT','ZM','DOCU','PINS','ROKU','SHOP',
      // Misc large caps
      'CVS','TMO','MDT','ISRG','F','GM',
    ];
    // Crypto: all with consistent daily volume > $100M
    const SCAN_CRYPTO = [
      'BTC-USD',   // ~$30B+ daily
      'ETH-USD',   // ~$15B+ daily
      'SOL-USD',   // ~$3B+ daily
      'XRP-USD',   // ~$2B+ daily
      'BNB-USD',   // ~$1B+ daily
      'DOGE-USD',  // ~$1B+ daily
      'ADA-USD',   // ~$500M+ daily
      'AVAX-USD',  // ~$500M+ daily
      'LINK-USD',  // ~$500M+ daily
      'MATIC-USD', // ~$400M+ daily
      'LTC-USD',   // ~$400M+ daily
      'UNI-USD',   // ~$200M+ daily
      'SHIB-USD',  // ~$300M+ daily
      'TON-USD',   // ~$300M+ daily
      'DOT-USD',   // ~$200M+ daily
      'TRX-USD',   // ~$500M+ daily
      'NEAR-USD',  // ~$200M+ daily
      'APT-USD',   // ~$200M+ daily
      'ARB-USD',   // ~$150M+ daily
      'SUI-USD',   // ~$500M+ daily
    ];

    // Top 20 Futures (liquid, trade overnight)
    const SCAN_FUTURES = [
      'ES=F',    // E-mini S&P 500
      'NQ=F',    // E-mini NASDAQ
      'YM=F',    // E-mini Dow
      'CL=F',    // Crude Oil WTI
      'GC=F',    // Gold
      'SI=F',    // Silver
      'ZN=F',    // 10-Year T-Note
      'ZB=F',    // 30-Year T-Bond
      'ZF=F',    // 5-Year T-Note
      '6E=F',    // Euro FX
      '6J=F',    // Japanese Yen
      '6B=F',    // British Pound
      '6C=F',    // Canadian Dollar
      '6A=F',    // Australian Dollar
      'HG=F',    // Copper
      'NG=F',    // Natural Gas
      'ZW=F',    // Wheat
      'ZC=F',    // Corn
      'ZS=F',    // Soybeans
      'ZL=F',    // Soybean Oil
    ];

    const SCAN_ALL = [...SCAN_STOCKS, ...SCAN_CRYPTO, ...SCAN_FUTURES];

    // ── Per-symbol processing helper ─────────────────────────────────────────
    async function processSymbol(bot: Record<string,unknown>, sym: string, settings: BotSettings): Promise<object> {
      try {
        const candles = await fetchCandles(sym, settings.interval, 150, bot.user_id as string);
        if (candles.length < 60) return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Not enough candle data' };

        // Check database for REAL open trade on this symbol (across ALL bots for this user)
        const { data: realOpenTrade } = await supabase.from('trades')
          .select('id, action, bot_id').eq('user_id', bot.user_id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'filled').is('pnl', null)
          .limit(1).maybeSingle();
        const hasRealPosition = !!realOpenTrade;
        const isOwnPosition = realOpenTrade?.bot_id === bot.id;
        
        // Skip if another bot already has an open position on this symbol
        if (hasRealPosition && !isOwnPosition) {
          return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Another bot already has open ${sym} position` };
        }
        
        // Cooldown: don't re-enter if a trade was recently closed on this symbol (any bot, same user)
        const cooldownMinutes = Math.max(Number(settings.interval?.replace(/[^\d]/g, '')) || 5, 5);
        const cooldownAgo = new Date(Date.now() - cooldownMinutes * 60 * 1000).toISOString();
        const { data: recentlyClosed } = await supabase.from('trades')
          .select('id').eq('user_id', bot.user_id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'closed')
          .gte('closed_at', cooldownAgo)
          .limit(1).maybeSingle();
        if (recentlyClosed && !hasRealPosition) {
          return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Cooldown: trade closed within ${cooldownMinutes}m` };
        }

        const overrideSettings = { ...settings, symbol: sym };
        const botSignal = (bot.bot_signal as string) || 'supertrend';
        const tradeDirection = settings.tradeDirection || 'both';
        let signalResult: SignalResult;
        if (botSignal === 'rsi_macd') {
          signalResult = generateSignalRSIMACD(candles, tradeDirection);
        } else if (botSignal === 'boof15') {
          signalResult = generateSignalBoof15(candles, tradeDirection, sym);
        } else if (botSignal === 'boof20') {
          signalResult = generateSignalBoof20(candles, tradeDirection, 0.001, -0.001);
        } else if (botSignal === 'boof30') {
          signalResult = generateSignalBoof30(candles, tradeDirection);
        } else if (botSignal === 'boof50') {
          signalResult = generateSignalBoof50(candles, tradeDirection);
        } else if (botSignal === 'boof60') {
          const [c1h, c15m, c1m] = await Promise.all([
            fetchCandles(sym, '1h',  50, bot.user_id as string),
            fetchCandles(sym, '15m', 50, bot.user_id as string),
            fetchCandles(sym, '1m',  60, bot.user_id as string),
          ]);
          const isCryptoSym = sym.includes('-USD') || sym.includes('/USD');
          signalResult = generateSignalBoof60(candles, c1h, c15m, c1m, tradeDirection, isCryptoSym);
        } else if (botSignal === 'boof70') {
          // Fetch last 20 closed trades for this bot to compute win rate + consecutive losses
          const { data: recentTrades } = await supabase
            .from('trades')
            .select('pnl')
            .eq('bot_id', bot.id)
            .eq('status', 'closed')
            .not('pnl', 'is', null)
            .order('closed_at', { ascending: false })
            .limit(20);
          const pnls = (recentTrades || []).map((t: any) => Number(t.pnl));
          const wins = pnls.filter((p: number) => p > 0).length;
          const recentWinRate = pnls.length > 0 ? wins / pnls.length : 0.5;
          // Count consecutive losses from most recent
          let consecutiveLosses = 0;
          for (const p of pnls) {
            if (p <= 0) consecutiveLosses++;
            else break;
          }
          const isCryptoSym = sym.includes('-USD') || sym.includes('/USD');
          const boof7Result = generateSignalBoof70(candles, tradeDirection, recentWinRate, consecutiveLosses, isCryptoSym);
          signalResult = boof7Result;
          // If kill-switch triggered, log it
          if (boof7Result.killSwitch) {
            console.log(`[Boof7.0] Kill-switch for bot ${bot.id}: ${boof7Result.killReason}`);
          }
          // Apply adaptive position sizing to dollar amount
          if (boof7Result.positionSizePct && boof7Result.positionSizePct > 0) {
            const originalAmount = settings.dollarAmount;
            settings.dollarAmount = Math.round(settings.dollarAmount * boof7Result.positionSizePct);
            console.log(`[Boof7.0] Position size: ${(boof7Result.positionSizePct*100).toFixed(0)}% → $${originalAmount} → $${settings.dollarAmount}`);
            await supabase.from('stock_bots').update({ last_position_size_pct: boof7Result.positionSizePct }).eq('id', bot.id as string);
          }
          if (boof7Result.ci !== undefined) {
            await supabase.from('stock_bots').update({ last_ci: Math.round(boof7Result.ci) }).eq('id', bot.id as string);
          }
        } else if (botSignal === 'boof80') {
          // BOOF 8.0 - Adaptive AI Scalper with 0DTE aggressive mode support
          // Fetch last 20 closed trades with regime info for pattern learning
          const { data: recentTradesData } = await supabase
            .from('trades')
            .select('pnl, reason')
            .eq('bot_id', bot.id)
            .eq('status', 'closed')
            .not('pnl', 'is', null)
            .order('closed_at', { ascending: false })
            .limit(20);
          const recentTrades = (recentTradesData || []).map((t: any) => {
            // Match known regime types specifically: TREND_UP, TREND_DOWN, RANGE, EXPLOSIVE, HIGH_VOL, LOW_VOL
            const regimeMatch = t.reason?.match(/\[(TREND_UP|TREND_DOWN|RANGE|EXPLOSIVE|HIGH_VOL|LOW_VOL)[^\]]*\]/);
            const regime = regimeMatch ? regimeMatch[1] : 'UNKNOWN';
            return { reason: t.reason || '', pnlPct: Number(t.pnl) || 0, regime };
          });
          const pnls = recentTrades.map((t: any) => t.pnlPct);
          const wins = pnls.filter((p: number) => p > 0).length;
          const recentWinRate = pnls.length > 0 ? wins / pnls.length : 0.5;
          let consecutiveLosses = 0;
          for (const p of pnls) {
            if (p <= 0) consecutiveLosses++;
            else break;
          }
          const isCryptoSym = sym.includes('-USD') || sym.includes('/USD');
          const expiryType: string = (bot.bot_expiry_type as string) || 'weekly';
          const interval = settings.interval || '5m';
          const boof8Result = generateSignalBoof80(candles, tradeDirection, {
            recentTrades,
            consecutiveLosses,
            recentWinRate,
            expiryType,
            isCrypto: isCryptoSym,
            interval
          });
          signalResult = boof8Result;
          if (boof8Result.killSwitch) {
            console.log(`[Boof8.0] Kill-switch for bot ${bot.id}: ${boof8Result.killReason}`);
          }
          // Apply adaptive position sizing
          if (boof8Result.positionSizePct && boof8Result.positionSizePct > 0) {
            const originalAmount = settings.dollarAmount;
            settings.dollarAmount = Math.round(settings.dollarAmount * boof8Result.positionSizePct);
            console.log(`[Boof8.0] Position size: ${(boof8Result.positionSizePct*100).toFixed(0)}% → $${originalAmount} → $${settings.dollarAmount}`);
            await supabase.from('stock_bots').update({ last_position_size_pct: boof8Result.positionSizePct }).eq('id', bot.id as string);
          }
          if (boof8Result.choppiness !== undefined) {
            await supabase.from('stock_bots').update({ last_ci: Math.round(boof8Result.choppiness) }).eq('id', bot.id as string);
          }
        } else if (botSignal === 'boof21' || botSignal === 'boof22' || botSignal === 'boof23') {
          // BOOF 21/22/23 — SR Cluster + ZigZag/Regime signals reused as stock entry signals
          // Call the options-bot function to get the signal (shares same candle format)
          try {
            const optRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/options-bot`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`,
              },
              body: JSON.stringify({
                action: 'get_signal',
                signal: botSignal,
                symbol: sym,
                user_id: bot.user_id,
                interval: settings.interval || '1m',
              }),
            });
            const optJson = await optRes.json();
            const sig = optJson?.signal ?? 'none';
            const reason22 = optJson?.reason ?? `${botSignal} signal`;
            const price22  = optJson?.price  ?? (candles[candles.length - 1]?.close ?? 0);
            signalResult = {
              signal: sig === 'buy' ? 'buy' : sig === 'sell' ? 'sell' : 'none',
              price:  price22,
              trend:  sig !== 'none' ? 1 : 0,
              ema:    price22,
              adx:    0,
              reason: `[${botSignal.toUpperCase()}] ${reason22}`,
            };
          } catch (e) {
            signalResult = { signal: 'none', price: candles[candles.length-1]?.close ?? 0, trend: 0, ema: 0, adx: 0, reason: `${botSignal} fetch error: ${e}` };
          }
        } else if (botSignal === 'boof90') {
          // BOOF 9.0 - Precision Sniper (ultra-strict, multi-timeframe confluence)
          const [c1d, c4h] = await Promise.all([
            fetchCandles(sym, '1d',  250, bot.user_id as string),
            fetchCandles(sym, '4h', 100, bot.user_id as string),
          ]);
          signalResult = generateSignalBoof90(candles, c1d, c4h, tradeDirection);
        } else {
          signalResult = generateSignal(candles, overrideSettings);
        }
        let { signal, price, trend, ema, adx, reason, stopLoss, takeProfit } = signalResult;
        
        // Correct the signal using REAL database position state
        // The signal generators simulate inLong from historical candles, which may not match reality
        const simulatedInLong = reason.includes('inLong=true');
        
        if (hasRealPosition && !simulatedInLong) {
          // We HAVE a real position but simulation says we don't — treat as inLong
          // Only allow SELL signals, block new BUYs
          if (signal === 'buy') {
            return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Already have real open ${realOpenTrade.action} position` };
          }
        }
        
        if (!hasRealPosition && simulatedInLong && signal === 'none') {
          // No real position but simulation thinks we're in one
          // Re-run signal check ignoring inLong state: use raw indicator values
          const closes = candles.map(c => c.close);
          const curClose = closes[closes.length - 2] ?? closes[closes.length - 1];
          
          if (botSignal === 'boof20') {
            const match = reason.match(/predicted_return=([-\d.]+)/);
            const predReturn = match ? parseFloat(match[1]) : 0;
            // Only buy if predicted return is meaningfully positive (>0.5%)
            if (predReturn > 0.005 && (tradeDirection === 'both' || tradeDirection === 'long')) {
              signal = 'buy';
              reason = `Boof 2.0 BUY (no real position, pred_ret=${predReturn.toFixed(4)}). ${reason}`;
            }
          } else if (botSignal === 'supertrend' || botSignal === 'boof10') {
            // For SuperTrend: check if current bar meets entry conditions
            const match = reason.match(/adx=([\d.]+)/);
            const curAdx = match ? parseFloat(match[1]) : 0;
            const emaMatch = reason.match(/ema50=([\d.]+)/);
            const stMatch = reason.match(/supertrend=([\d.]+)/);
            const curEma = emaMatch ? parseFloat(emaMatch[1]) : 0;
            const curSt = stMatch ? parseFloat(stMatch[1]) : 0;
            if (curAdx > 25 && curClose > curEma && curClose > curSt && (tradeDirection === 'both' || tradeDirection === 'long')) {
              signal = 'buy';
              reason = `Boof 1.0 BUY (no real position, adx=${curAdx.toFixed(1)}). ${reason}`;
            } else if (curAdx > 25 && curClose < curEma && curClose < curSt && (tradeDirection === 'both' || tradeDirection === 'short')) {
              signal = 'sell';
              reason = `Boof 1.0 SELL (no real position, adx=${curAdx.toFixed(1)}). ${reason}`;
            }
          }
          if (signal !== 'none') {
            console.log(`[AutoBot] ${sym} OVERRIDE: no real position → ${signal}`);
          }
        }
        
        console.log(`[AutoBot] ${sym} → ${signal} | ${reason}`);

        if (signal === 'buy'  && settings.tradeDirection === 'short') return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Direction: short only' };
        if (signal === 'sell' && settings.tradeDirection === 'long')  return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Direction: long only' };

        if (signal === 'none') {
          await supabase.from('stock_bot_logs').insert({ bot_id: bot.id, user_id: bot.user_id, symbol: sym, signal: 'none', price, trend, ema, adx, reason, created_at: new Date().toISOString() });
          return { bot_id: bot.id, symbol: sym, status: 'no_signal', reason };
        }

        // Trend Filter: Check higher timeframe trend
        const trendFilter = bot.trend_filter as string || 'none';
        if (trendFilter !== 'none') {
          try {
            const higherTfCandles = await fetchCandles(sym, trendFilter, 100, bot.user_id as string);
            if (higherTfCandles.length >= 50) {
              const higherTfCloses = higherTfCandles.map(c => c.close);
              const higherTfEma = calcEMA(higherTfCloses, 20);
              const currentPrice = higherTfCloses[higherTfCloses.length - 1];
              const higherTfEmaVal = higherTfEma[higherTfEma.length - 1];
              
              // Higher timeframe trend: price above EMA = uptrend, below = downtrend
              const higherTfTrend = currentPrice > higherTfEmaVal ? 'up' : 'down';
              
              // Filter signal: Only trade if aligned with higher timeframe
              if (signal === 'buy' && higherTfTrend === 'down') {
                console.log(`[AutoBot] ${sym} BUY blocked - ${trendFilter} trend is DOWN (price ${currentPrice.toFixed(2)} < EMA ${higherTfEmaVal.toFixed(2)})`);
                return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `BUY blocked: ${trendFilter} trend is DOWN` };
              }
              if (signal === 'sell' && higherTfTrend === 'up') {
                console.log(`[AutoBot] ${sym} SELL blocked - ${trendFilter} trend is UP (price ${currentPrice.toFixed(2)} > EMA ${higherTfEmaVal.toFixed(2)})`);
                return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `SELL blocked: ${trendFilter} trend is UP` };
              }
              console.log(`[AutoBot] ${sym} ${signal} approved - ${trendFilter} trend aligned (${higherTfTrend})`);
            }
          } catch (e) {
            console.log(`[AutoBot] ${sym} trend filter error: ${e}`);
          }
        }

        // Check for duplicate trade within 1 minute (race condition prevention)
        const oneMinuteAgo = new Date(Date.now() - 60 * 1000).toISOString();
        const { data: recentTrade } = await supabase.from('trades')
          .select('id, action').eq('bot_id', bot.id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').gte('created_at', oneMinuteAgo)
          .limit(1).maybeSingle();
        if (recentTrade) {
          return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Duplicate ${recentTrade.action} trade within 1 minute` };
        }

        // Check for existing open position on this symbol for this bot
        const { data: openTrade } = await supabase.from('trades')
          .select('*').eq('bot_id', bot.id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'filled').is('pnl', null)
          .order('created_at', { ascending: false }).limit(1).maybeSingle();

        if (openTrade) {
          const entryPrice = Number(openTrade.entry_price || openTrade.price);
          const qty = Number(openTrade.quantity);
          // Use realistic futures P&L calculation with contract specs
          const pnl = calcFuturesPnL(sym, entryPrice, price, qty, openTrade.action as 'buy' | 'sell');
          const pnlPct = entryPrice > 0 ? ((openTrade.action === 'buy' ? (price - entryPrice) : (entryPrice - price)) / entryPrice) * 100 : 0;
          
          // Check Take Profit / Stop Loss thresholds — per-symbol rule overrides default
          const symbolRules: Array<{symbol:string;tp:number;sl:number;dir:string}> = (bot.symbol_rules as any) || [];
          const symRule = symbolRules.find(r => r.symbol?.toUpperCase() === sym.toUpperCase());
          const tpPct = symRule ? Number(symRule.tp) : (Number(bot.take_profit_pct) || 0);
          const slPct = symRule ? Number(symRule.sl) : (Number(bot.stop_loss_pct) || 0); // stored as negative, e.g. -20
          if (symRule) console.log(`[AutoBot] ${sym} using per-symbol rule: TP=${tpPct}% SL=${slPct}% dir=${symRule.dir}`);
          
          if (tpPct > 0 && pnlPct >= tpPct) {
            // Take profit hit
            await supabase.from('trades').update({
              status: 'closed',
              exit_price: price,
              pnl: pnl,
              closed_at: new Date().toISOString(),
            }).eq('id', openTrade.id);
            console.log(`[AutoBot] TP HIT ${sym} | +${pnlPct.toFixed(2)}% >= ${tpPct}% | P&L: $${pnl.toFixed(2)}`);
            return { bot_id: bot.id, symbol: sym, status: 'tp_closed', reason: `Take Profit ${tpPct}% hit (${pnlPct.toFixed(2)}%)`, pnl };
          }
          
          if (slPct < 0 && pnlPct <= slPct) {
            // Stop loss hit (slPct is negative, e.g. -20 means close at -20%)
            await supabase.from('trades').update({
              status: 'closed',
              exit_price: price,
              pnl: pnl,
              closed_at: new Date().toISOString(),
            }).eq('id', openTrade.id);
            console.log(`[AutoBot] SL HIT ${sym} | ${pnlPct.toFixed(2)}% <= ${slPct}% | P&L: $${pnl.toFixed(2)}`);
            return { bot_id: bot.id, symbol: sym, status: 'sl_closed', reason: `Stop Loss ${slPct}% hit (${pnlPct.toFixed(2)}%)`, pnl };
          }
          
          if (openTrade.action === signal) {
            // Same direction already open - skip
            return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Already in ${signal} position (${pnlPct.toFixed(2)}%)` };
          }
          // Opposite signal - close the open trade with P&L
          await supabase.from('trades').update({
            status: 'closed',
            exit_price: price,
            pnl: pnl,
            closed_at: new Date().toISOString(),
          }).eq('id', openTrade.id);
          console.log(`[AutoBot] Closed ${openTrade.action} on ${sym} | P&L: $${pnl.toFixed(2)}`);
        }

        // Check for pending limit orders from previous runs - convert to market if signal still valid
        const { data: pendingLimit } = await supabase.from('trades')
          .select('*').eq('bot_id', bot.id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'pending').eq('order_type', 'limit')
          .order('created_at', { ascending: false }).limit(1).maybeSingle();
        
        if (pendingLimit) {
          const limitPrice = Number(pendingLimit.price);
          const entryPrice = Number(pendingLimit.entry_price);
          const isBuy = pendingLimit.action === 'buy';
          const filled = isBuy ? price <= limitPrice : price >= limitPrice;
          
          // Max drawdown protection: Don't buy if stock dropped too much from original signal
          const maxDrawdownPct = Number(bot.limit_drawdown_pct) || 2.0; // Use bot setting or default 2%
          const drawdown = isBuy 
            ? ((entryPrice - price) / entryPrice) * 100  // How much it dropped
            : ((price - entryPrice) / entryPrice) * 100; // How much it rose (for shorts)
          
          if (drawdown > maxDrawdownPct) {
            // Stock moved too far against us - cancel limit order
            await supabase.from('trades').update({ 
              status: 'cancelled',
              reason: `Cancelled: ${drawdown.toFixed(2)}% drawdown exceeded ${maxDrawdownPct}% max`
            }).eq('id', pendingLimit.id);
            console.log(`[AutoBot] Cancelled limit for ${sym} - ${drawdown.toFixed(2)}% drawdown, signal price ${entryPrice}, current ${price}`);
            return { bot_id: bot.id, symbol: sym, status: 'cancelled', reason: 'Max drawdown exceeded' };
          }
          
          // Check time limit
          const limitTimeMin = Number(bot.limit_time_min) || 2;
          const orderAgeMs = Date.now() - new Date(pendingLimit.created_at).getTime();
          const orderAgeMin = orderAgeMs / (1000 * 60);
          const timeLimitExceeded = orderAgeMin >= limitTimeMin;
          
          if (filled) {
            // Limit order would have filled - update to filled status
            await supabase.from('trades').update({
              status: 'filled',
              filled_at: new Date().toISOString(),
            }).eq('id', pendingLimit.id);
            console.log(`[AutoBot] Limit order filled for ${sym} at ~${limitPrice}`);
            return { bot_id: bot.id, symbol: sym, status: 'filled', signal, price: limitPrice, quantity: pendingLimit.quantity };
          } else if (signal === pendingLimit.action && timeLimitExceeded) {
            // Time limit exceeded - convert to market order
            await supabase.from('trades').update({
              order_type: 'market',
              price: price,
              entry_price: price,
              status: 'filled',
              filled_at: new Date().toISOString(),
            }).eq('id', pendingLimit.id);
            console.log(`[AutoBot] Time limit (${limitTimeMin}min) exceeded - converted limit to market for ${sym} at ${price}`);
            return { bot_id: bot.id, symbol: sym, status: 'filled', signal, price, quantity: pendingLimit.quantity };
          } else if (signal !== pendingLimit.action) {
            // Signal reversed - cancel the limit order
            await supabase.from('trades').update({ status: 'cancelled' }).eq('id', pendingLimit.id);
            console.log(`[AutoBot] Cancelled limit order for ${sym} - signal reversed`);
          } else {
            // Still waiting - signal valid but limit not hit and time not exceeded
            console.log(`[AutoBot] Limit order pending for ${sym} at ${limitPrice} (current ${price}, ${orderAgeMin.toFixed(1)}min/${limitTimeMin}min)`);
            return { bot_id: bot.id, symbol: sym, status: 'pending', reason: `Limit pending ${orderAgeMin.toFixed(1)}min/${limitTimeMin}min` };
          }
        }

        // Double-check no open position (race condition prevention)
        const { data: stillOpen } = await supabase.from('trades')
          .select('id').eq('bot_id', bot.id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'filled').is('pnl', null)
          .limit(1);
        if (stillOpen && stillOpen.length > 0) {
          return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Position already opened by parallel process' };
        }

        let orderId: string | undefined;
        let quantity = Math.max(1, Math.round(settings.dollarAmount / price));
        console.log(`[AutoBot] Trade size: $${settings.dollarAmount} → ${quantity} shares @ $${price.toFixed(2)}`);
        let tradeStatus = 'filled';
        let brokerError: string | undefined;

        if (bot.broker === 'tastytrade') {
          try {
            const r = await placeTastyOrder(supabase, bot.user_id as string, signal, sym, price, settings.dollarAmount);
            orderId = r.orderId;
            quantity = r.quantity;
          } catch (e) {
            brokerError = String(e);
            tradeStatus = 'failed';
            console.error('[AutoBot] Tastytrade error:', brokerError);
          }
        } else if (bot.broker === 'alpaca') {
          const useLimitOrders = bot.use_limit_orders || false;
          const limitOffsetPct = bot.limit_offset_pct || 0.5;
          
          if (useLimitOrders && signal === 'buy') {
            // Place limit order at better price
            const limitPrice = price * (1 - Number(limitOffsetPct) / 100);
            
            // Insert as pending limit order
            await supabase.from('trades').insert({
              user_id: bot.user_id,
              bot_id: bot.id,
              symbol: sym,
              action: signal,
              direction: 'Long',
              quantity: quantity,
              price: limitPrice,
              entry_price: price,  // Store original signal price for drawdown calc
              order_type: 'limit',
              broker: 'alpaca',
              source: 'auto-bot',
              status: 'pending',
              created_at: new Date().toISOString(),
            });
            
            console.log(`[AutoBot] Alpaca limit order placed: ${sym} at $${limitPrice.toFixed(2)} (current $${price.toFixed(2)}, offset -${limitOffsetPct}%)`);
            return { bot_id: bot.id, symbol: sym, status: 'pending', signal, price: limitPrice, quantity, order_type: 'limit' };
          } else {
            // Market order
            try {
              const alpacaRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/alpaca-order`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`,
                },
                body: JSON.stringify({
                  user_id: bot.user_id,
                  symbol: sym,
                  side: signal === 'buy' ? 'buy' : 'sell',
                  notional: settings.dollarAmount,
                }),
              });
              const alpacaJson = await alpacaRes.json();
              if (!alpacaRes.ok || alpacaJson.error) throw new Error(alpacaJson.error || 'Alpaca order failed');
              orderId = alpacaJson.order_id;
              tradeStatus = 'filled';
            } catch (e) {
              brokerError = String(e);
              tradeStatus = 'failed';
              console.error('[AutoBot] Alpaca error:', brokerError);
            }
          }
        } else {
          // Paper trading: check if we should use limit orders
          const useLimitOrders = bot.use_limit_orders || false;
          const limitOffsetPct = bot.limit_offset_pct || 0.5; // Default 0.5% better price
          
          if (useLimitOrders && signal === 'buy') {
            // Place limit order at better price (below current for buys)
            const limitPrice = price * (1 - Number(limitOffsetPct) / 100);
            
            // Insert as pending limit order
            await supabase.from('trades').insert({
              user_id: bot.user_id,
              bot_id: bot.id,
              symbol: sym,
              action: signal,
              direction: 'Long',
              quantity: quantity,
              price: limitPrice,
              entry_price: limitPrice,
              order_type: 'limit',
              broker: 'paper',
              source: 'auto-bot',
              status: 'pending',
              created_at: new Date().toISOString(),
            });
            
            console.log(`[AutoBot] Paper limit order placed: ${sym} at $${limitPrice.toFixed(2)} (current $${price.toFixed(2)}, offset -${limitOffsetPct}%)`);
            return { bot_id: bot.id, symbol: sym, status: 'pending', signal, price: limitPrice, quantity, order_type: 'limit' };
          } else {
            // Market order (existing behavior)
            const tradeValue = quantity * price;
            const { data: botRow } = await supabase.from('stock_bots').select('paper_balance').eq('id', bot.id as string).single();
            const currentBalance = Number(botRow?.paper_balance ?? 100000);
            const newBalance = signal === 'buy'
              ? currentBalance - tradeValue
              : currentBalance + tradeValue;
            await supabase.from('stock_bots').update({ paper_balance: Math.max(0, newBalance) }).eq('id', bot.id as string);
          }
        }

        // Final duplicate guard: check one more time before inserting
        const { data: existingPos } = await supabase.from('trades')
          .select('id').eq('user_id', bot.user_id as string).eq('symbol', sym)
          .eq('source', 'auto-bot').eq('status', 'filled').is('pnl', null)
          .limit(1).maybeSingle();
        if (existingPos) {
          console.log(`[AutoBot] BLOCKED duplicate: ${sym} already has open position ${existingPos.id}`);
          return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Blocked duplicate at insert time' };
        }

        // Insert trade into main trades table (visible on trades page)
        const { data: trade } = await supabase.from('trades').insert({
          user_id: bot.user_id,
          bot_id: bot.id,
          symbol: sym,
          action: signal,
          direction: signal === 'buy' ? 'Long' : 'Short',
          quantity: quantity,
          price: price,
          entry_price: price,
          order_type: 'market',
          broker: bot.broker || 'paper',
          source: 'auto-bot',
          status: tradeStatus === 'filled' ? 'filled' : 'pending',
          filled_at: tradeStatus === 'filled' ? new Date().toISOString() : null,
          created_at: new Date().toISOString(),
          // Use dynamic TP/SL from Boof 15.0 if available, otherwise use bot defaults
          take_profit_pct: stopLoss && takeProfit ? ((takeProfit - price) / price) * 100 : (Number(bot.take_profit_pct) || 0),
          stop_loss_pct: stopLoss && takeProfit ? ((stopLoss - price) / price) * 100 : (Number(bot.stop_loss_pct) || 0),
        }).select().single();

        // Post-insert duplicate cleanup: if multiple open positions exist for this user+symbol, keep only the oldest
        if (trade?.id) {
          const { data: allOpen } = await supabase.from('trades')
            .select('id, created_at').eq('user_id', bot.user_id as string).eq('symbol', sym)
            .eq('source', 'auto-bot').eq('status', 'filled').is('pnl', null)
            .order('created_at', { ascending: true });
          if (allOpen && allOpen.length > 1) {
            // Keep the first (oldest), delete the rest
            const dupeIds = allOpen.slice(1).map(t => t.id);
            console.log(`[AutoBot] CLEANING ${dupeIds.length} duplicate(s) for ${sym}: keeping ${allOpen[0].id}, removing ${dupeIds.join(', ')}`);
            await supabase.from('trades').delete().in('id', dupeIds);
            // If our trade was a dupe, return early
            if (dupeIds.includes(trade.id)) {
              return { bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Duplicate cleaned post-insert' };
            }
          }
        }

        await supabase.from('stock_bot_logs').insert({ bot_id: bot.id, user_id: bot.user_id, symbol: sym, signal, price, trend, ema, adx, reason, trade_id: trade?.id || null, created_at: new Date().toISOString() });

        // Note: Options bot now runs independently - no sync trigger from stock bot
        // Options bot scans symbols on its own schedule and generates its own signals

        return { bot_id: bot.id, status: tradeStatus, signal, symbol: sym, price, quantity, order_id: orderId, reason, broker_error: brokerError };
      } catch (err) {
        return { bot_id: bot.id, symbol: sym, status: 'error', error: String(err) };
      }
    }

    // ── Main loop ────────────────────────────────────────────────────────────
    const results: object[] = [];
    const now = new Date();
    
    // Check market hours (crypto/futures trade 24/7, stocks only 9:30 AM - 4:00 PM ET)
    const etNow = new Date(now.toLocaleString("en-US", {timeZone: "America/New_York"}));
    const hour = etNow.getHours();
    const minute = etNow.getMinutes();
    const day = etNow.getDay();
    const isWeekday = day >= 1 && day <= 5;
    const isStockMarketHours = isWeekday && (hour > 9 || (hour === 9 && minute >= 30)) && hour < 16;

    for (const bot of bots) {
      // Check if bot should run based on run_interval_min
      const runIntervalMin = (bot.run_interval_min as number) ?? 15;
      const lastRunAt = bot.last_run_at ? new Date(bot.last_run_at as string) : null;
      const minutesSinceLastRun = lastRunAt ? (now.getTime() - lastRunAt.getTime()) / (1000 * 60) : Infinity;
      
      if (minutesSinceLastRun < runIntervalMin) {
        console.log(`[AutoBot] Skipping "${bot.name}" - ran ${minutesSinceLastRun.toFixed(1)}m ago, interval=${runIntervalMin}m`);
        continue;
      }
      
      const settings: BotSettings = {
        atrLength:      bot.bot_atr_length     ?? 10,
        atrMultiplier:  bot.bot_atr_multiplier ?? 3.0,
        emaLength:      bot.bot_ema_length     ?? 50,
        adxLength:      bot.bot_adx_length     ?? 14,
        adxThreshold:   bot.bot_adx_threshold  ?? 20,
        symbol:         bot.bot_symbol         ?? 'SPY',
        dollarAmount:   bot.bot_dollar_amount  ?? 500,
        interval:       bot.bot_interval       ?? '1h',
        tradeDirection: bot.bot_trade_direction ?? bot.trade_direction ?? 'both',
      };

      // New multi-select scan markets
      const scanStocks = bot.scan_stocks || false;
      const scanCrypto = bot.scan_crypto || false;
      const scanFutures = bot.scan_futures || false;
      
      // Skip stocks portion if market is closed (but still run crypto/futures)
      const skipStocks = scanStocks && !isStockMarketHours;
      if (skipStocks) {
        console.log(`[AutoBot] Skipping stocks for "${bot.name}" - stock markets closed (${etNow.toLocaleTimeString('en-US', {timeZone: 'America/New_York'})} ET)`);
      }
      
      // Single mode: parse bot_symbol as CSV list e.g. "SPY, QQQ, NVDA"
      const singleSymbols = (settings.symbol as string).split(',').map((s:string) => s.trim().toUpperCase()).filter(Boolean);
      const isSingleMode = !scanStocks && !scanCrypto && !scanFutures;

      console.log(`[AutoBot] Running "${bot.name}" | ${isSingleMode ? `single=[${singleSymbols.join(',')}]` : `stocks=${scanStocks}${skipStocks?' (skipped)':''}, crypto=${scanCrypto}, futures=${scanFutures}`} | ${settings.interval} | interval=${runIntervalMin}m`);

      try {
        if (isSingleMode) {
          for (const sym of singleSymbols) {
            const isCryptoOrFutures = sym.includes('-USD') || sym.includes('/USD') || sym.includes('=F');
            if (!isCryptoOrFutures && !isStockMarketHours) {
              console.log(`[AutoBot] Skipping ${sym} for "${bot.name}" - pre/post market (${etNow.toLocaleTimeString('en-US', {timeZone: 'America/New_York'})} ET)`);
              results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Pre/post market hours (${etNow.toLocaleTimeString('en-US', {timeZone: 'America/New_York'})} ET) — stocks only trade 9:30 AM - 4:00 PM ET` });
              continue;
            }
            const result = await processSymbol(bot, sym, settings);
            results.push(result);
          }
        }
        if (scanStocks && !skipStocks) {
          for (const sym of SCAN_STOCKS) {
            const result = await processSymbol(bot, sym, settings);
            results.push(result);
          }
        }
        if (scanCrypto) {
          for (const sym of SCAN_CRYPTO) {
            const result = await processSymbol(bot, sym, settings);
            results.push(result);
          }
        }
        if (scanFutures) {
          for (const sym of SCAN_FUTURES) {
            const result = await processSymbol(bot, sym, settings);
            results.push(result);
          }
        }
        
        // Update last_run_at after successful processing
        await supabase.from('stock_bots').update({ last_run_at: now.toISOString() }).eq('id', bot.id);
        
      } catch (err) {
        console.error(`[AutoBot] Error on bot ${bot.id}:`, err);
        results.push({ bot_id: bot.id, status: 'error', error: String(err) });
      }
    }

    console.log(`[AutoBot] Processed ${results.length} results:`, results);

    return new Response(JSON.stringify({ processed: results.length, results }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
