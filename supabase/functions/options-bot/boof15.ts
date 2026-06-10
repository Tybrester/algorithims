// ─────────────────────────────────────────────
// BOOF 15.0/16.0 - EV-BASED SIGNAL GENERATION
// Ported from Python backtest_signals.py
// ─────────────────────────────────────────────

interface Boof150Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  score: number;
  ev: number;
  positionSize: number;
  reason: string;
  regime: string;
  session: string;
}

// ─────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────

const SYMBOL_MULTIPLIER: Record<string, number> = {
  'SPY': 1.0,
  'QQQ': 0.85,
  'TSLA': 1.3,
  'AMD': 1.25,
  'NVDA': 1.15,
  'PLTR': 1.15,
  'AAPL': 0.95,
  'MSFT': 0.90,
  'AMZN': 1.05,
  'AVGO': 0.95,
  'default': 1.0
};

const REGIME_MULTIPLIER: Record<string, number> = {
  'EXPANSION': 1.1,
  'NORMAL': 0.8,
  'COMPRESSION': 0.9
};

const SESSION_MULTIPLIER: Record<string, Record<string, number>> = {
  'SPY': { 'OPEN': 1.2, 'MID': 0.9, 'CLOSE': 1.0 },
  'QQQ': { 'OPEN': 1.3, 'MID': 0.7, 'CLOSE': 0.9 },
  'TSLA': { 'OPEN': 1.1, 'MID': 1.0, 'CLOSE': 1.1 },
  'AMD': { 'OPEN': 1.25, 'MID': 1.05, 'CLOSE': 1.15 },
  'NVDA': { 'OPEN': 1.2, 'MID': 1.0, 'CLOSE': 1.1 }
};

const SYMBOL_TP_MULTIPLIER: Record<string, number> = {
  'AMD': 1.2,
  'TSLA': 1.0,
  'SPY': 0.9,
  'QQQ': 0.8,
  'NVDA': 1.0,
  'PLTR': 1.1,
  'AAPL': 0.85,
  'MSFT': 0.85,
  'AMZN': 0.95,
  'AVGO': 0.9,
  'default': 1.0
};

// ─────────────────────────────────────────────
// HELPER FUNCTIONS
// ─────────────────────────────────────────────

function getSession(timestamp: Date): string {
  const hour = timestamp.getUTCHours();
  const minute = timestamp.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;

  if (timeMinutes >= 570 && timeMinutes < 660) return 'OPEN';  // 9:30-11:00 UTC
  if (timeMinutes >= 660 && timeMinutes < 840) return 'MID';   // 11:00-14:00 UTC
  return 'CLOSE';  // 14:00-16:00 UTC
}

function calculateTPMultiplier(ev: number): number {
  if (ev < 0.05) return 1.2;
  if (ev < 0.15) return 1.5;
  return 2.0;
}

function calculateRiskParameters(symbol: string, ev: number, atrValue: number): { slDistance: number; tpDistance: number } {
  const slDistance = 0.8 * atrValue;
  const tpMultiplier = calculateTPMultiplier(ev);
  const symbolTPMult = SYMBOL_TP_MULTIPLIER[symbol] || SYMBOL_TP_MULTIPLIER['default'];
  const tpDistance = slDistance * tpMultiplier * symbolTPMult;
  return { slDistance, tpDistance };
}

function computeContinuousEV(symbol: string, score: number, regime: string, atrPercentile: number = 0.5, session: string = 'MID'): number {
  // Base EV from score
  const baseEV = (score - 3.0) * 0.08;

  // Symbol multiplier
  const symMult = SYMBOL_MULTIPLIER[symbol] || SYMBOL_MULTIPLIER['default'];

  // Session multiplier
  const sessionMults = SESSION_MULTIPLIER[symbol] || { 'OPEN': 1.0, 'MID': 1.0, 'CLOSE': 1.0 };
  const sessMult = sessionMults[session] || 1.0;

  // Regime multiplier
  const regMult = REGIME_MULTIPLIER[regime] || 1.0;

  // Volatility adjustment
  let volAdj = 1.0;
  if (atrPercentile > 0.7) volAdj = 0.9;
  else if (atrPercentile < 0.3) volAdj = 1.1;

  // Final EV
  return baseEV * symMult * sessMult * regMult * volAdj;
}

function calculatePositionSize(ev: number, volatility: number, baseSize: number = 1.0, useKelly: boolean = false): number {
  if (useKelly) {
    // Kelly criterion (half-Kelly)
    const kellyFraction = ev * 0.5;
    const cappedKelly = Math.min(kellyFraction, 0.25);
    const volFactor = 1.0 / (1.0 + volatility * 0.5);
    const adjustedSize = baseSize * cappedKelly * volFactor * 4;
    return Math.max(adjustedSize, 0.1);
  } else {
    // EV-based sizing (Boof 15.0)
    const evFactor = Math.min(ev * 5, 2.0);
    const volFactor = 1.0 / (1.0 + volatility * 0.5);
    const adjustedSize = baseSize * evFactor * volFactor;
    return Math.max(adjustedSize, 0.1);
  }
}

// ─────────────────────────────────────────────
// SCORING SYSTEM
// ─────────────────────────────────────────────

function calculateScore(candles: any[], lookback: number = 20): number {
  if (candles.length < lookback + 5) return 0;

  const i = candles.length - 1;
  const row = candles[i];
  const df = candles;

  let score = 0;

  // SCORE 1: ATR rising (pre-expansion)
  const atrSeries = df.slice(i - 20, i).map((c: any) => c.atr || 0);
  const atrAvg = atrSeries.reduce((a: number, b: number) => a + b, 0) / atrSeries.length;
  const atrCurrent = row.atr || 0;
  const atrRising = atrCurrent > atrAvg * 1.02;
  if (atrRising) score += 1;

  // SCORE 1: ATR compression (relative percentile)
  const atrSeriesClean = atrSeries.filter((v: number) => v > 0);
  if (atrSeriesClean.length > 0) {
    const atrRank = atrSeriesClean.filter((v: number) => v < atrCurrent).length / atrSeriesClean.length;
    const atrCompression = atrRank < 0.4;
    if (atrCompression) score += 1;
  }

  // SCORE 1: Clean consolidation (tight range)
  const rangeHigh = Math.max(...df.slice(i - lookback, i).map((c: any) => c.high));
  const rangeLow = Math.min(...df.slice(i - lookback, i).map((c: any) => c.low));
  const rangeWidth = rangeHigh - rangeLow;

  const recentRanges: number[] = [];
  for (let j = i - lookback - 5; j < i - lookback; j++) {
    if (j >= lookback) {
      const pastWindow = df.slice(j - lookback, j);
      recentRanges.push(Math.max(...pastWindow.map((c: any) => c.high)) - Math.min(...pastWindow.map((c: any) => c.low)));
    }
  }
  const avgRecentRange = recentRanges.length > 0 ? recentRanges.reduce((a, b) => a + b, 0) / recentRanges.length : rangeWidth;
  const tightRange = rangeWidth < avgRecentRange * 1.3;
  if (tightRange) score += 1;

  // SCORE 1: Time-of-day filter
  const timestamp = new Date(row.t);
  const hour = timestamp.getUTCHours();
  const minute = timestamp.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;
  const isOpen = timeMinutes >= 570 && timeMinutes <= 660;
  const isLunch = timeMinutes >= 750 && timeMinutes <= 810;
  const isClose = timeMinutes >= 900 && timeMinutes <= 960;
  if (isOpen || isLunch || isClose) score += 1;

  return score;
}

// ─────────────────────────────────────────────
// MAIN SIGNAL GENERATION
// ─────────────────────────────────────────────

export function generateSignalBoof150(
  candles: any[],
  symbol: string = 'SPY',
  regime: string = 'NORMAL',
  useKelly: boolean = false,
  tradeDirection: string = 'both'
): Boof150Result {
  if (candles.length < 30) {
    return {
      signal: 'none',
      price: 0,
      score: 0,
      ev: 0,
      positionSize: 0,
      reason: 'Insufficient data',
      regime,
      session: 'MID'
    };
  }

  const i = candles.length - 1;
  const row = candles[i];
  const lookback = 20;

  // Calculate score
  const score = calculateScore(candles, lookback);

  // Calculate ATR percentile (simplified)
  const atrValues = candles.slice(-50).map((c: any) => c.atr || 0).filter((v: number) => v > 0);
  const atrPercentile = atrValues.length > 0 ? 
    atrValues.filter((v: number) => v < (row.atr || 0)).length / atrValues.length : 0.5;

  // Determine session
  const session = getSession(new Date(row.t));

  // Calculate EV
  const ev = computeContinuousEV(symbol, score, regime, atrPercentile, session);

  // Only trade if positive EV
  if (ev <= 0) {
    return {
      signal: 'none',
      price: row.close,
      score,
      ev,
      positionSize: 0,
      reason: `EV ${ev.toFixed(3)} <= 0`,
      regime,
      session
    };
  }

  // Calculate range for breakout detection
  const rangeHigh = Math.max(...candles.slice(i - lookback, i).map((c: any) => c.high));
  const rangeLow = Math.min(...candles.slice(i - lookback, i).map((c: any) => c.low));

  // Entry conditions
  const longBreakout = row.close > rangeHigh;
  const shortBreakout = row.close < rangeLow;

  const longEntry = longBreakout && row.close > row.vwap && row.ema9 > row.ema20 && (row.rvol || 1) > 1.3;
  const shortEntry = shortBreakout && row.close < row.vwap && row.ema9 < row.ema20 && (row.rvol || 1) > 1.3;

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = '';

  if (longEntry && tradeDirection !== 'short') {
    signal = 'buy';
    reason = `LONG breakout score=${score.toFixed(1)} ev=${ev.toFixed(3)}`;
  } else if (shortEntry && tradeDirection !== 'long') {
    signal = 'sell';
    reason = `SHORT breakdown score=${score.toFixed(1)} ev=${ev.toFixed(3)}`;
  } else {
    reason = `No entry conditions met score=${score.toFixed(1)}`;
  }

  // Calculate position size
  const atrValue = row.atr || 0.5;
  const positionSize = calculatePositionSize(ev, atrValue, 1.0, useKelly);

  return {
    signal,
    price: row.close,
    score,
    ev,
    positionSize,
    reason,
    regime,
    session
  };
}

// ─────────────────────────────────────────────
// OPTIONS-SPECIFIC EXIT CONDITIONS
// ─────────────────────────────────────────────

interface ExitResult {
  shouldExit: boolean;
  exitPrice: number;
  exitReason: string;
}

export function generateExitSignalsOptions(
  candles: any[],
  positionDirection: 'LONG' | 'SHORT',
  entryPrice: number,
  entryTime: number,
  optionPremium: number,
  is0DTE: boolean = true
): ExitResult {
  const closes = candles.map((c: any) => c.close);
  const highs = candles.map((c: any) => c.high);
  const lows = candles.map((c: any) => c.low);
  const n = closes.length;
  const curClose = closes[n - 1];

  // Options-specific TP/SL (based on premium, not underlying)
  const tpPct = 0.30;  // 30% profit target on premium
  const slPct = -0.20; // 20% stop loss on premium

  // Calculate current premium PnL (simplified - in reality would use actual option price)
  const premiumPnL = (curClose - entryPrice) / entryPrice;
  const optionsPnL = premiumPnL * 0.5; // Delta ~0.5 for 0DTE

  // Check TP/SL on options premium
  if (optionsPnL >= tpPct) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'options_tp'
    };
  }
  if (optionsPnL <= slPct) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'options_sl'
    };
  }

  // Time-based exit for 0DTE (exit 30 min before close)
  if (is0DTE) {
    const now = new Date().getTime();
    const entryDate = new Date(entryTime);
    const hoursHeld = (now - entryTime) / (1000 * 60 * 60);

    // Exit if held for more than 1 hour (theta decay)
    if (hoursHeld >= 1.0) {
      return {
        shouldExit: true,
        exitPrice: curClose,
        exitReason: 'theta_decay'
      };
    }

    // Exit 30 min before market close (3:30 PM ET)
    const nowDate = new Date(now);
    const hour = nowDate.getUTCHours();
    const minute = nowDate.getUTCMinutes();
    const timeMinutes = hour * 60 + minute;

    if (timeMinutes >= 930) { // 3:30 PM UTC = 9:30 UTC (assuming ET)
      return {
        shouldExit: true,
        exitPrice: curClose,
        exitReason: 'eod_exit'
      };
    }
  }

  // IV crush detection (only on losing trades)
  if (premiumPnL < 0) {
    // Simplified IV crush - in reality would compare IV changes
    const ivCrushFactor = 0.98; // 2% IV crush
    if (optionsPnL * ivCrushFactor < slPct) {
      return {
        shouldExit: true,
        exitPrice: curClose,
        exitReason: 'iv_crush'
      };
    }
  }

  // Fallback to underlying-based exit conditions
  const vwap = calcVWAP(candles);
  const ema9 = calcEMA(closes, 9);
  const ema20 = calcEMA(closes, 20);
  const atr = calcATR(highs, lows, closes, 14);

  const curVWAP = vwap;
  const curEMA9 = ema9[ema9.length - 1];
  const curEMA20 = ema20[ema20.length - 1];
  const curATR = atr[atr.length - 1];

  const stopMult = 1.2;
  const stop = positionDirection === 'LONG'
    ? entryPrice - stopMult * curATR
    : entryPrice + stopMult * curATR;

  // Hard stop
  if (positionDirection === 'LONG' && curClose < stop) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'hard_stop'
    };
  }
  if (positionDirection === 'SHORT' && curClose > stop) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'hard_stop'
    };
  }

  // Structure break
  if (positionDirection === 'LONG' && curClose < curVWAP && curEMA9 < curEMA20) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'structure_break'
    };
  }
  if (positionDirection === 'SHORT' && curClose > curVWAP && curEMA9 > curEMA20) {
    return {
      shouldExit: true,
      exitPrice: curClose,
      exitReason: 'structure_break'
    };
  }

  return {
    shouldExit: false,
    exitPrice: curClose,
    exitReason: 'hold'
  };
}

// Helper function for VWAP (needed for exit logic)
function calcVWAP(candles: any[]): number {
  let cumTPV = 0, cumVol = 0;
  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    const vol = c.volume || 1;
    cumTPV += tp * vol;
    cumVol += vol;
  }
  return cumVol > 0 ? cumTPV / cumVol : 0;
}

// Helper function for EMA (needed for exit logic)
function calcEMA(data: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const ema = new Array(data.length).fill(0);
  ema[0] = data[0];
  for (let i = 1; i < data.length; i++) ema[i] = data[i] * k + ema[i - 1] * (1 - k);
  return ema;
}

// Helper function for ATR (needed for exit logic)
function calcATR(highs: number[], lows: number[], closes: number[], period: number): number[] {
  const tr = highs.map((h, i) => i === 0 ? h - lows[i] : Math.max(h - lows[i], Math.abs(h - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
  const atr = new Array(tr.length).fill(0);
  atr[period - 1] = tr.slice(0, period).reduce((a, b) => a + b) / period;
  for (let i = period; i < tr.length; i++) atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;
  return atr;
}

// ─────────────────────────────────────────────
// REGIME CLASSIFICATION
// ─────────────────────────────────────────────

export function classifyRegime(candles: any[]): string {
  if (candles.length < 50) return 'NORMAL';

  const closes = candles.map((c: any) => c.close);
  const highs = candles.map((c: any) => c.high);
  const lows = candles.map((c: any) => c.low);

  // Calculate ATR
  const atrValues: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    atrValues.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    ));
  }

  const atr = atrValues.slice(-14).reduce((a, b) => a + b, 0) / 14;
  const atrPercent = atr / closes[closes.length - 1] * 100;

  // Simple regime classification
  if (atrPercent > 1.5) return 'EXPANSION';
  if (atrPercent < 0.5) return 'COMPRESSION';
  return 'NORMAL';
}
