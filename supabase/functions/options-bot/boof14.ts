// ─────────────────────────────────────────────
// BOOF 14.0 - SIMPLIFIED EV-BASED SIGNAL GENERATION
// Backup of original Boof 15.0 without Kelly/Advanced EV
// ─────────────────────────────────────────────

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface Boof14Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  score: number;
  ev: number;
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

// ─────────────────────────────────────────────
// HELPER FUNCTIONS
// ─────────────────────────────────────────────

function getSession(timestamp: number): string {
  const date = new Date(timestamp);
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;

  if (timeMinutes >= 570 && timeMinutes < 660) return 'OPEN';  // 9:30-11:00 UTC
  if (timeMinutes >= 660 && timeMinutes < 840) return 'MID';   // 11:00-14:00 UTC
  return 'CLOSE';  // 14:00-16:00 UTC
}

function ema(values: number[], period: number): number[] {
  const result: number[] = [];
  const multiplier = 2 / (period + 1);
  
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(values[i]);
    } else if (i === period - 1) {
      const sum = values.slice(0, period).reduce((a, b) => a + b, 0);
      result.push(sum / period);
    } else {
      result.push((values[i] - result[i - 1]) * multiplier + result[i - 1]);
    }
  }
  
  return result;
}

function atr(candles: Candle[], period: number): number[] {
  const tr: number[] = [];
  
  for (let i = 0; i < candles.length; i++) {
    if (i === 0) {
      tr.push(candles[i].high - candles[i].low);
    } else {
      const highLow = candles[i].high - candles[i].low;
      const highClose = Math.abs(candles[i].high - candles[i - 1].close);
      const lowClose = Math.abs(candles[i].low - candles[i - 1].close);
      tr.push(Math.max(highLow, highClose, lowClose));
    }
  }
  
  return ema(tr, period);
}

function vwap(candles: Candle[]): number[] {
  const result: number[] = [];
  let cumVolume = 0;
  let cumVolumePrice = 0;
  
  for (let i = 0; i < candles.length; i++) {
    const typicalPrice = (candles[i].high + candles[i].low + candles[i].close) / 3;
    cumVolume += candles[i].volume || 0;
    cumVolumePrice += typicalPrice * (candles[i].volume || 0);
    result.push(cumVolume / (cumVolume || 1));
  }
  
  return result;
}

function classifyRegime(candles: Candle[]): string {
  if (candles.length < 50) return 'NORMAL';
  
  const atrValues = atr(candles, 14);
  const currentATR = atrValues[atrValues.length - 1];
  const avgATR = atrValues.slice(-20).reduce((a, b) => a + b, 0) / 20;
  
  const vwapValues = vwap(candles);
  const currentPrice = candles[candles.length - 1].close;
  const currentVWAP = vwapValues[vwapValues.length - 1];
  
  // Expansion: ATR > 1.2x average and price far from VWAP
  if (currentATR > avgATR * 1.2 && Math.abs(currentPrice - currentVWAP) / currentVWAP > 0.01) {
    return 'EXPANSION';
  }
  
  // Compression: ATR < 0.8x average
  if (currentATR < avgATR * 0.8) {
    return 'COMPRESSION';
  }
  
  return 'NORMAL';
}

function calculateScore(candles: Candle[], symbol: string): number {
  if (candles.length < 20) return 0;
  
  const closes = candles.map(c => c.close);
  const ema9 = ema(closes, 9);
  const ema21 = ema(closes, 21);
  const vwapValues = vwap(candles);
  
  const currentClose = closes[closes.length - 1];
  const currentEMA9 = ema9[ema9.length - 1];
  const currentEMA21 = ema21[ema21.length - 1];
  const currentVWAP = vwapValues[vwapValues.length - 1];
  
  let score = 0;
  
  // Trend alignment
  if (currentClose > currentEMA9 && currentEMA9 > currentEMA21) score += 1;
  if (currentClose < currentEMA9 && currentEMA9 < currentEMA21) score += 1;
  
  // VWAP alignment
  if (currentClose > currentVWAP) score += 0.5;
  if (currentClose < currentVWAP) score += 0.5;
  
  // Momentum
  const momentum = (currentClose - closes[closes.length - 5]) / closes[closes.length - 5];
  if (Math.abs(momentum) > 0.005) score += 0.5;
  
  return score;
}

function calculateSimpleEV(score: number, symbol: string, regime: string, session: string): number {
  const symMult = SYMBOL_MULTIPLIER[symbol] || SYMBOL_MULTIPLIER['default'];
  const regimeMult = REGIME_MULTIPLIER[regime] || 1.0;
  const sessionMults = SESSION_MULTIPLIER[symbol] || { 'OPEN': 1.0, 'MID': 1.0, 'CLOSE': 1.0 };
  const sessMult = sessionMults[session] || 1.0;
  
  const baseEV = (score / 3.0) * 0.1;  // Simple linear mapping
  return baseEV * symMult * regimeMult * sessMult;
}

// ─────────────────────────────────────────────
// SIGNAL GENERATION
// ─────────────────────────────────────────────

export function generateSignalBoof14(
  candles: Candle[],
  symbol: string,
  tradeDirection: string = 'both'
): Boof14Result {
  if (candles.length < 30) {
    return {
      signal: 'none',
      price: candles[candles.length - 1].close,
      score: 0,
      ev: 0,
      reason: 'Not enough candles',
      regime: 'NORMAL',
      session: 'MID'
    };
  }
  
  const currentCandle = candles[candles.length - 1];
  const regime = classifyRegime(candles);
  const session = getSession(currentCandle.time);
  const score = calculateScore(candles, symbol);
  const ev = calculateSimpleEV(score, symbol, regime, session);
  
  // Minimum score threshold
  if (score < 1.5) {
    return {
      signal: 'none',
      price: currentCandle.close,
      score,
      ev,
      reason: 'Score below threshold',
      regime,
      session
    };
  }
  
  // Determine signal direction
  const closes = candles.map(c => c.close);
  const ema9 = ema(closes, 9);
  const currentEMA9 = ema9[ema9.length - 1];
  const vwapValues = vwap(candles);
  const currentVWAP = vwapValues[vwapValues.length - 1];
  
  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = '';
  
  if (tradeDirection === 'long' || tradeDirection === 'both') {
    if (currentCandle.close > currentEMA9 && currentCandle.close > currentVWAP) {
      signal = 'buy';
      reason = `Price above EMA9 and VWAP (score: ${score.toFixed(1)}, ev: ${ev.toFixed(3)})`;
    }
  }
  
  if (tradeDirection === 'short' || tradeDirection === 'both') {
    if (currentCandle.close < currentEMA9 && currentCandle.close < currentVWAP) {
      signal = 'sell';
      reason = `Price below EMA9 and VWAP (score: ${score.toFixed(1)}, ev: ${ev.toFixed(3)})`;
    }
  }
  
  return {
    signal,
    price: currentCandle.close,
    score,
    ev,
    reason: signal === 'none' ? 'No signal' : reason,
    regime,
    session
  };
}

export { Candle };
