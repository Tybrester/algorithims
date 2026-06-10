import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { generateSignalBoof150, classifyRegime as classifyRegime150 } from './boof150.ts';
import { generateSignalBoof18 } from './boof18.ts';
import { generateSignalBoof14 } from './boof14.ts';
import { generateSignalBoof19 } from './boof19.ts';
import { generateSignalBoof19V2 } from './boof19v2.ts';
import { generateSignalBoof19Spy, generateExitBoof19Spy } from './boof19_spy.ts';
import { generateSignalBoof19Qqq, generateExitBoof19Qqq } from './boof19_qqq.ts';
import { generateSignalBoof21 } from './boof21.ts';
import { getBoof22Signal } from './boof22.ts';
import { getBoof22v2Signal } from './boof22_v2.ts';
import { getBoof23Signal } from './boof23.ts';
import { getBoof23v2Signal } from './boof23_v2.ts';
import { getBoof24Signal } from './boof24.ts';

const ALLOWED_ORIGINS = ['https://boofcapital.com', 'https://www.boofcapital.com', 'http://localhost:3000'];
function getCorsHeaders(req: Request) {
  const origin = req.headers.get('origin') || '';
  const allowed = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return { 'Access-Control-Allow-Origin': allowed, 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };
}
const corsHeaders = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type', 'Access-Control-Allow-Methods': 'POST, OPTIONS' };

// ─────────────────────────────────────────────
// RISK MANAGEMENT CONSTANTS
// ─────────────────────────────────────────────

// Risk Management: Symbol-aware TP adjustments
const SYMBOL_TP_MULTIPLIER: Record<string, number> = {
  'AMD': 1.2,
  'TSLA': 1.0,
  'SPY': 0.9,
  'QQQ': 0.8,
  'NVDA': 1.0,
  'default': 1.0
};

// ─────────────────────────────────────────────
// MATH HELPERS
// ─────────────────────────────────────────────

function calcVWAP(candles: Candle[]): number {
  let cumTPV = 0, cumVol = 0;
  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    const vol = c.volume || 1;
    cumTPV += tp * vol;
    cumVol += vol;
  }
  return cumVol > 0 ? cumTPV / cumVol : 0;
}

function calcEMA(data: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const ema = new Array(data.length).fill(0);
  ema[0] = data[0];
  for (let i = 1; i < data.length; i++) ema[i] = data[i] * k + ema[i - 1] * (1 - k);
  return ema;
}

function calcATR(highs: number[], lows: number[], closes: number[], period: number): number[] {
  const tr = highs.map((h, i) => i === 0 ? h - lows[i] : Math.max(h - lows[i], Math.abs(h - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
  const atr = new Array(tr.length).fill(0);
  atr[period - 1] = tr.slice(0, period).reduce((a, b) => a + b) / period;
  for (let i = period; i < tr.length; i++) atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;
  return atr;
}

function calcSuperTrend(highs: number[], lows: number[], closes: number[], atrLen: number, mult: number) {
  const atr = calcATR(highs, lows, closes, atrLen);
  const n = closes.length;
  const trend = new Array(n).fill(1);
  const upperBand = new Array(n).fill(0);
  const lowerBand = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    const hl2 = (highs[i] + lows[i]) / 2;
    upperBand[i] = hl2 + mult * atr[i];
    lowerBand[i] = hl2 - mult * atr[i];
    if (i > 0) {
      lowerBand[i] = lowerBand[i] > lowerBand[i - 1] || closes[i - 1] < lowerBand[i - 1] ? lowerBand[i] : lowerBand[i - 1];
      upperBand[i] = upperBand[i] < upperBand[i - 1] || closes[i - 1] > upperBand[i - 1] ? upperBand[i] : upperBand[i - 1];
      if (trend[i - 1] === -1 && closes[i] > upperBand[i - 1]) trend[i] = 1;
      else if (trend[i - 1] === 1 && closes[i] < lowerBand[i - 1]) trend[i] = -1;
      else trend[i] = trend[i - 1];
    }
  }
  return { trend, upperBand, lowerBand };
}

function calcDMI(highs: number[], lows: number[], closes: number[], period: number) {
  const n = highs.length;
  const plusDM = new Array(n).fill(0);
  const minusDM = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const up = highs[i] - highs[i - 1];
    const down = lows[i - 1] - lows[i];
    if (up > down && up > 0) plusDM[i] = up;
    if (down > up && down > 0) minusDM[i] = down;
  }
  const atr = calcATR(highs, lows, closes, period);
  const smoothPlusDM = calcEMA(plusDM, period);
  const smoothMinusDM = calcEMA(minusDM, period);
  const plusDI = smoothPlusDM.map((v, i) => atr[i] ? (v / atr[i]) * 100 : 0);
  const minusDI = smoothMinusDM.map((v, i) => atr[i] ? (v / atr[i]) * 100 : 0);
  const dx = plusDI.map((v, i) => (v + minusDI[i]) ? Math.abs(v - minusDI[i]) / (v + minusDI[i]) * 100 : 0);
  const adx = new Array(n).fill(0);
  const start2 = period * 2 - 1;
  if (start2 < n) {
    const validDx = dx.slice(period - 1, start2);
    adx[start2] = validDx.reduce((a, b) => a + b, 0) / period;
    for (let i = start2 + 1; i < n; i++) adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period;
  }
  return { plusDI, minusDI, adx };
}

function calcRSI(closes: number[], period: number): number[] {
  const rsi: number[] = new Array(closes.length).fill(NaN);
  if (closes.length < period + 1) return rsi;
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  let avgGain = gains / period, avgLoss = losses / period;
  rsi[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    rsi[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return rsi;
}

// ─────────────────────────────────────────────
// RISK MANAGEMENT FUNCTIONS
// ─────────────────────────────────────────────

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

function calcRelativeVolume(volumes: number[], period: number = 20): number[] {
  const rvol: number[] = new Array(volumes.length).fill(0);
  for (let i = period; i < volumes.length; i++) {
    const avgVol = volumes.slice(i - period, i).reduce((a, b) => a + b, 0) / period;
    rvol[i] = avgVol > 0 ? volumes[i] / avgVol : 1;
  }
  return rvol;
}

function calcMACD(closes: number[], fast: number, slow: number, signal: number): { macdLine: number[], signalLine: number[], hist: number[] } {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macdLine = closes.map((_, i) => (isNaN(emaFast[i]) || isNaN(emaSlow[i])) ? NaN : emaFast[i] - emaSlow[i]);
  const validStart = macdLine.findIndex(v => !isNaN(v));
  const signalLine: number[] = new Array(closes.length).fill(NaN);
  if (validStart >= 0) {
    const emaSignal = calcEMA(macdLine.slice(validStart), signal);
    for (let i = 0; i < emaSignal.length; i++) signalLine[validStart + i] = emaSignal[i];
  }
  const hist = macdLine.map((v, i) => (isNaN(v) || isNaN(signalLine[i])) ? NaN : v - signalLine[i]);
  return { macdLine, signalLine, hist };
}

function generateSignalRSIMACD(candles: Candle[], tradeDirection = 'both'): { signal: 'buy' | 'sell' | 'none', price: number, trend: number, ema: number, adx: number, reason: string } {
  const closes = candles.map(c => c.close);
  const n = closes.length;
  const i = n - 2;
  const rsi = calcRSI(closes, 14);
  const ema50 = calcEMA(closes, 50);
  const { hist } = calcMACD(closes, 12, 26, 9);
  const curRSI = rsi[i], curEma = ema50[i], curHist = hist[i], curClose = closes[i];
  
  // Replay position state
  let inLong = false, inShort = false;
  for (let j = 50; j < i; j++) {
    const r = rsi[j], h = hist[j], e = ema50[j], c = closes[j];
    if (isNaN(r) || isNaN(h) || isNaN(e)) continue;
    const buyCond = (r < 30 || h > 0) && c > e;
    const sellCond = (r > 70 || h < 0) && c < e;
    if (!inLong && !inShort && buyCond) inLong = true;
    else if (!inLong && !inShort && sellCond) inShort = true;
    else if (inLong && sellCond) { inLong = false; inShort = true; }
    else if (inShort && buyCond) { inShort = false; inLong = true; }
  }
  
  const buyCond  = (curRSI < 30 || curHist > 0) && curClose > curEma;
  const sellCond = (curRSI > 70 || curHist < 0) && curClose < curEma;
  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `rsi=${curRSI?.toFixed(1)}, macd_hist=${curHist?.toFixed(4)}, ema=${curEma?.toFixed(2)}, close=${curClose?.toFixed(2)}, pos=${inLong ? 'long' : inShort ? 'short' : 'flat'}`;
  
  if (buyCond) {
    if (inShort) { signal = 'buy'; reason = `EXIT SHORT->LONG. ${reason}`; }
    else if (!inLong) { signal = 'buy'; reason = `ENTER LONG. ${reason}`; }
  } else if (sellCond) {
    if (inLong) { signal = 'sell'; reason = `EXIT LONG->SHORT. ${reason}`; }
    else if (!inShort && tradeDirection !== 'long') { signal = 'sell'; reason = `ENTER SHORT. ${reason}`; }
    else if (tradeDirection === 'long' && inLong) { signal = 'sell'; reason = `EXIT LONG (long-only). ${reason}`; }
  }
  return { signal, price: curClose, trend: buyCond ? 1 : -1, ema: curEma, adx: curRSI, reason };
}

// ─────────────────────────────────────────────
// SHARED HELPERS FOR BOOF 7.0 / 8.0
// ─────────────────────────────────────────────

function b50SMA(data: number[], period: number): number[] {
  const result: number[] = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    result.push(slice.reduce((a: number, b: number) => a + b, 0) / period);
  }
  return result;
}
function b50StdDev(data: number[], period: number): number {
  if (data.length < period) return 0;
  const slice = data.slice(-period);
  const mean = slice.reduce((a: number, b: number) => a + b, 0) / period;
  return Math.sqrt(slice.reduce((a: number, b: number) => a + Math.pow(b - mean, 2), 0) / period);
}
function b50Mean(data: number[]): number {
  return data.length > 0 ? data.reduce((a: number, b: number) => a + b, 0) / data.length : 0;
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

// ─────────────────────────────────────────────
// BOOF 7.0 + 8.0 — ADAPTIVE SCALPER ENGINE
// ─────────────────────────────────────────────

interface Boof70Regime {
  type: 'TREND_UP' | 'TREND_DOWN' | 'RANGE' | 'HIGH_VOL' | 'LOW_VOL' | 'EXPLOSIVE';
  adx: number; atr: number; atrPercent: number; bbWidth: number;
  maSlope: number; volatilityPercentile: number;
  shouldTrade: boolean; noTradeReason?: string;
}

function isNoTradeZone80(isCrypto: boolean): { skip: boolean; reason: string } {
  const utcHour = new Date().getUTCHours();
  if (isCrypto) {
    if (utcHour >= 3 && utcHour < 5) return { skip: true, reason: 'Crypto dead zone: 03-05 UTC' };
    return { skip: false, reason: '' };
  }
  if (utcHour < 13 || utcHour >= 20) return { skip: true, reason: `Outside NYSE hours (UTC ${utcHour}:00)` };
  return { skip: false, reason: '' };
}

function detectRegime80(highs: number[], lows: number[], closes: number[], volumes: number[]): Boof70Regime {
  const n = closes.length;
  const atrVals: number[] = [];
  for (let i = 1; i < n; i++) atrVals.push(Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1])));
  const atr = b50Mean(atrVals.slice(-14));
  const atrPercent = atr / closes[n-1] * 100;
  const adx = b50ADX(highs, lows, closes, 14);
  const sma20 = b50SMA(closes, 20);
  const std20 = b50StdDev(closes, 20);
  const bbUpper = sma20[sma20.length-1] + 2 * std20;
  const bbLower = sma20[sma20.length-1] - 2 * std20;
  const bbWidth = sma20[sma20.length-1] > 0 ? (bbUpper - bbLower) / sma20[sma20.length-1] : 0;
  const maRecent = sma20[sma20.length-1];
  const maOld = sma20[Math.max(0, sma20.length-6)];
  const maSlope = maOld > 0 ? (maRecent - maOld) / maOld * 100 : 0;
  const atrHistory: number[] = [];
  for (let i = Math.max(1, n-50); i < n; i++) atrHistory.push(Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1])));
  const atrMed = b50Mean(atrHistory);
  const volPercentile = atrMed > 0 ? Math.min(1, atr / (atrMed * 2)) : 0.5;
  const avgVol = b50Mean(volumes.slice(-20));
  const curVol = volumes[n-1] || 0;
  const relVol = avgVol > 0 ? curVol / avgVol : 1;
  let type: Boof70Regime['type'];
  let shouldTrade = true; let noTradeReason: string | undefined;
  const isExplosive = bbWidth > 0.08 && adx > 35 && volPercentile > 0.85;
  const isHighVol   = volPercentile > 0.75 || atrPercent > 3.5;
  const isLowVol    = volPercentile < 0.20 && bbWidth < 0.02;
  const isTrending  = adx > 22 && Math.abs(maSlope) > 0.15;
  const isRange     = adx < 18 && bbWidth < 0.04;
  if (isExplosive)             { type = 'EXPLOSIVE'; }
  else if (isHighVol && !isTrending) { type = 'HIGH_VOL'; shouldTrade = false; noTradeReason = `HIGH_VOL chop`; }
  else if (isLowVol)           { type = 'LOW_VOL';  shouldTrade = false; noTradeReason = `LOW_VOL dead zone`; }
  else if (isTrending)         { type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN'; }
  else if (isRange)            { type = 'RANGE'; }
  else                         { type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN'; }
  if (relVol < 0.4 && avgVol > 0) { shouldTrade = false; noTradeReason = `Low volume`; }
  return { type, adx, atr, atrPercent, bbWidth, maSlope, volatilityPercentile: volPercentile, shouldTrade, noTradeReason };
}

function runRegimeStrategy80(regime: Boof70Regime, candles: any[], tradeDirection: string): { signal: 'buy'|'sell'|'none'; reason: string } {
  const closes  = candles.map((c: any) => c.close);
  const highs   = candles.map((c: any) => c.high);
  const lows    = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1);
  const n = closes.length; const i = n - 2;
  const rsi = calcRSI(closes, 14); const curRSI = rsi[rsi.length-2] ?? 50;
  const atrVals: number[] = [];
  for (let j = 1; j < n; j++) atrVals.push(Math.max(highs[j]-lows[j], Math.abs(highs[j]-closes[j-1]), Math.abs(lows[j]-closes[j-1])));
  const atrNow = b50Mean(atrVals.slice(-14)); const atrAvg = b50Mean(atrVals.slice(-34,-14));
  const candleBody = Math.abs(closes[i] - candles[i].open);
  const candleBodyPct = candles[i].open > 0 ? candleBody / candles[i].open * 100 : 0;
  const atrSpike = atrNow > atrAvg * 2.0;
  const volAvg = b50Mean(volumes.slice(-20));
  const volSpike = volumes[i] > volAvg * 1.8;
  const bearFlush = closes[i] < candles[i].open && candleBodyPct > 0.12 && atrSpike && volSpike;
  const bullFlush = closes[i] > candles[i].open && candleBodyPct > 0.12 && atrSpike && volSpike;
  const ema21arr = calcEMA(closes, 21);
  const ema21Now = ema21arr[ema21arr.length-1]; const ema21Prev = ema21arr[ema21arr.length-2];
  const prevBearFlush = i >= 1 && closes[i-1] < candles[i-1].open && (candles[i-1].open > 0 ? Math.abs(closes[i-1]-candles[i-1].open)/candles[i-1].open*100 : 0) > 0.10;
  const recoveryBuy = curRSI < 30 && closes[i] > ema21Now && closes[i-1] <= ema21Prev && (prevBearFlush || curRSI < 25);
  if (regime.type === 'TREND_UP' || regime.type === 'TREND_DOWN' || regime.type === 'EXPLOSIVE') {
    const ema9 = calcEMA(closes, 9);
    const { hist } = calcMACD(closes, 12, 26, 9);
    const histLast = hist[hist.length-1] ?? 0; const histPrev = hist[hist.length-2] ?? 0;
    const emaUp = ema9[ema9.length-1] > ema21Now;
    const emaCrossedUp   = ema9[ema9.length-2] <= ema21Prev && emaUp;
    const emaCrossedDown = ema9[ema9.length-2] >= ema21Prev && !emaUp;
    const macdBull = histLast > 0 && histLast > histPrev; const macdBear = histLast < 0 && histLast < histPrev;
    const contBull = emaUp && macdBull && closes[i] > closes[i-1];
    const contBear = !emaUp && macdBear && closes[i] < closes[i-1];
    const rsiBuyOk = curRSI > 40 && curRSI < 75; const rsiSellOk = curRSI < 60 && curRSI > 25;
    const ema50arr = calcEMA(closes, 50);
    const sellSlopeOk = !(ema50arr[ema50arr.length-1] > ema50arr[Math.max(0, ema50arr.length-4)]);
    let signal: 'buy'|'sell'|'none' = 'none'; let reason = '';
    if      (recoveryBuy && tradeDirection !== 'short')                          { signal = 'buy';  reason = `Boof7.0 RECOVERY_BUY [${regime.type}] rsi=${curRSI.toFixed(1)}`; }
    else if (bearFlush && regime.type !== 'TREND_UP' && sellSlopeOk)            { signal = 'sell'; reason = `Boof7.0 FLUSH_BEAR [${regime.type}]`; }
    else if (bullFlush && regime.type !== 'TREND_DOWN')                          { signal = 'buy';  reason = `Boof7.0 FLUSH_BULL [${regime.type}]`; }
    else if ((emaCrossedUp  || contBull) && regime.type !== 'TREND_DOWN' && rsiBuyOk)               { signal = 'buy';  reason = `Boof7.0 BREAKOUT [${regime.type}] rsi=${curRSI.toFixed(1)}`; }
    else if ((emaCrossedDown || contBear) && regime.type !== 'TREND_UP'  && rsiSellOk && sellSlopeOk) { signal = 'sell'; reason = `Boof7.0 BREAKOUT [${regime.type}] rsi=${curRSI.toFixed(1)}`; }
    else { reason = `Boof7.0 NO_ENTRY [${regime.type}] rsi=${curRSI.toFixed(1)}`; }
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason };
  } else if (regime.type === 'RANGE') {
    const sma20 = b50SMA(closes, 20); const std20 = b50StdDev(closes, 20);
    const bbUpper = sma20[sma20.length-1] + 2 * std20; const bbLower = sma20[sma20.length-1] - 2 * std20;
    let signal: 'buy'|'sell'|'none' = 'none';
    if      (recoveryBuy && tradeDirection !== 'short')                   signal = 'buy';
    else if (closes[i] <= bbLower * 1.005 && curRSI < 40)                signal = 'buy';
    else if (closes[i] >= bbUpper * 0.995 && curRSI > 60)                signal = 'sell';
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 MEAN_REV [RANGE] rsi=${curRSI.toFixed(1)}` };
  }
  return { signal: 'none', reason: `Boof7.0 NO_STRATEGY regime=${regime.type}` };
}

function calcPositionSize80(regime: Boof70Regime, recentWinRate: number, consecutiveLosses: number): number {
  const base: Record<string, number> = { TREND_UP:1.0, TREND_DOWN:1.0, RANGE:0.75, HIGH_VOL:0.5, LOW_VOL:0.5, EXPLOSIVE:0.6 };
  let size = base[regime.type] || 1.0;
  if (recentWinRate >= 0.60) size *= 1.25; else if (recentWinRate < 0.40) size *= 0.60;
  if (consecutiveLosses >= 5) size *= 0.25; else if (consecutiveLosses >= 3) size *= 0.50;
  if (regime.volatilityPercentile > 0.80) size *= 0.70;
  return Math.max(0.10, Math.min(1.50, size));
}

function calcChoppinessIndex80(highs: number[], lows: number[], closes: number[], period = 14): number {
  const n = closes.length;
  if (n < period + 1) return 50;
  let atrSum = 0;
  for (let i = n - period; i < n; i++) atrSum += Math.max(highs[i]-lows[i], Math.abs(highs[i]-closes[i-1]), Math.abs(lows[i]-closes[i-1]));
  const hh = Math.max(...highs.slice(n - period));
  const ll = Math.min(...lows.slice(n - period));
  const range = hh - ll;
  if (range === 0) return 50;
  return Math.max(0, Math.min(100, 100 * Math.log10(atrSum / range) / Math.log10(period)));
}

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

interface Boof70Result {
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
  regimeDetails: Boof70Regime;
  ci?: number;
}

function detectRegime70(
  highs: number[], lows: number[], closes: number[], volumes: number[],
  is1m = false, is5m = false
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

  // Relaxed thresholds for 1m intervals (0DTE is naturally volatile)
  // Also relaxed for 5m options trading (need more signals)
  const explosiveThresh = is1m ? 0.06 : 0.07;
  const explosiveAdx = is1m ? 30 : 32;
  const explosiveVol = is1m ? 0.80 : 0.82;
  const highVolThresh = is1m ? 0.65 : 0.70;
  const highVolAtr = is1m ? 3.0 : 3.2;
  const lowVolThresh = is1m ? 0.10 : 0.15;
  const trendingAdx = is1m ? 18 : 20;
  const trendingSlope = is1m ? 0.10 : 0.12;
  const rangeAdx = is1m ? 15 : 16;
  const rangeBb = is1m ? 0.03 : 0.035;

  const isExplosive = bbWidth > explosiveThresh && adx > explosiveAdx && volPercentile > explosiveVol;
  const isHighVol   = volPercentile > highVolThresh || atrPercent > highVolAtr;
  const isLowVol    = volPercentile < lowVolThresh && bbWidth < 0.02;
  const isTrending  = adx > trendingAdx && Math.abs(maSlope) > trendingSlope;
  const isRange     = adx < rangeAdx && bbWidth < rangeBb;

  if (isExplosive) {
    type = 'EXPLOSIVE';
    // Explosive: trade with reduced size, wide stops
  } else if (isHighVol && !isTrending) {
    type = 'HIGH_VOL';
    // For 1m and 5m options, allow trading in high vol (options are naturally volatile)
    if (is1m || is5m) {
      shouldTrade = true;
    } else {
      shouldTrade = false;
      noTradeReason = `HIGH_VOL chop: ATR=${atrPercent.toFixed(2)}% ADX=${adx.toFixed(1)}`;
    }
  } else if (isLowVol) {
    type = 'LOW_VOL';
    // For 1m, allow trading in low vol with reduced size
    if (is1m) {
      shouldTrade = true;
    } else {
      shouldTrade = false;
      noTradeReason = `LOW_VOL dead zone: bbWidth=${bbWidth.toFixed(4)} volPct=${volPercentile.toFixed(2)}`;
    }
  } else if (isTrending) {
    type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN';
  } else if (isRange) {
    type = 'RANGE';
  } else {
    type = maSlope > 0 ? 'TREND_UP' : 'TREND_DOWN';
  }

  // Volume filter — skip if volume too thin (relaxed for 0DTE 1m)
  if (relVol < 0.25 && avgVol > 0) {
    shouldTrade = false;
    noTradeReason = `Low volume: ${curVol.toFixed(0)} = ${(relVol*100).toFixed(0)}% of avg`;
  }

  return { type, adx, atr, atrPercent, bbWidth, maSlope, volatilityPercentile: volPercentile, shouldTrade, noTradeReason };
}

function calcDynamicTPSL(regime: Boof70Regime, entryPrice: number): { tp: number; sl: number; tpPct: number; slPct: number } {
  // Base ATR multipliers per regime (increased for trending to allow room to breathe)
  const multipliers: Record<string, { tp: number; sl: number }> = {
    TREND_UP:   { tp: 4.5, sl: 1.8 },  // Ride the trend, wider SL for breathing room
    TREND_DOWN: { tp: 4.5, sl: 1.8 },
    RANGE:      { tp: 1.5, sl: 1.0 },  // Mean reversion = smaller targets
    HIGH_VOL:   { tp: 4.0, sl: 2.0 },  // Wide stops, big targets
    LOW_VOL:    { tp: 2.0, sl: 1.2 },  // Tight targets but not too tight
    EXPLOSIVE:  { tp: 5.0, sl: 2.5 },  // Explosive moves = big targets
  };
  const m = multipliers[regime.type] || multipliers['TREND_UP'];
  const tp = entryPrice + regime.atr * m.tp;
  const sl = entryPrice - regime.atr * m.sl;
  const tpPct = (tp - entryPrice) / entryPrice * 100;
  const slPct = (sl - entryPrice) / entryPrice * 100;
  return { tp, sl, tpPct, slPct };
}

function calcPositionSize70(regime: Boof70Regime, recentWinRate: number, consecutiveLosses: number): number {
  const base: Record<string, number> = { TREND_UP:1.0, TREND_DOWN:1.0, RANGE:0.75, HIGH_VOL:0.5, LOW_VOL:0.5, EXPLOSIVE:0.6 };
  let size = base[regime.type] || 1.0;
  if (recentWinRate >= 0.60) size *= 1.25; else if (recentWinRate < 0.40) size *= 0.60;
  if (consecutiveLosses >= 5) size *= 0.25; else if (consecutiveLosses >= 3) size *= 0.50;
  if (regime.volatilityPercentile > 0.80) size *= 0.70;
  return Math.max(0.10, Math.min(1.50, size));
}

function isNoTradeZone(isCrypto: boolean): { skip: boolean; reason: string } {
  const utcHour = new Date().getUTCHours();
  if (isCrypto) {
    if (utcHour >= 3 && utcHour < 5) return { skip: true, reason: 'Crypto dead zone: 03-05 UTC' };
  } else {
    // Stock market hours: 9:30 AM - 4:00 PM ET = 13:30 - 20:00 UTC
    if (utcHour < 13 || utcHour >= 20) return { skip: true, reason: 'Outside market hours (13:30-20:00 UTC)' };
  }
  return { skip: false, reason: '' };
}

function runRegimeStrategy(regime: Boof70Regime, candles: any[], tradeDirection = 'both', is1m = false): { signal: 'buy' | 'sell' | 'none'; reason: string } {
  const closes = candles.map((c: any) => c.close);
  const highs = candles.map((c: any) => c.high);
  const lows = candles.map((c: any) => c.low);
  const n = closes.length;
  const i = n - 2;
  const curClose = closes[i];
  const curRSI = calcRSI(closes, 14)[i];
  const ema20 = calcEMA(closes, 20);
  const ema20Val = ema20[ema20.length - 1] ?? curClose;

  if (regime.type === 'RANGE') {
    const sma20 = b50SMA(closes, 20); const std20 = b50StdDev(closes, 20);
    const bbUpper = sma20[sma20.length-1] + 2 * std20; const bbLower = sma20[sma20.length-1] - 2 * std20;
    let signal: 'buy'|'sell'|'none' = 'none';
    // Relaxed RSI for 1m
    const rsiOversold = is1m ? 35 : 40;
    const rsiOverbought = is1m ? 65 : 60;
    if      (curClose <= bbLower * 1.005 && curRSI < rsiOversold)                signal = 'buy';
    else if (curClose >= bbUpper * 0.995 && curRSI > rsiOverbought)                signal = 'sell';
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 MEAN_REV [RANGE] rsi=${curRSI.toFixed(1)}` };
  }

  if (regime.type === 'TREND_UP') {
    // Trend following: buy on pullback to EMA
    const prevClose = closes[i-1];
    const isPullback = curClose < prevClose && curClose > ema20Val;
    const rsiNotOverbought = curRSI < (is1m ? 70 : 65);
    let signal: 'buy'|'sell'|'none' = 'none';
    if (isPullback && rsiNotOverbought) signal = 'buy';
    if (tradeDirection === 'short' && signal === 'buy') signal = 'none';
    return { signal, reason: `Boof7.0 TREND_FOLLOW [TREND_UP] rsi=${curRSI.toFixed(1)}` };
  }

  if (regime.type === 'TREND_DOWN') {
    // Trend following: sell on pullback to EMA
    const prevClose = closes[i-1];
    const isPullback = curClose > prevClose && curClose < ema20Val;
    const rsiNotOversold = curRSI > (is1m ? 30 : 35);
    let signal: 'buy'|'sell'|'none' = 'none';
    if (isPullback && rsiNotOversold) signal = 'sell';
    if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
    return { signal, reason: `Boof7.0 TREND_FOLLOW [TREND_DOWN] rsi=${curRSI.toFixed(1)}` };
  }

  if (regime.type === 'EXPLOSIVE') {
    // Explosive: trade with momentum, wider stops
    const prevClose = closes[i-1];
    const prev2Close = closes[i-2];
    const momUp = curClose > prevClose && prevClose > prev2Close;
    const momDown = curClose < prevClose && prevClose < prev2Close;
    let signal: 'buy'|'sell'|'none' = 'none';
    if (momUp && curRSI < 75) signal = 'buy';
    if (momDown && curRSI > 25) signal = 'sell';
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 MOMENTUM [EXPLOSIVE] rsi=${curRSI.toFixed(1)}` };
  }

  if (regime.type === 'HIGH_VOL') {
    // High vol: trade with tight stops, quick entries
    const sma20 = b50SMA(closes, 20); const std20 = b50StdDev(closes, 20);
    const bbUpper = sma20[sma20.length-1] + 2 * std20; const bbLower = sma20[sma20.length-1] - 2 * std20;
    let signal: 'buy'|'sell'|'none' = 'none';
    // Trade bounces off BB in high vol
    if (curClose <= bbLower * 1.003 && curRSI < 45) signal = 'buy';
    if (curClose >= bbUpper * 0.997 && curRSI > 55) signal = 'sell';
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 VOLATILITY [HIGH_VOL] rsi=${curRSI.toFixed(1)}` };
  }

  if (regime.type === 'LOW_VOL') {
    // Low vol: trade breakouts from recent range
    const recentHighs = highs.slice(-10);
    const recentLows = lows.slice(-10);
    const maxHigh = Math.max(...recentHighs);
    const minLow = Math.min(...recentLows);
    const range = maxHigh - minLow;
    const rangeMid = (maxHigh + minLow) / 2;
    let signal: 'buy'|'sell'|'none' = 'none';
    // Breakout above recent high with momentum
    if (curClose > maxHigh * 0.998 && curRSI > 50) signal = 'buy';
    // Breakdown below recent low with momentum
    if (curClose < minLow * 1.002 && curRSI < 50) signal = 'sell';
    if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
    if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';
    return { signal, reason: `Boof7.0 BREAKOUT [LOW_VOL] rsi=${curRSI.toFixed(1)}` };
  }

  return { signal: 'none', reason: `Boof7.0 NO_STRATEGY regime=${regime.type}` };
}

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

  // Detect if running on 1m candles
  const avgSpacingSec = n > 2 ? (candles[n-1].time - candles[n-10].time) / (9 * 1000) : 300;
  const is1m = avgSpacingSec < 90;
  const is5m = !is1m && avgSpacingSec < 360; // 90-360s = 5m

  // ── 3. REGIME DETECTION ───────────────────────────────────────────────────
  const regime = detectRegime70(highs, lows, closes, volumes, is1m, is5m);

  if (!regime.shouldTrade) {
    return noResult(`Boof 7.0: skipping — ${regime.noTradeReason}`, false, undefined);
  }

  // ── 4. CHOPPINESS INDEX FILTER ────────────────────────────────────────────
  const ci = calcChoppinessIndex80(highs, lows, closes, 14);
  // Relaxed CI threshold for options (especially 0DTE which is naturally choppy)
  const ciThreshold = isCrypto ? 70 : 65;
  if (ci > ciThreshold) {
    return noResult(`Boof 7.0: skipping — too choppy (CI=${ci.toFixed(1)})`, false, undefined);
  }

  // ── 5. DYNAMIC TP/SL ─────────────────────────────────────────────────────
  const { tpPct, slPct } = calcDynamicTPSL(regime, curPrice);

  // ── 6. POSITION SIZING ────────────────────────────────────────────────────
  const positionSizePct = calcPositionSize70(regime, recentWinRate, consecutiveLosses);

  // ── 7. REGIME-BASED STRATEGY ─────────────────────────────────────────────
  const { signal, reason } = runRegimeStrategy(regime, candles, tradeDirection, is1m);

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

interface Boof80Context {
  recentTrades: { reason: string; pnlPct: number; regime: string }[];
  consecutiveLosses: number; recentWinRate: number; isCrypto: boolean;
}

function generateSignalBoof80(candles: any[], tradeDirection = 'both', context: Boof80Context = { recentTrades:[], consecutiveLosses:0, recentWinRate:0.5, isCrypto:false }): { signal:'buy'|'sell'|'none'; price:number; trend:number; ema:number; adx:number; reason:string; regime:string; dynamicTP:number; dynamicSL:number; positionSizePct:number; killSwitch:boolean; killReason?:string; choppiness:number; patternWeight:number; adaptedFromHistory:boolean } {
  const closes  = candles.map((c: any) => c.close);
  const highs   = candles.map((c: any) => c.high);
  const lows    = candles.map((c: any) => c.low);
  const volumes = candles.map((c: any) => c.volume || 1000000);
  const n = closes.length;
  const curPrice = closes[n-2] ?? closes[n-1];
  const { recentTrades, consecutiveLosses, recentWinRate, isCrypto } = context;
  const noResult = (reason: string, kill = false, killReason?: string) => ({ signal: 'none' as const, price: curPrice, trend: 0, ema: curPrice, adx: 0, reason, regime: 'NONE', dynamicTP: 0, dynamicSL: 0, positionSizePct: 0, killSwitch: kill, killReason, choppiness: 50, patternWeight: 1.0, adaptedFromHistory: false });
  if (n < 50)                        return noResult('Boof 8.0: insufficient data');
  if (consecutiveLosses >= 7)        return noResult(`Kill-switch: ${consecutiveLosses} consecutive losses`, true, `${consecutiveLosses} consecutive losses`);
  const timeCheck = isNoTradeZone80(isCrypto);
  if (timeCheck.skip)                return noResult(`Boof 8.0: ${timeCheck.reason}`);
  const regime = detectRegime80(highs, lows, closes, volumes);
  if (!regime.shouldTrade)           return noResult(`Boof 8.0: skipping — ${regime.noTradeReason}`);
  const ci = calcChoppinessIndex80(highs, lows, closes, 14);
  const marketState = ci > 62 ? 'CHOPPY' : ci < 38 ? 'TRENDING' : 'MIXED';
  if (ci > 61.8 && regime.type !== 'EXPLOSIVE') return noResult(`Boof 8.0: too choppy CI=${ci.toFixed(1)}`);
  const { signal, reason } = runRegimeStrategy80(regime, candles, tradeDirection);
  if (signal === 'none')             return noResult(`Boof 8.0 NO_ENTRY [${regime.type}] CI=${ci.toFixed(1)}`);
  // Pattern weight scoring
  const patternMatch = reason.match(/Boof7\.0\s+(\w+)/);
  const patternLabel = patternMatch?.[1] ?? 'UNKNOWN';
  const patternKey   = `${regime.type}:${patternLabel}`;
  const matched = recentTrades.filter((t: { reason: string; regime: string }) => t.reason?.includes(patternLabel) && t.regime === regime.type);
  const pWins   = matched.filter((t: { pnlPct: number }) => t.pnlPct > 0).length;
  const pLosses = matched.filter((t: { pnlPct: number }) => t.pnlPct <= 0).length;
  const patternWinRate = matched.length > 0 ? pWins / matched.length : 0.5;
  const avgWin  = pWins   > 0 ? matched.filter((t: { pnlPct: number }) => t.pnlPct > 0).reduce((a: number, t: { pnlPct: number }) => a + t.pnlPct, 0) / pWins : 0;
  const avgLoss = pLosses > 0 ? matched.filter((t: { pnlPct: number }) => t.pnlPct <= 0).reduce((a: number, t: { pnlPct: number }) => a + t.pnlPct, 0) / pLosses : 0;
  const expectancy = patternWinRate * avgWin + (1 - patternWinRate) * avgLoss;
  const patternWeight = Math.max(0.5, Math.min(1.5, 1.0 + expectancy / 4));
  const adaptedFromHistory = recentTrades.length >= 2;
  if (patternWeight < 0.65 && recentTrades.length >= 5) return noResult(`Boof 8.0: pattern ${patternKey} underperforming (${pWins}W/${pLosses}L)`);
  // Adaptive TP/SL
  const baseM: Record<string, { tp: number; sl: number }> = { TREND_UP:{tp:3.0,sl:1.2}, TREND_DOWN:{tp:3.0,sl:1.2}, RANGE:{tp:1.5,sl:1.0}, HIGH_VOL:{tp:4.0,sl:2.0}, LOW_VOL:{tp:1.0,sl:0.8}, EXPLOSIVE:{tp:5.0,sl:2.5} };
  const m = baseM[regime.type] || baseM['TREND_UP'];
  const ciScale     = ci > 62 ? 1.40 : ci < 38 ? 0.80 : 1.0 + (ci - 50) / 100; // Higher CI = wider TP/SL for choppy markets
  const volScale    = regime.volatilityPercentile > 0.75 ? 1.20 : regime.volatilityPercentile < 0.25 ? 0.85 : 1.0;
  const wrScale     = recentWinRate > 0.60 ? 1.15 : recentWinRate < 0.35 ? 0.75 : 1.0;
  const tpPct       = Math.max(15.0, Math.min(80,  ((curPrice + regime.atr * m.tp * ciScale * volScale * patternWeight * wrScale) - curPrice) / curPrice * 100));
  const slPct       = Math.max(-25, Math.min(-5.0, ((curPrice - regime.atr * m.sl * ciScale * volScale) - curPrice) / curPrice * 100));
  const trailPct    = Math.max(0.3, Math.min(3.0, regime.atr * 0.5 / curPrice * 100));
  const positionSizePct = calcPositionSize80(regime, recentWinRate, consecutiveLosses);
  const ema21val    = calcEMA(closes, 21);
  const fullReason  = `${reason} | CI=${ci.toFixed(1)}[${marketState}] pw=${patternWeight.toFixed(2)}(${pWins}W/${pLosses}L) tp=+${tpPct.toFixed(1)}% sl=${slPct.toFixed(1)}% trail=${trailPct.toFixed(1)}% adapted=${adaptedFromHistory}`;
  return { signal, price: curPrice, trend: regime.maSlope > 0 ? 1 : -1, ema: ema21val[ema21val.length-1] ?? curPrice, adx: regime.adx, reason: fullReason, regime: regime.type, dynamicTP: tpPct, dynamicSL: slPct, positionSizePct, killSwitch: false, choppiness: ci, patternWeight, adaptedFromHistory };
}

// ─────────────────────────────────────────────
// BOOF 2.0 ML-STYLE INDICATOR
// ─────────────────────────────────────────────

function generateSignalBoof20(candles: Candle[], tradeDirection = 'both', thresholdBuy = 0.0, thresholdSell = 0.0): { signal: 'buy' | 'sell' | 'none', price: number, trend: number, ema: number, adx: number, reason: string } {
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const n = closes.length;

  if (n < 25) {
    return { signal: 'none', price: closes[n - 1], trend: 0, ema: closes[n - 1], adx: 50, reason: 'Insufficient data for Boof 2.0' };
  }

  const length = 14, maFast = 5, maSlow = 20;

  // Past return
  const pastReturn: number[] = new Array(n).fill(0);
  for (let i = length; i < n; i++) {
    pastReturn[i] = (closes[i] - closes[i - length]) / closes[i - length];
  }

  // MA calculations
  const maFastVals: number[] = new Array(n).fill(NaN);
  const maSlowVals: number[] = new Array(n).fill(NaN);
  for (let i = maFast - 1; i < n; i++) {
    maFastVals[i] = closes.slice(i - maFast + 1, i + 1).reduce((a, b) => a + b, 0) / maFast;
  }
  for (let i = maSlow - 1; i < n; i++) {
    maSlowVals[i] = closes.slice(i - maSlow + 1, i + 1).reduce((a, b) => a + b, 0) / maSlow;
  }

  // RSI
  const rsi = calcRSI(closes, length);

  // Current bar
  const i = n - 2;
  const iPrev = i - 1;

  const calcPredicted = (idx: number) => {
    const rP = pastReturn[idx] || 0;
    const rM = (maFastVals[idx] - maSlowVals[idx]) / closes[idx] || 0;
    const rR = (rsi[idx] - 50) / 50 || 0;
    const atrSlice = highs.slice(idx - 13, idx + 1).map((h, j) => h - lows[idx - 13 + j]);
    const rA = Math.max(...atrSlice) / closes[idx] || 0;
    return 0.4 * rP + 0.3 * rM + 0.2 * rR - 0.1 * rA;
  };

  const predictedReturn = calcPredicted(i);
  const prevPredicted = iPrev >= 13 ? calcPredicted(iPrev) : 0;

  const curState = predictedReturn > thresholdBuy ? 1 : predictedReturn < thresholdSell ? -1 : 0;
  const prevState = prevPredicted > thresholdBuy ? 1 : prevPredicted < thresholdSell ? -1 : 0;
  const justFlipped = curState !== prevState;

  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `predicted=${predictedReturn.toFixed(4)}, rsi=${rsi[i]?.toFixed(1)}`;

  if (curState === 1 && justFlipped) {
    signal = 'buy';
    reason = `Boof 2.0 BUY CROSSOVER. ${reason}`;
  } else if (curState === -1 && justFlipped) {
    signal = 'sell';
    reason = `Boof 2.0 SELL CROSSOVER. ${reason}`;
  }

  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  return { signal, price: closes[i], trend: predictedReturn > 0 ? 1 : -1, ema: maSlowVals[i], adx: rsi[i], reason };
}

// ─────────────────────────────────────────────
// BOOF 3.0 — FAST REGIME SCALPER (1m optimized)
// Replaced KMeans (slow) with instant rule-based regime detection
// Same regime logic, ~100x faster execution
// ─────────────────────────────────────────────

type MarketRegime = 'Trend' | 'Range' | 'HighVol';

function generateSignalBoof30(candles: Candle[], tradeDirection = 'both'): { signal: 'buy' | 'sell' | 'none', price: number, trend: number, ema: number, adx: number, reason: string, regime?: string, rsi?: number, slope?: number, atr?: number } {
  const highs  = candles.map(c => c.high);
  const lows   = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const volumes = candles.map(c => (c as any).volume || 1000000);
  const n = closes.length;
  const i = n - 2;

  if (n < 30) return { signal: 'none', price: closes[n-1], trend: 0, ema: closes[n-1], adx: 50, reason: 'Insufficient data' };

  // ── FAST EMA9 / EMA21 ──
  const ema9  = calcEMA(closes, 9);
  const ema21 = calcEMA(closes, 21);
  const ema9Now  = ema9[ema9.length-1];
  const ema9Prev = ema9[ema9.length-2];
  const ema21Now  = ema21[ema21.length-1];
  const ema21Prev = ema21[ema21.length-2];
  const maSlope = ema9Now - ema9[Math.max(0, ema9.length-4)];

  // ── FAST ATR (last 14 bars only) ──
  let atrSum = 0;
  for (let j = Math.max(1, n-14); j < n; j++) {
    atrSum += Math.max(highs[j]-lows[j], Math.abs(highs[j]-closes[j-1]), Math.abs(lows[j]-closes[j-1]));
  }
  const atrVal = atrSum / Math.min(14, n-1);
  const atrPct = closes[i] > 0 ? atrVal / closes[i] * 100 : 1;

  // ── FAST ADX (simplified DI from last 14 bars) ──
  let dmPlus = 0, dmMinus = 0, tr = 0;
  for (let j = Math.max(1, n-14); j < n; j++) {
    const upMove = highs[j] - highs[j-1];
    const downMove = lows[j-1] - lows[j];
    dmPlus  += (upMove > downMove && upMove > 0) ? upMove : 0;
    dmMinus += (downMove > upMove && downMove > 0) ? downMove : 0;
    tr += Math.max(highs[j]-lows[j], Math.abs(highs[j]-closes[j-1]), Math.abs(lows[j]-closes[j-1]));
  }
  const diPlus  = tr > 0 ? 100 * dmPlus  / tr : 0;
  const diMinus = tr > 0 ? 100 * dmMinus / tr : 0;
  const adxVal  = (diPlus + diMinus) > 0 ? 100 * Math.abs(diPlus - diMinus) / (diPlus + diMinus) : 0;

  // ── RSI (last 14 bars) ──
  const rsiArr = calcRSI(closes, 14);
  const curRSI = rsiArr[rsiArr.length-2] ?? 50;

  // ── FAST VOLUME CHECK ──
  const volSlice = volumes.slice(-20);
  const volAvg = volSlice.reduce((a, b) => a + b, 0) / volSlice.length;
  const relVol = volAvg > 0 ? volumes[i] / volAvg : 1;

  // ── REGIME CLASSIFICATION (rule-based, replaces KMeans) ──
  let regime: MarketRegime;
  if (atrPct > 2.5 && adxVal < 20) {
    regime = 'HighVol';
  } else if (adxVal >= 18 && Math.abs(maSlope) > closes[i] * 0.0002) {
    regime = 'Trend';
  } else {
    regime = 'Range';
  }

  // ── SIGNAL LOGIC per regime ──
  const minSlope = closes[i] * 0.0002;
  const emaCrossUp   = ema9Prev <= ema21Prev && ema9Now > ema21Now;
  const emaCrossDown = ema9Prev >= ema21Prev && ema9Now < ema21Now;
  const contBull = ema9Now > ema21Now && maSlope > minSlope && closes[i] > closes[i-1];
  const contBear = ema9Now < ema21Now && maSlope < -minSlope && closes[i] < closes[i-1];

  // ── EMA DISTANCE FILTER: prevent buying tops / selling bottoms ──
  const priceVsEma = (closes[i] - ema21Now) / ema21Now * 100;
  const tooExtendedUp = priceVsEma > 0.5; // price > 0.5% above EMA21
  const tooExtendedDown = priceVsEma < -0.5; // price < 0.5% below EMA21

  // ── DISTANCE FROM HIGH/LOW FILTER: prevent buying at exact top / selling at exact bottom ──
  const recentHighs = highs.slice(-5);
  const recentLows = lows.slice(-5);
  const maxRecentHigh = Math.max(...recentHighs);
  const minRecentLow = Math.min(...recentLows);
  const nearHigh = (maxRecentHigh - closes[i]) / maxRecentHigh * 100 < 0.3; // within 0.3% of recent high
  const nearLow = (closes[i] - minRecentLow) / minRecentLow * 100 < 0.3; // within 0.3% of recent low

  // ── PULLBACK REQUIREMENT: wait for 1 candle of retracement ──
  const prevPrice = closes[i-1];
  const prev2Price = closes[i-2];
  const isPullbackUp = closes[i] < prevPrice && prevPrice > prev2Price; // price pulled back from high
  const isPullbackDown = closes[i] > prevPrice && prevPrice < prev2Price; // price pulled back from low

  let sigVal = 0;
  if (regime === 'Trend' || regime === 'HighVol') {
    if ((emaCrossUp  || contBull) && curRSI > 40 && curRSI < 75 && !tooExtendedUp && !nearHigh && isPullbackUp) sigVal = 1;
    else if ((emaCrossDown || contBear) && curRSI < 60 && curRSI > 25 && !tooExtendedDown && !nearLow && isPullbackDown) sigVal = -1;
  } else {
    // Range: BB bounce
    const sma20 = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
    const std20 = Math.sqrt(closes.slice(-20).reduce((a, b) => a + (b - sma20) ** 2, 0) / 20);
    const bbLower = sma20 - 2 * std20;
    const bbUpper = sma20 + 2 * std20;
    if (closes[i] <= bbLower * 1.005 && curRSI < 38 && !tooExtendedDown && !nearLow && isPullbackUp) sigVal = 1;
    else if (closes[i] >= bbUpper * 0.995 && curRSI > 62 && !tooExtendedUp && !nearHigh && isPullbackDown) sigVal = -1;
  }

  // Volume gate — skip thin volume
  if (relVol < 0.4) sigVal = 0;

  let signal: 'buy' | 'sell' | 'none' = sigVal === 1 ? 'buy' : sigVal === -1 ? 'sell' : 'none';
  const reason = `Boof3.0 ${signal.toUpperCase()} [${regime}] adx=${adxVal.toFixed(1)} rsi=${curRSI.toFixed(1)} slope=${maSlope.toFixed(3)} atr=${atrPct.toFixed(2)}%`;

  if (tradeDirection === 'long'  && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy')  signal = 'none';

  return { signal, price: closes[i], trend: maSlope > 0 ? 1 : -1, ema: ema21Now, adx: adxVal, reason, regime, rsi: curRSI, slope: maSlope, atr: atrVal };
}

// ─────────────────────────────────────────────
// BOOF 5.0 - QUANTITUTIONAL SIGNAL GENERATION
// Six-Factor Model: Momentum, Mean Reversion, Volatility, Trend, Volume, Microstructure
// ─────────────────────────────────────────────

function generateSignalBoof50(candles: Candle[], tradeDirection = 'both', trendFilterCandles?: Candle[]): { 
  signal: 'buy' | 'sell' | 'none', 
  price: number, 
  trend: number, 
  ema: number, 
  adx: number, 
  reason: string, 
  regime?: string, 
  rsi?: number, 
  slope?: number, 
  atr?: number,
  compositeScore?: number,
  positionSize?: number
} {
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const opens = candles.map(c => c.open);
  const volumes = (candles as any[]).map(c => (c as any).volume || 1000000);
  const n = closes.length;

  if (n < 50) return { signal: 'none', price: closes[n - 1], trend: 0, ema: closes[n - 1], adx: 0, reason: 'Insufficient data', compositeScore: 0, positionSize: 1 };

  const i = n - 2; // Current bar

  // ── FACTOR 1: MOMENTUM (Price Velocity & Acceleration) ──
  const ema20 = calcEMA(closes, 20);
  const ema50 = calcEMA(closes, 50);
  const ema200 = calcEMA(closes, 200);
  
  // Price momentum (10-period)
  const momentum = ((closes[i] - closes[i - 10]) / closes[i - 10]) * 100;
  const momentumPrev = ((closes[i - 1] - closes[i - 11]) / closes[i - 11]) * 100;
  const momentumAccel = momentum - momentumPrev;
  
  // Momentum score (-2 to +2)
  let momScore = 0;
  if (momentum > 1.5 && momentumAccel > 0) momScore = 2;
  else if (momentum > 0.5) momScore = 1;
  else if (momentum < -1.5 && momentumAccel < 0) momScore = -2;
  else if (momentum < -0.5) momScore = -1;

  // ── FACTOR 2: MEAN REVERSION (Z-Score & Bollinger Position) ──
  const sma20 = boof50SMA(closes, 20);
  const std20 = boof50StdDev(closes, 20);
  const zScore = std20 > 0 ? (closes[i] - sma20[sma20.length - 1]) / std20 : 0;
  
  // Bollinger position (0-1)
  const bbUpper = sma20[sma20.length - 1] + (2 * std20);
  const bbLower = sma20[sma20.length - 1] - (2 * std20);
  const bbPosition = bbUpper !== bbLower ? (closes[i] - bbLower) / (bbUpper - bbLower) : 0.5;
  
  // Mean reversion score (-1 to +1)
  let mrScore = 0;
  if (zScore < -1.5 && bbPosition < 0.1) mrScore = 1; // Oversold - bullish mean reversion
  else if (zScore > 1.5 && bbPosition > 0.9) mrScore = -1; // Overbought - bearish mean reversion

  // ── FACTOR 3: VOLATILITY REGIME ──
  const returns: number[] = [];
  for (let j = 1; j < n; j++) returns.push((closes[j] - closes[j - 1]) / closes[j - 1]);
  const currentVol = boof50StdDev(returns.slice(-20), 20);
  const volMean = boof50Mean(returns.slice(-50).map(r => Math.abs(r)));
  const volPercentile = volMean > 0 ? Math.min(1, currentVol / (volMean * 2)) : 0.5;
  
  // Volatility regime
  const highVol = volPercentile > 0.8;
  const lowVol = volPercentile < 0.2;
  
  // ATR for position sizing
  const atr = boof50ATR(highs, lows, closes, 14);
  const atrPercent = atr / closes[i] * 100;

  // ── FACTOR 4: TREND STRENGTH (ADX & Multi-Timeframe) ──
  const adx = boof50ADX(highs, lows, closes, 14);
  const strongTrend = adx > 25;
  const weakTrend = adx < 20;
  
  // Price vs EMA alignment
  const aboveEMA20 = closes[i] > ema20[ema20.length - 1];
  const aboveEMA50 = closes[i] > ema50[ema50.length - 1];
  const aboveEMA200 = closes[i] > ema200[ema200.length - 1];
  
  // Trend score (-2 to +2)
  let trendScore = 0;
  if (strongTrend && aboveEMA20 && aboveEMA50 && aboveEMA200) trendScore = 2;
  else if (aboveEMA20 && aboveEMA50) trendScore = 1;
  else if (strongTrend && !aboveEMA20 && !aboveEMA50 && !aboveEMA200) trendScore = -2;
  else if (!aboveEMA20 && !aboveEMA50) trendScore = -1;
  
  // Trend filter check (if provided)
  let trendAligned = true;
  if (trendFilterCandles && trendFilterCandles.length >= 50) {
    const tfCloses = trendFilterCandles.map(c => c.close);
    const tfEma = boof50SMA(tfCloses, 20); // Use SMA as proxy for EMA
    const tfPrice = tfCloses[tfCloses.length - 1];
    const tfEmaVal = tfEma[tfEma.length - 1];
    trendAligned = momScore > 0 ? tfPrice > tfEmaVal : tfPrice < tfEmaVal;
  }

  // ── FACTOR 5: VOLUME ANALYSIS ──
  const volSMA = boof50SMA(volumes, 20);
  const relVolume = volumes[i] / volSMA[volSMA.length - 1];
  const volIncreasing = relVolume > 1.2;
  
  // OBV momentum (simplified - just check last few bars)
  let obv = 0;
  for (let j = Math.max(1, n - 20); j < n; j++) {
    obv += closes[j] > closes[j - 1] ? volumes[j] : closes[j] < closes[j - 1] ? -volumes[j] : 0;
  }
  const obvMomentum = obv > 0;
  
  // Volume score (0 to 1)
  const volScore = (volIncreasing && obvMomentum) ? 1 : 0;

  // ── FACTOR 6: MARKET MICROSTRUCTURE ──
  const body = Math.abs(closes[i] - opens[i]);
  const wick = highs[i] - lows[i];
  const bodyRatio = wick > 0 ? body / wick : 0;
  
  // Rejection patterns
  const upperWick = highs[i] - Math.max(opens[i], closes[i]);
  const lowerWick = Math.min(opens[i], closes[i]) - lows[i];
  const upperRejection = wick > 0 ? upperWick / wick > 0.6 : false;
  const lowerRejection = wick > 0 ? lowerWick / wick > 0.6 : false;
  
  // Microstructure score (-1 to +1)
  let microScore = 0;
  if (lowerRejection && bodyRatio > 0.3) microScore = 1;
  else if (upperRejection && bodyRatio > 0.3) microScore = -1;

  // ── REGIME CLASSIFICATION ──
  let regime = 'UNCERTAIN';
  if (strongTrend && !weakTrend) regime = aboveEMA50 ? 'TREND_UP' : 'TREND_DOWN';
  else if (weakTrend && Math.abs(zScore) < 1) regime = 'RANGING';
  else if (highVol) regime = 'VOLATILE';

  // ── COMPOSITE SCORING ──
  // Base composite (-5 to +5)
  let composite = momScore + trendScore + mrScore + volScore + microScore;
  
  // Regime adjustments
  if (regime === 'RANGING') {
    // Mean reversion mode: fade extremes
    composite = -composite * 0.5;
  } else if (regime === 'VOLATILE' && !strongTrend) {
    // Chop mode: reduce signals
    composite = composite * 0.3;
  }
  
  // Smooth the composite
  const compositeSmooth = composite; // Could add EMA smoothing here

  // ── SIGNAL GENERATION ──
  const thresholdBuy = 1.5; // Lowered from 2.5 for 10-15 trades/day
  const thresholdSell = -1.5;
  
  // Require confirmation (2 bars)
  const rawBuy = compositeSmooth > thresholdBuy;
  const rawSell = compositeSmooth < thresholdSell;
  const prevBuy = i > 0 ? (momScore > 0 && trendScore > 0) : false;
  const prevSell = i > 0 ? (momScore < 0 && trendScore < 0) : false;
  
  let signal: 'buy' | 'sell' | 'none' = 'none';
  
  if (rawBuy && trendAligned && !highVol && regime !== 'VOLATILE') {
    signal = 'buy';
  } else if (rawSell && trendAligned && !highVol && regime !== 'VOLATILE') {
    signal = 'sell';
  }
  
  // Apply trade direction filter
  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  // ── POSITION SIZING (Kelly Criterion) ──
  // Win rate assumption based on composite strength
  const winRate = 0.55 + (Math.abs(compositeSmooth) / 10);
  const avgWinLossRatio = 2.0;
  const kelly = winRate - ((1 - winRate) / avgWinLossRatio);
  
  // Volatility adjustment
  const volAdj = highVol ? 0.5 : lowVol ? 1.2 : 1.0;
  const positionSize = Math.max(0.1, Math.min(1.0, kelly * volAdj));

  // ── REASON STRING ──
  const reason = `Boof 5.0 [${regime}] MOM=${momScore} TREND=${trendScore} MR=${mrScore} VOL=${volScore} MICRO=${microScore} COMPOSITE=${compositeSmooth.toFixed(2)} SIZE=${(positionSize * 100).toFixed(0)}%`;

  return { 
    signal, 
    price: closes[i], 
    trend: trendScore, 
    ema: ema50[ema50.length - 1], 
    adx, 
    reason, 
    regime, 
    rsi: zScore * 10 + 50, // Approximate RSI from z-score
    slope: momentum,
    atr,
    compositeScore: compositeSmooth,
    positionSize
  };
}

// ─────────────────────────────────────────────
// HELPER FUNCTIONS FOR BOOF 5.0
// ─────────────────────────────────────────────

function boof50SMA(data: number[], period: number): number[] {
  const result: number[] = [];
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    result.push(slice.reduce((a, b) => a + b, 0) / period);
  }
  return result;
}

function boof50StdDev(data: number[], period: number): number {
  if (data.length < period) return 0;
  const slice = data.slice(-period);
  const mean = slice.reduce((a, b) => a + b, 0) / period;
  const variance = slice.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / period;
  return Math.sqrt(variance);
}

function boof50Mean(data: number[]): number {
  return data.length > 0 ? data.reduce((a, b) => a + b, 0) / data.length : 0;
}

function boof50ATR(highs: number[], lows: number[], closes: number[], period: number): number {
  const trValues: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    trValues.push(tr);
  }
  return trValues.length >= period ? boof50Mean(trValues.slice(-period)) : 0;
}

function boof50ADX(highs: number[], lows: number[], closes: number[], period: number): number {
  const dmPlus: number[] = [];
  const dmMinus: number[] = [];
  const trValues: number[] = [];
  
  for (let i = 1; i < closes.length; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    dmPlus.push(upMove > downMove && upMove > 0 ? upMove : 0);
    dmMinus.push(downMove > upMove && downMove > 0 ? downMove : 0);
    
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    trValues.push(tr);
  }
  
  if (dmPlus.length < period) return 25;
  
  const diPlus = 100 * boof50Mean(dmPlus.slice(-period)) / boof50Mean(trValues.slice(-period));
  const diMinus = 100 * boof50Mean(dmMinus.slice(-period)) / boof50Mean(trValues.slice(-period));
  const dx = (diPlus + diMinus) > 0 ? 100 * Math.abs(diPlus - diMinus) / (diPlus + diMinus) : 0;
  
  return dx;
}

// ─────────────────────────────────────────────
// BOOF 6.0 — MULTI-TIMEFRAME SCALPING SYSTEM
// Best-of-breed: Renaissance regime detection + Citadel direction lock +
// TastyTrade IV filter + LBR-style pullback entry + TTM momentum confirmation
// Target: 10-15 high-quality scalp entries per day
// ─────────────────────────────────────────────
function generateSignalBoof60(
  candles: Candle[],           // signal-interval candles (e.g. 5m)
  candles1h: Candle[],         // 1h candles for trend lock
  candles15m: Candle[],        // 15m candles for EMA confirmation
  candles1m: Candle[],         // 1m candles for VWAP
  tradeDirection: string
): { signal: 'buy' | 'sell' | 'none', price: number, ema: number, adx: number, reason: string } {

  const n = candles.length;
  if (n < 30) return { signal: 'none', price: 0, ema: 0, adx: 0, reason: 'Not enough candles' };

  const closes  = candles.map(c => c.close);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume ?? 0);
  const curClose = closes[n - 1];
  const prevClose = closes[n - 2];
  const prev2Close = closes[n - 3];
  const prev3Close = closes[n - 4];

  // Detect if running on 1m candles by checking average spacing between candles
  const avgSpacingSec = n > 2 ? (candles[n-1].time - candles[n-10].time) / (9 * 1000) : 300;
  const is1m = avgSpacingSec < 90; // < 90s between candles = 1m

  // ── FACTOR 1: 1H TREND LOCK (direction-only gate) ──
  // Uses 1h EMA20 slope. Up = calls only. Down = puts only. Flat = skip.
  // Relaxed for 1m 0DTE - allow flat trend with other confirmations
  let trendBias: 'up' | 'down' | 'flat' = 'flat';
  if (candles1h.length >= 25) {
    const closes1h = candles1h.map(c => c.close);
    const ema1h = calcEMA(closes1h, 20);
    const emaLast = ema1h[ema1h.length - 1];
    const emaPrev = ema1h[ema1h.length - 5]; // slope over last 5 1h candles
    const emaSlope = (emaLast - emaPrev) / emaPrev;
    const price1h = closes1h[closes1h.length - 1];
    // Relaxed slope threshold for 1m
    const slopeThresh = is1m ? 0.0001 : 0.0003;
    if (price1h > emaLast && emaSlope > slopeThresh) trendBias = 'up';
    else if (price1h < emaLast && emaSlope < -slopeThresh) trendBias = 'down';
    // For 1m, if price is clearly on one side of EMA, use that as bias
    else if (is1m) {
      const priceVsEma = (price1h - emaLast) / emaLast * 100;
      if (priceVsEma > 0.2) trendBias = 'up';
      else if (priceVsEma < -0.2) trendBias = 'down';
    }
  }
  // For 1m, allow flat trend if other conditions are strong
  if (trendBias === 'flat' && !is1m) {
    return { signal: 'none', price: curClose, ema: 0, adx: 0, reason: 'Boof 6.0: 1h trend flat — no directional bias, skipping' };
  }

  // ── FACTOR 2: ADX TRENDING CONFIRMATION ──
  // 1m candles have naturally lower ADX values — use relaxed threshold
  const { adx: adxArr } = calcDMI(highs, lows, closes, 14);
  const adxVal = adxArr[adxArr.length - 1] ?? 0;
  const adxMin = is1m ? 12 : 18;
  if (adxVal < adxMin) {
    return { signal: 'none', price: curClose, ema: 0, adx: adxVal, reason: `Boof 6.0: ADX=${adxVal.toFixed(1)} too low (chop, min=${adxMin}), skipping` };
  }

  // ── FACTOR 3: EMA PRICE SIDE CONFIRMATION ──
  // On 1m: use 5m EMA20 (from candles15m reused as 5m ref, or fall back to 1m EMA50)
  // On 5m+: use 15m EMA20
  let ema15Val = 0;
  const emaLabel = is1m ? '5m' : '15m';
  if (candles15m.length >= 22) {
    const closes15m = candles15m.map(c => c.close);
    const emaPeriod = is1m ? 50 : 20; // 1m uses EMA50 on signal candles as proxy for 5m trend
    const ema15 = calcEMA(is1m ? closes : closes15m, emaPeriod);
    ema15Val = ema15[ema15.length - 1] ?? 0;
  }
  if (ema15Val > 0) {
    if (trendBias === 'up' && curClose < ema15Val) {
      return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: BUY blocked — close $${curClose.toFixed(2)} < ${emaLabel} EMA $${ema15Val.toFixed(2)}` };
    }
    if (trendBias === 'down' && curClose > ema15Val) {
      return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: SELL blocked — close $${curClose.toFixed(2)} > ${emaLabel} EMA $${ema15Val.toFixed(2)}` };
    }
  }

  // ── FACTOR 4: VWAP POSITION + BOUNCE ENTRY ──
  // Price must be on correct side of VWAP AND bouncing back toward it (pullback entry)
  let vwapVal = 0;
  let vwapConfirmed = false;
  if (candles1m.length >= 30) {
    vwapVal = calcVWAP(candles1m);
    const aboveVwap = curClose >= vwapVal;
    const prevAbove = prevClose >= vwapVal;
    // For calls: price above VWAP, bouncing up after a dip toward VWAP
    // For puts: price below VWAP, bouncing down after a push toward VWAP
    if (trendBias === 'up' && aboveVwap && prevAbove) vwapConfirmed = true;
    if (trendBias === 'down' && !aboveVwap && !prevAbove) vwapConfirmed = true;
  }
  if (!vwapConfirmed) {
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: VWAP position not confirmed for ${trendBias} bias (close=$${curClose.toFixed(2)} vwap=$${vwapVal.toFixed(2)})` };
  }

  // ── FACTOR 5: MACD HISTOGRAM FLIP (momentum turning) ──
  // 1m uses faster MACD 5/13/4 to reduce lag on 1m candles
  const { hist } = is1m ? calcMACD(closes, 5, 13, 4) : calcMACD(closes, 12, 26, 9);
  const histLast = hist[hist.length - 1] ?? 0;
  const histPrev = hist[hist.length - 2] ?? 0;
  const macdFlipBull = histLast > histPrev && histLast > 0; // histogram rising and positive
  const macdFlipBear = histLast < histPrev && histLast < 0; // histogram falling and negative
  // Also allow if hist just crossed zero
  const macdCrossedBull = histPrev <= 0 && histLast > 0;
  const macdCrossedBear = histPrev >= 0 && histLast < 0;
  const macdOK = trendBias === 'up'
    ? (macdFlipBull || macdCrossedBull)
    : (macdFlipBear || macdCrossedBear);
  if (!macdOK) {
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: MACD histogram not confirming ${trendBias} momentum (hist=${histLast.toFixed(4)})` };
  }

  // ── FACTOR 6: MOMENTUM BUILDING ──
  // 1m: net direction over last 5 candles (less strict — 1m candles reverse constantly)
  // 5m+: 3 consecutive closes in direction
  let momOK = false;
  if (is1m) {
    const ref5 = closes[n - 6] ?? closes[0];
    momOK = trendBias === 'up' ? curClose > ref5 : curClose < ref5;
  } else {
    const momUp = curClose > prevClose && prevClose > prev2Close;
    const momDown = curClose < prevClose && prevClose < prev2Close;
    const momUpRelaxed = (curClose > prev2Close) && (curClose > prevClose || prevClose > prev2Close);
    const momDownRelaxed = (curClose < prev2Close) && (curClose < prevClose || prevClose < prev2Close);
    momOK = trendBias === 'up' ? (momUp || momUpRelaxed) : (momDown || momDownRelaxed);
  }
  if (!momOK) {
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: Momentum not building for ${trendBias} (close=${curClose.toFixed(2)} is1m=${is1m})` };
  }

  // ── FACTOR 7: VOLUME CONFIRMATION ──
  // Current candle volume should be above 20-period average (conviction)
  const avgVol = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const curVol = volumes[n - 1];
  const volConfirmed = avgVol <= 0 || curVol >= avgVol * 0.8; // 80% of avg minimum
  if (!volConfirmed) {
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: Volume too low (cur=${curVol} < 80% avg=${(avgVol*0.8).toFixed(0)})` };
  }

  // ── FACTOR 8: EMA DISTANCE FILTER: prevent buying tops / selling bottoms ──
  // Relaxed thresholds for 1m intervals (0DTE is naturally more volatile)
  const emaDistanceThreshold = is1m ? 1.2 : 0.5; // 1.2% for 1m, 0.5% for 5m+
  if (ema15Val > 0) {
    const priceVsEma = (curClose - ema15Val) / ema15Val * 100;
    const tooExtendedUp = priceVsEma > emaDistanceThreshold;
    const tooExtendedDown = priceVsEma < -emaDistanceThreshold;
    if (trendBias === 'up' && tooExtendedUp) {
      return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: BUY blocked — price too extended above EMA (${priceVsEma.toFixed(2)}%)` };
    }
    if (trendBias === 'down' && tooExtendedDown) {
      return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: SELL blocked — price too extended below EMA (${priceVsEma.toFixed(2)}%)` };
    }
  }

  // ── FACTOR 9: DISTANCE FROM HIGH/LOW FILTER: prevent buying at exact top / selling at exact bottom ──
  // Relaxed threshold for 1m intervals (0DTE needs more flexibility)
  const nearHighThreshold = is1m ? 0.8 : 0.3; // 0.8% for 1m, 0.3% for 5m+
  const recentHighs = highs.slice(-5);
  const recentLows = lows.slice(-5);
  const maxRecentHigh = Math.max(...recentHighs);
  const minRecentLow = Math.min(...recentLows);
  const nearHigh = (maxRecentHigh - curClose) / maxRecentHigh * 100 < nearHighThreshold;
  const nearLow = (curClose - minRecentLow) / minRecentLow * 100 < nearHighThreshold;

  // ── FACTOR 10: PULLBACK REQUIREMENT: wait for 1 candle of retracement ──
  // For 1m 0DTE, relaxed pullback requirement (need speed, not perfect entries)
  const isPullbackUp = curClose < prevClose && prevClose > prev2Close; // price pulled back from high
  const isPullbackDown = curClose > prevClose && prevClose < prev2Close; // price pulled back from low
  if (trendBias === 'up' && (!isPullbackUp && !is1m)) {
    const reason = nearHigh ? 'BUY blocked — price too close to recent high' : 'BUY blocked — no pullback detected';
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: ${reason} (cur=${curClose.toFixed(2)} prev=${prevClose.toFixed(2)} prev2=${prev2Close.toFixed(2)})` };
  }
  if (trendBias === 'down' && (!isPullbackDown && !is1m)) {
    const reason = nearLow ? 'SELL blocked — price too close to recent low' : 'SELL blocked — no pullback detected';
    return { signal: 'none', price: curClose, ema: ema15Val, adx: adxVal, reason: `Boof 6.0: ${reason} (cur=${curClose.toFixed(2)} prev=${prevClose.toFixed(2)} prev2=${prev2Close.toFixed(2)})` };
  }

  // ── APPLY TRADE DIRECTION OVERRIDE ──
  let signal: 'buy' | 'sell' | 'none' = trendBias === 'up' ? 'buy' : 'sell';
  if (tradeDirection === 'long' && signal === 'sell') signal = 'none';
  if (tradeDirection === 'short' && signal === 'buy') signal = 'none';

  const reason = `Boof 6.0 [${trendBias.toUpperCase()}${is1m?'/1m':'/5m+'}] adx=${adxVal.toFixed(1)} macd=${histLast.toFixed(4)} vwap=$${vwapVal.toFixed(2)} ema=$${ema15Val.toFixed(2)} vol=${curVol}/${avgVol.toFixed(0)}${is1m?' (1m-tuned)':''}`;

  return { signal, price: curClose, ema: ema15Val, adx: adxVal, reason };
}

// ═══════════════════════════════════════════════════════════════════════════════
// BOOF 9.0 — PRECISION SNIPER
// Ultra-strict multi-timeframe confluence: Only 1 trade per 3 days per stock
// Requires: Daily trend + 4h/1h alignment, strong ADX, low CI, volume spike, pullback
// ═══════════════════════════════════════════════════════════════════════════════
function generateSignalBoof90(
  candles: Candle[],
  candles1d: Candle[],
  candles4h: Candle[],
  tradeDirection = 'both'
): { signal: 'buy' | 'sell' | 'none', price: number, trend: number, ema: number, adx: number, reason: string } {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 1000000);
  const n = closes.length;
  const curClose = closes[n - 1];

  if (n < 50) return { signal: 'none', price: curClose, trend: 0, ema: 0, adx: 0, reason: 'Boof 9.0: insufficient data' };

  // ── 1. DAILY TREND CONFIRMATION ─────────────────────────────────────────
  const closes1d = candles1d.map(c => c.close);
  const ema50d = calcEMA(closes1d, 50);
  const ema200d = calcEMA(closes1d, 200);
  const curEMA50d = ema50d[ema50d.length - 1];
  const curEMA200d = ema200d[ema200d.length - 1];
  
  const dailyBullish = curClose > curEMA50d && curClose > curEMA200d && curEMA50d > curEMA200d;
  const dailyBearish = curClose < curEMA50d && curClose < curEMA200d && curEMA50d < curEMA200d;
  
  if (!dailyBullish && !dailyBearish) {
    return { signal: 'none', price: curClose, trend: 0, ema: curEMA50d, adx: 0, reason: 'Boof 9.0: no daily trend alignment' };
  }

  // ── 2. 4H TIMEFRAME ALIGNMENT ─────────────────────────────────────────────
  const closes4h = candles4h.map(c => c.close);
  const ema20_4h = calcEMA(closes4h, 20);
  const curEMA20_4h = ema20_4h[ema20_4h.length - 1];
  const ema50_4h = calcEMA(closes4h, 50);
  const curEMA50_4h = ema50_4h[ema50_4h.length - 1];
  
  const trend4h = dailyBullish ? (curEMA20_4h > curEMA50_4h) : (curEMA20_4h < curEMA50_4h);
  if (!trend4h) {
    return { signal: 'none', price: curClose, trend: 0, ema: curEMA50d, adx: 0, reason: 'Boof 9.0: 4h trend misaligned' };
  }

  // ── 3. STRONG ADX ─────────────────────────────────────────────────────────
  const { adx: adxArr } = calcDMI(highs, lows, closes, 14);
  const adxVal = adxArr[adxArr.length - 1] || 0;
  if (adxVal < 30) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: `Boof 9.0: ADX too weak (${adxVal.toFixed(1)} < 30)` };
  }

  // ── 4. LOW CHOPPINESS INDEX ───────────────────────────────────────────────
  const ci = calcChoppinessIndex80(highs, lows, closes, 14);
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
  const avgVol = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const curVol = volumes[n - 1];
  const volSpike = curVol > avgVol * 1.5;
  if (!volSpike) {
    return { signal: 'none', price: curClose, trend: dailyBullish ? 1 : -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: no volume spike' };
  }

  // ── 8. PULLBACK FROM SWING HIGH/LOW ────────────────────────────────────────
  const recentHighs = highs.slice(-20);
  const recentLows = lows.slice(-20);
  const swingHigh = Math.max(...recentHighs);
  const swingLow = Math.min(...recentLows);
  
  const prevClose = closes[n - 2];
  const prev2Close = closes[n - 3];
  const isPullbackUp = curClose < prevClose && prevClose > prev2Close;
  const isPullbackDown = curClose > prevClose && prevClose < prev2Close;
  
  if (dailyBullish && !isPullbackUp) {
    return { signal: 'none', price: curClose, trend: 1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: no pullback detected' };
  }
  if (dailyBearish && !isPullbackDown) {
    return { signal: 'none', price: curClose, trend: -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: no pullback detected' };
  }

  // ── 9. NOT NEAR RECENT EXTREMES ─────────────────────────────────────────────
  const nearHigh = (swingHigh - curClose) / swingHigh * 100 < 0.3;
  const nearLow = (curClose - swingLow) / swingLow * 100 < 0.3;
  
  if (dailyBullish && nearHigh) {
    return { signal: 'none', price: curClose, trend: 1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: too close to swing high' };
  }
  if (dailyBearish && nearLow) {
    return { signal: 'none', price: curClose, trend: -1, ema: curEMA50d, adx: adxVal, reason: 'Boof 9.0: too close to swing low' };
  }

  // ── 10. TIME OF DAY FILTER ─────────────────────────────────────────────────
  const utcHour = new Date().getUTCHours();
  const isMarketHours = utcHour >= 14 && utcHour < 20;
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
// BOOF 15.0 — REGIME-BASED ADAPTIVE TRADER
// Separated entry signals (trend + momentum) from exit signals (ATR-based stops)
// Entry: VWAP + EMA alignment, RVOL > 1.2, volatility check
// Exit: Hard stop (1.2x ATR), structure break (VWAP/EMA), trailing stop
// ═══════════════════════════════════════════════════════════════════════════════
function classifyRegime15(highs: number[], lows: number[], closes: number[]): 'EXPANSION' | 'COMPRESSION' | 'NORMAL' {
  const atr = calcATR(highs, lows, closes, 14);
  const atrAvg = atr.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const ratio = atr[atr.length - 1] / atrAvg;

  if (ratio > 1.1) return 'EXPANSION';
  if (ratio < 0.9) return 'COMPRESSION';
  return 'NORMAL';
}

function generateEntrySignals15(
  candles: Candle[],
  tradeDirection = 'both',
  symbol = 'SPY'
): { signal: 'buy' | 'sell' | 'none', price: number, reason: string, regime: string, ev?: number, stopLoss?: number, takeProfit?: number } {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 1000000);
  const n = closes.length;
  const curClose = closes[n - 1];

  if (n < 50) return { signal: 'none', price: curClose, reason: 'Boof 15.0: insufficient data', regime: 'UNKNOWN' };

  // Indicators
  const ema9 = calcEMA(closes, 9);
  const ema20 = calcEMA(closes, 20);
  const vwap = calcVWAP(candles);
  const atr = calcATR(highs, lows, closes, 14);
  const rvol = calcRelativeVolume(volumes, 20);

  const curEMA9 = ema9[ema9.length - 1];
  const curEMA20 = ema20[ema20.length - 1];
  const curRVOL = rvol[rvol.length - 1];
  const curATR = atr[atr.length - 1];

  // Regime classification
  const regime = classifyRegime15(highs, lows, closes);

  // Core trend bias
  const longBias = curClose > vwap && curEMA9 > curEMA20;
  const shortBias = curClose < vwap && curEMA9 < curEMA20;

  // Momentum confirmation
  const momentum = curRVOL > 1.2;

  // Volatility check (avoid dead conditions)
  const volatilityOk = (highs[n - 1] - lows[n - 1]) > curATR * 0.6;

  if (!momentum) {
    return { signal: 'none', price: curClose, reason: `Boof 15.0: RVOL too low (${curRVOL.toFixed(2)} < 1.2)`, regime };
  }

  if (!volatilityOk) {
    return { signal: 'none', price: curClose, reason: `Boof 15.0: Volatility too low (range ${(highs[n-1] - lows[n-1]).toFixed(2)} < ATR*0.6)`, regime };
  }

  // Calculate simple score based on conditions
  let score = 0;
  if (curRVOL > 1.5) score += 1;
  if (curATR > curATR * 1.02) score += 1;
  if (longBias || shortBias) score += 1;

  // Calculate EV (simplified for options - no session multiplier for now)
  const baseEv = (score - 1.5) * 0.05;
  const ev = Math.max(0, baseEv);

  if (longBias && tradeDirection !== 'short') {
    // Calculate dynamic risk parameters
    const { slDistance, tpDistance } = calculateRiskParameters(symbol, ev, curATR);
    const stopLoss = curClose - slDistance;
    const takeProfit = curClose + tpDistance;

    return {
      signal: 'buy',
      price: curClose,
      reason: `Boof 15.0: LONG | Regime=${regime} RVOL=${curRVOL.toFixed(2)} EV=${ev.toFixed(3)}`,
      regime,
      ev,
      stopLoss,
      takeProfit
    };
  }

  if (shortBias && tradeDirection !== 'long') {
    // Calculate dynamic risk parameters
    const { slDistance, tpDistance } = calculateRiskParameters(symbol, ev, curATR);
    const stopLoss = curClose + slDistance;
    const takeProfit = curClose - tpDistance;

    return {
      signal: 'sell',
      price: curClose,
      reason: `Boof 15.0: SHORT | Regime=${regime} RVOL=${curRVOL.toFixed(2)} EV=${ev.toFixed(3)}`,
      regime,
      ev,
      stopLoss,
      takeProfit
    };
  }

  return { signal: 'none', price: curClose, reason: 'Boof 15.0: no trend bias', regime };
}

function generateExitSignals15(
  candles: Candle[],
  positionDirection: 'LONG' | 'SHORT',
  entryPrice: number,
  entryTime: number
): { shouldExit: boolean, exitPrice: number, exitReason: string } {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 1000000);
  const n = closes.length;

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

  const curClose = closes[n - 1];

  // Hard stop
  if (positionDirection === 'LONG' && curClose < stop) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'stop_loss' };
  }
  if (positionDirection === 'SHORT' && curClose > stop) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'stop_loss' };
  }

  // Structure break exit
  if (positionDirection === 'LONG' && (curClose < curVWAP || curEMA9 < curEMA20)) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'structure_break' };
  }
  if (positionDirection === 'SHORT' && (curClose > curVWAP || curEMA9 > curEMA20)) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'structure_break' };
  }

  // Trailing stop (would need to track max_favorable from trade state)
  // For now, structure break serves as dynamic exit

  return { shouldExit: false, exitPrice: curClose, exitReason: 'hold' };
}

// ─────────────────────────────────────────────
// BOOF 16.0 - QUANT-ENHANCED TRADING ENGINE
// ─────────────────────────────────────────────

// Transaction cost model
function applyTransactionCosts(
  price: number,
  side: 'buy' | 'sell',
  atr: number
): number {
  const spread = price * 0.0005; // 5 bps
  const slippage = atr * 0.05;   // ATR-based slippage
  const commission = 0.65;       // options-like flat fee

  const cost = spread + slippage + commission;

  return side === 'buy'
    ? price + cost
    : price - cost;
}

// Statistical helpers
function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function stdDev(values: number[]): number {
  if (values.length === 0) return 0;
  const avg = mean(values);
  const variance = values.reduce((sum, val) => sum + Math.pow(val - avg, 2), 0) / values.length;
  return Math.sqrt(variance);
}

function calcSharpe(returns: number[]): number {
  const avg = mean(returns);
  const std = stdDev(returns);
  return std === 0 ? 0 : (avg / std) * Math.sqrt(252);
}

function calcSortino(returns: number[]): number {
  const avg = mean(returns);
  const downside = returns.filter(r => r < 0);
  const downsideStd = stdDev(downside);
  return downsideStd === 0 ? 0 : (avg / downsideStd) * Math.sqrt(252);
}

function confidenceInterval(returns: number[]) {
  const avg = mean(returns);
  const std = stdDev(returns);
  const n = returns.length;
  const z = 1.96;
  return {
    lower: avg - z * (std / Math.sqrt(n)),
    upper: avg + z * (std / Math.sqrt(n)),
  };
}

// Kelly criterion position sizing
function kellyCriterion(winRate: number, avgWin: number, avgLoss: number): number {
  const b = avgLoss > 0 ? avgWin / avgLoss : 1;
  const p = winRate;
  const q = 1 - p;
  return (b * p - q) / b;
}

function fractionalKelly(kelly: number, fraction = 0.25): number {
  return Math.max(0, kelly * fraction);
}

function positionSize(equity: number, kellyFraction: number): number {
  return equity * kellyFraction;
}

// Factor analysis
interface TradeFactor {
  factor: string;
  return: number;
  winrate: number;
  trades: number;
}

function classifyTradeFactor(trade: any): string {
  if (trade.rvol > 1.5 && trade.emaTrend) return 'momentum';
  if (trade.rvol < 1.0 && trade.vwapReversion) return 'mean_reversion';
  if (trade.atrExpansion) return 'vol_expansion';
  return 'neutral';
}

function factorPerformance(trades: any[]): TradeFactor[] {
  const groups: Record<string, any[]> = {};
  
  for (const trade of trades) {
    const factor = classifyTradeFactor(trade);
    if (!groups[factor]) groups[factor] = [];
    groups[factor].push(trade);
  }

  return Object.entries(groups).map(([factor, ts]) => ({
    factor,
    return: ts.reduce((sum, t) => sum + (t.pnl || 0), 0),
    winrate: ts.filter(t => t.win).length / ts.length,
    trades: ts.length
  }));
}

// Walk-forward analysis
interface WalkForwardResult {
  period: string;
  sharpe: number;
  returnPct: number;
  maxDrawdown: number;
  trades: number;
}

interface TradeResult {
  pnl: number;
  entryTime: number;
  exitTime: number;
}

interface EquityCurve {
  returns: number[];
  totalReturn: number;
  equity: number[];
}

function buildEquityCurve(trades: TradeResult[]): EquityCurve {
  const equity = [10000]; // Starting equity
  const returns: number[] = [];
  
  for (const trade of trades) {
    const prevEquity = equity[equity.length - 1];
    const newEquity = prevEquity + trade.pnl;
    equity.push(newEquity);
    returns.push(trade.pnl / prevEquity);
  }

  const totalReturn = (equity[equity.length - 1] - equity[0]) / equity[0];
  
  return { returns, totalReturn, equity };
}

function calcMaxDrawdown(equity: number[]): number {
  let maxDrawdown = 0;
  let peak = equity[0];
  
  for (const val of equity) {
    if (val > peak) peak = val;
    const drawdown = (peak - val) / peak;
    if (drawdown > maxDrawdown) maxDrawdown = drawdown;
  }
  
  return maxDrawdown;
}

function walkForward(
  candles: Candle[],
  windowSize: number,
  stepSize: number,
  runStrategy: (slice: Candle[]) => TradeResult[]
): WalkForwardResult[] {
  const results: WalkForwardResult[] = [];

  for (let start = 0; start + windowSize < candles.length; start += stepSize) {
    const window = candles.slice(start, start + windowSize);
    const trades = runStrategy(window);
    const equity = buildEquityCurve(trades);

    results.push({
      period: `${start}-${start + windowSize}`,
      sharpe: calcSharpe(equity.returns),
      returnPct: equity.totalReturn,
      maxDrawdown: calcMaxDrawdown(equity.equity),
      trades: trades.length,
    });
  }

  return results;
}

// Boof 16.0 Entry Signals
function generateEntrySignals16(
  candles: Candle[],
  symbol = 'SPY',
  equity = 10000,
  tradeDirection: 'long' | 'short' | 'both' = 'both'
): { 
  signal: 'buy' | 'sell' | 'none'; 
  price: number; 
  regime: string; 
  ev?: number; 
  positionSize?: number; 
  stopLoss?: number; 
  takeProfit?: number; 
  probability?: number;
  reason: string;
} {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 1);

  const n = closes.length;
  const price = closes[n - 1];

  if (n < 100) {
    return { signal: 'none', reason: 'Boof 16.0: insufficient data', price, regime: 'UNKNOWN' };
  }

  const ema9 = calcEMA(closes, 9);
  const ema20 = calcEMA(closes, 20);
  const atr = calcATR(highs, lows, closes, 14);
  const rvol = calcRelativeVolume(volumes, 20);
  const vwap = calcVWAP(candles);

  const regime = classifyRegime15(highs, lows, closes);

  const trendScore =
    (price > vwap ? 1 : -1) +
    (ema9[n - 1] > ema20[n - 1] ? 1 : -1);

  const momentumScore = rvol[n - 1] > 1.2 ? 1 : 0;
  const volScore = atr[n - 1] > atr[n - 2] ? 1 : 0;

  // PROBABILITY MODEL (simple logistic-ish proxy)
  const rawScore = trendScore + momentumScore + volScore;
  const probUp = 1 / (1 + Math.exp(-rawScore));
  const expectedMove = atr[n - 1] * (probUp - 0.5);

  // COST MODEL
  const costEstimate = price * 0.001;
  const ev = expectedMove - costEstimate;

  const kelly = kellyCriterion(probUp, expectedMove, atr[n - 1]);
  const kellyFraction = fractionalKelly(kelly, 0.25);
  const posSize = positionSize(equity, kellyFraction);

  const sl = price - 0.8 * atr[n - 1];
  const tp = price + 1.6 * atr[n - 1];

  if (ev <= 0) {
    return {
      signal: 'none',
      price,
      regime,
      reason: `Boof 16.0: no positive EV (${ev.toFixed(4)})`
    };
  }

  if (trendScore > 0 && tradeDirection !== 'short') {
    return {
      signal: 'buy',
      price,
      regime,
      ev,
      positionSize: posSize,
      stopLoss: sl,
      takeProfit: tp,
      probability: probUp,
      reason: `Boof 16.0: LONG | Regime=${regime} EV=${ev.toFixed(4)} Prob=${probUp.toFixed(2)}`
    };
  }

  if (trendScore < 0 && tradeDirection !== 'long') {
    return {
      signal: 'sell',
      price,
      regime,
      ev,
      positionSize: posSize,
      stopLoss: price + 0.8 * atr[n - 1],
      takeProfit: price - 1.6 * atr[n - 1],
      probability: 1 - probUp,
      reason: `Boof 16.0: SHORT | Regime=${regime} EV=${ev.toFixed(4)} Prob=${(1 - probUp).toFixed(2)}`
    };
  }

  return {
    signal: 'none',
    price,
    regime,
    reason: 'Boof 16.0: no alignment'
  };
}

// Boof 16.0 Exit Signals
function generateExitSignals16(
  candles: Candle[],
  positionDirection: 'LONG' | 'SHORT',
  entryPrice: number,
  entryTime: number
): { shouldExit: boolean, exitPrice: number, exitReason: string } {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const n = closes.length;

  const vwap = calcVWAP(candles);
  const ema9 = calcEMA(closes, 9);
  const ema20 = calcEMA(closes, 20);
  const atr = calcATR(highs, lows, closes, 14);

  const curVWAP = vwap;
  const curEMA9 = ema9[ema9.length - 1];
  const curEMA20 = ema20[ema20.length - 1];
  const curATR = atr[atr.length - 1];

  const stopMult = 1.2;
  const stop = positionDirection === 'LONG' ? entryPrice - stopMult * curATR : entryPrice + stopMult * curATR;
  const curClose = closes[n - 1];

  // Hard stop
  if (positionDirection === 'LONG' && curClose < stop) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'stop_loss' };
  }
  if (positionDirection === 'SHORT' && curClose > stop) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'stop_loss' };
  }

  // Structure break exit
  if (positionDirection === 'LONG' && (curClose < curVWAP || curEMA9 < curEMA20)) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'structure_break' };
  }
  if (positionDirection === 'SHORT' && (curClose > curVWAP || curEMA9 > curEMA20)) {
    return { shouldExit: true, exitPrice: curClose, exitReason: 'structure_break' };
  }

  return { shouldExit: false, exitPrice: curClose, exitReason: 'hold' };
}

// ─────────────────────────────────────────────
// FETCH CANDLES (Yahoo Finance - Free)
// ─────────────────────────────────────────────

interface Candle { time: number; open: number; high: number; low: number; close: number; volume?: number; }

async function fetchAlpacaSpotPrice(symbol: string, api_key: string, secret_key: string): Promise<number | null> {
  try {
    const res = await fetch(`https://data.alpaca.markets/v2/stocks/${symbol}/quotes/latest`, {
      headers: { 'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key }
    });
    const json = await res.json();
    const ask = json?.quote?.ap;
    const bid = json?.quote?.bp;
    if (ask > 0 && bid > 0) {
      const mid = (ask + bid) / 2;
      console.log(`[OptionsBot] Alpaca spot ${symbol} = $${mid.toFixed(2)} (bid=$${bid} ask=$${ask})`);
      return mid;
    }
  } catch (_) {}
  return null;
}

// Sanity check: spot price must be positive, within 50% of candle close, and within hard bounds for known symbols
// referencePrice=0 skips cross-check
function sanityCheckSpot(symbol: string, price: number, referencePrice = 0): boolean {
  if (!price || price <= 0) return false;
  
  // Hard bounds for major ETFs/stocks (catches stale data from months/years ago)
  const hardBounds: Record<string, { min: number; max: number }> = {
    'QQQ': { min: 350, max: 1000 },
    'SPY': { min: 400, max: 1000 },
    'AMD': { min: 50, max: 600 },
    'NVDA': { min: 80, max: 600 },
    'TSLA': { min: 150, max: 900 },
    'IWM': { min: 150, max: 350 },
    'DIA': { min: 300, max: 550 },
    'AAPL': { min: 150, max: 350 },
    'MSFT': { min: 300, max: 600 },
    'GOOG': { min: 130, max: 280 },
    'AMZN': { min: 150, max: 350 },
    'META': { min: 400, max: 800 },
    'NFLX': { min: 500, max: 1200 },
    'PLTR': { min: 15, max: 200 },
    'MSTR': { min: 200, max: 2000 },
    'COIN': { min: 100, max: 500 },
  };
  
  const bounds = hardBounds[symbol.toUpperCase()];
  if (bounds) {
    if (price < bounds.min || price > bounds.max) {
      console.log(`[OptionsBot] SANITY FAIL: ${symbol} price $${price.toFixed(2)} outside hard bounds $${bounds.min}-$${bounds.max} — stale data suspected, rejecting`);
      return false;
    }
  }
  
  if (referencePrice > 0) {
    const pct = Math.abs(price - referencePrice) / referencePrice;
    if (pct > 0.50) {
      console.log(`[OptionsBot] SANITY FAIL: ${symbol} spot $${price.toFixed(2)} is ${(pct*100).toFixed(1)}% away from candle close $${referencePrice.toFixed(2)} — rejecting`);
      return false;
    }
  }
  return true;
}

async function fetchTastytradeSpotPrice(symbol: string, accessToken: string): Promise<number | null> {
  try {
    // Tastytrade equity quotes endpoint
    const res = await fetch(`https://api.tastytrade.com/market-data/quotes?symbols[]=${encodeURIComponent(symbol)}`, {
      headers: { Authorization: `Bearer ${accessToken}` }
    });
    const json = await res.json();
    const quote = json?.data?.items?.[0];
    const mid = quote?.mid || ((Number(quote?.bid) + Number(quote?.ask)) / 2) || quote?.last;
    if (mid && mid > 0 && sanityCheckSpot(symbol, mid, 0)) { // reference=0: no candle available here, basic check only
      console.log(`[OptionsBot] Tastytrade real-time spot ${symbol} = $${mid} (bid=$${quote?.bid} ask=$${quote?.ask})`);
      return mid;
    }
    console.log(`[OptionsBot] Tastytrade spot bad/missing for ${symbol}: mid=${mid} raw=${JSON.stringify(quote)}`);
  } catch (err) {
    console.log(`[OptionsBot] Tastytrade spot fetch failed for ${symbol}:`, err);
  }
  return null;
}

async function fetchSpotPrice(symbol: string, alpacaApiKey?: string, alpacaSecretKey?: string): Promise<number | null> {
  // For paper trading: use real-time Alpaca data for accurate backtesting
  if (alpacaApiKey && alpacaSecretKey) {
    const p = await fetchAlpacaSpotPrice(symbol, alpacaApiKey, alpacaSecretKey);
    if (p) return p;
  }
  // Fallback: Yahoo real-time (better than delayed for paper testing)
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d`;
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' } });
    const json = await res.json();
    const meta = json?.chart?.result?.[0]?.meta;
    const p = meta?.regularMarketPrice ?? meta?.price;
    if (p && p > 0) { console.log(`[OptionsBot] Yahoo spot ${symbol} = $${p}`); return p; }
  } catch (_) {}
  return null;
}

async function fetchCandles(symbol: string, interval = '1h', bars = 150, alpacaApiKey?: string, alpacaSecretKey?: string): Promise<Candle[]> {
  const isCrypto  = symbol.includes('-USD') || symbol.includes('/USD');
  const isFutures = symbol.includes('=F');

  // ── ALPACA FIRST (stocks only, lower latency, no rate limits) ──
  if (!isCrypto && !isFutures) {
    try {
      if (alpacaApiKey && alpacaSecretKey) {
        const alpacaIntervalMap: Record<string, string> = {
          '1m': '1Min', '5m': '5Min', '15m': '15Min', '30m': '30Min',
          '1h': '1Hour', '4h': '4Hour', '1d': '1Day',
        };
        const timeframe = alpacaIntervalMap[interval] || '5Min';
        const limit = Math.min(bars + 10, 1000);
        const url = `https://data.alpaca.markets/v2/stocks/${encodeURIComponent(symbol)}/bars?timeframe=${timeframe}&limit=${limit}&adjustment=raw&feed=sip`;
        const res = await fetch(url, {
          headers: { 'APCA-API-KEY-ID': alpacaApiKey, 'APCA-API-SECRET-KEY': alpacaSecretKey }
        });
        if (res.ok) {
          const json = await res.json();
          const bars_data = json?.bars || [];
          if (bars_data.length >= 30) {
            const candles: Candle[] = bars_data.map((b: any) => ({
              time:   new Date(b.t).getTime(),
              open:   b.o, high: b.h, low: b.l, close: b.c, volume: b.v ?? 0
            }));
            console.log(`[OptionsBot] Alpaca candles ${symbol} (${interval}): ${candles.length} bars`);
            return candles.slice(-bars);
          }
        }
      }
    } catch (e) {
      console.warn(`[OptionsBot] Alpaca candle fetch failed for ${symbol}, falling back to Yahoo:`, e);
    }
  }

  // ── YAHOO FALLBACK (crypto, futures, or Alpaca failure) ──
  const intervalMap: Record<string, { yahooInterval: string; range: string }> = {
    '1m':  { yahooInterval: '1m',  range: '5d'  },
    '5m':  { yahooInterval: '5m',  range: '5d'  },
    '10m': { yahooInterval: '15m', range: '5d'  },
    '15m': { yahooInterval: '15m', range: '5d'  },
    '30m': { yahooInterval: '30m', range: '1mo' },
    '45m': { yahooInterval: '60m', range: '1mo' },
    '1h':  { yahooInterval: '60m', range: '1mo' },
    '2h':  { yahooInterval: '60m', range: '3mo' },
    '4h':  { yahooInterval: '60m', range: '6mo' },
    '1d':  { yahooInterval: '1d',  range: '1y'  },
  };
  const { yahooInterval, range } = intervalMap[interval] ?? intervalMap['1h'];
  const yahooSymbol = isCrypto ? symbol.replace('/', '-') : symbol;
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahooSymbol)}?interval=${yahooInterval}&range=${range}`;
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' } });
  if (!res.ok) throw new Error(`Yahoo API error: ${res.status}`);
  const json = await res.json();
  if (!json.chart?.result?.[0]) throw new Error(`No Yahoo data for ${symbol}`);
  const result = json.chart.result[0];
  const timestamps = result.timestamp || [];
  const quote = result.indicators?.quote?.[0] || {};
  const candles: Candle[] = [];
  for (let i = 0; i < timestamps.length; i++) {
    if (quote.open?.[i] && quote.high?.[i] && quote.low?.[i] && quote.close?.[i]) {
      candles.push({ time: timestamps[i] * 1000, open: quote.open[i], high: quote.high[i], low: quote.low[i], close: quote.close[i], volume: quote.volume?.[i] ?? 0 });
    }
  }
  if (candles.length < 30) throw new Error(`Not enough data for ${symbol} (got ${candles.length} candles)`);
  console.log(`[OptionsBot] Yahoo candles ${symbol} (${interval}): ${candles.length} bars`);
  return candles.slice(-bars);
}

// ─────────────────────────────────────────────
// SIGNAL GENERATION
// ─────────────────────────────────────────────

function generateSignal(candles: Candle[], settings: BotSettings): { signal: 'buy' | 'sell' | 'none', price: number, trend: number, ema: number, adx: number, reason: string } {
  const highs  = candles.map(c => c.high);
  const lows   = candles.map(c => c.low);
  const closes = candles.map(c => c.close);
  const n = closes.length;
  const tradeDirection = settings.tradeDirection || 'both';
  const emaArr = calcEMA(closes, settings.emaLength);
  const { trend } = calcSuperTrend(highs, lows, closes, settings.atrLength, settings.atrMultiplier);
  const { adx }   = calcDMI(highs, lows, closes, settings.adxLength);
  
  // Options bot: no position state replay needed - each contract is independent
  
  const i = n - 2;
  const curTrend = trend[i], prevTrend = trend[i - 1];
  const curEma = emaArr[i], curAdx = adx[i], curClose = closes[i];
  const trendJustFlipped = curTrend !== prevTrend;
  const longOK  = curTrend === 1;
  const shortOK = curTrend === -1;
  let signal: 'buy' | 'sell' | 'none' = 'none';
  let reason = `trend=${curTrend}, close=${curClose.toFixed(2)}, ema=${curEma.toFixed(2)}, adx=${curAdx?.toFixed(1)}`;
  // Only fire on a fresh trend flip (crossover) — never enter mid-trend
  if (longOK && trendJustFlipped) {
    signal = 'buy';
    reason = `TREND FLIP ENTER LONG. SuperTrend UP. ${reason}`;
  } else if (shortOK && trendJustFlipped && tradeDirection !== 'long') {
    signal = 'sell';
    reason = `TREND FLIP ENTER SHORT. SuperTrend DOWN. ${reason}`;
  }
  return { signal, price: curClose, trend: curTrend, ema: curEma, adx: curAdx, reason };
}

// ─────────────────────────────────────────────
// BLACK-SCHOLES OPTION PRICING
// ─────────────────────────────────────────────

function erf(x: number): number {
  const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  const t = 1 / (1 + p * x);
  const y = 1 - (((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);
  return sign * y;
}

function normCDF(x: number): number { return 0.5 * (1 + erf(x / Math.sqrt(2))); }

function blackScholes(S: number, K: number, T: number, r: number, sigma: number, type: 'call' | 'put'): number {
  if (T <= 0) return Math.max(0, type === 'call' ? S - K : K - S);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  if (type === 'call') return S * normCDF(d1) - K * Math.exp(-r * T) * normCDF(d2);
  return K * Math.exp(-r * T) * normCDF(-d2) - S * normCDF(-d1);
}

function calcHistoricalVolatility(closes: number[], period = 20, interval = '1d'): number {
  const returns: number[] = [];
  for (let i = 1; i < closes.length; i++) returns.push(Math.log(closes[i] / closes[i - 1]));
  const recent = returns.slice(-period);
  const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
  const variance = recent.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / recent.length;
  // Annualization factor: scale per-bar variance to annual
  const barsPerDay: Record<string, number> = { '1m': 390, '5m': 78, '10m': 39, '15m': 26, '30m': 13, '45m': 9, '1h': 7, '2h': 4, '4h': 2, '1d': 1 };
  const bpd = barsPerDay[interval] ?? 1;
  return Math.sqrt(variance * 252 * bpd);
}

// ─────────────────────────────────────────────
// OPTION PRICE: Alpaca OPRA → Black-Scholes
// ─────────────────────────────────────────────

async function fetchRealOptionPrice(symbol: string, strike: number, expiration: string, optionType: string, interval = '1h', userId?: string, expiryType = 'weekly', alpacaApiKey?: string, alpacaSecretKey?: string): Promise<number> {
  // 1. Try Alpaca options snapshot first (real-time OPRA data with Algo Trader Plus)
  if (alpacaApiKey && alpacaSecretKey) {
    try {
      // Alpaca OCC symbol format: SPY260529C00745000
      const exp = expiration.replace(/-/g, '').slice(2); // YYMMDD
      const strikeStr = String(Math.round(strike * 1000)).padStart(8, '0');
      const typeChar = optionType.toLowerCase() === 'call' ? 'C' : 'P';
      const alpacaSymbol = `${symbol}${exp}${typeChar}${strikeStr}`;
      // Try opra first (Algo Trader Plus), fall back to indicative (free)
      for (const feed of ['opra', 'indicative']) {
        const snapUrl = `https://data.alpaca.markets/v1beta1/options/snapshots?symbols=${encodeURIComponent(alpacaSymbol)}&feed=${feed}`;
        const snapRes = await fetch(snapUrl, {
          headers: { 'APCA-API-KEY-ID': alpacaApiKey, 'APCA-API-SECRET-KEY': alpacaSecretKey }
        });
        const snapJson = await snapRes.json();
        console.log(`[OptionsBot] Alpaca snapshot ${alpacaSymbol} feed=${feed}: status=${snapRes.status} raw=${JSON.stringify(snapJson).slice(0,200)}`);
        if (!snapRes.ok) continue; // try next feed
        const snap = snapJson?.snapshots?.[alpacaSymbol];
        const bid = snap?.latestQuote?.bp;
        const ask = snap?.latestQuote?.ap;
        if (bid > 0 && ask > 0) {
          // Buy at ask for realistic paper trading (matches live execution)
          console.log(`[OptionsBot] Alpaca ${feed} price ${alpacaSymbol}: $${ask.toFixed(4)} (BUYING AT ASK - bid=$${bid} ask=$${ask})`);
          return ask;
        }
        const lastTrade = snap?.latestTrade?.p;
        if (lastTrade > 0) {
          console.log(`[OptionsBot] Alpaca ${feed} last trade ${alpacaSymbol}: $${lastTrade}`);
          return lastTrade;
        }
      }
    } catch (err) {
      console.log('[OptionsBot] Alpaca options snapshot failed:', err);
    }
  }

  // 2. Try Tastytrade (token only — no option quotes via REST)
  if (userId) {
    try {
      const supabase = createClient(
        Deno.env.get('SUPABASE_URL')!,
        Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
      );
      
      const { data: creds } = await supabase.from('broker_credentials')
        .select('credentials')
        .eq('user_id', userId)
        .eq('broker', 'tastytrade')
        .maybeSingle();
      
      if (creds?.credentials?.refresh_token) {
        // Get fresh access token
        const tokenRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/tasty-oauth?action=refresh&user_id=${userId}`, {
          headers: { 'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`, 'apikey': Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '' }
        });
        const tokenJson = await tokenRes.json();
        
        if (tokenJson.access_token) {
          // Note: Tastytrade REST API does not provide option quotes (only DXLink streaming does)
          // We use Tastytrade only for: stock spot prices and order placement
          // Option pricing falls through to Black-Scholes below
          console.log(`[OptionsBot] Tastytrade token valid — using for spot price only (REST has no option quotes)`);
        }
      }
    } catch (err) {
      console.log('[OptionsBot] Tastytrade price fetch failed:', err);
    }
  }
  
  // Black-Scholes with realistic IV — calibrated by VIX + expiry type
  try {
    // Always fetch candles for historical vol calculation — pass Alpaca keys if available
    const candles = await fetchCandles(symbol, interval, 60, alpacaApiKey, alpacaSecretKey);
    if (!candles.length) return 0;

    // Use Alpaca live spot price if available (much more accurate than stale Yahoo candle close)
    let spotPrice = candles[candles.length - 1].close;
    if (alpacaApiKey && alpacaSecretKey) {
      try {
        const alpacaSpot = await fetchAlpacaSpotPrice(symbol, alpacaApiKey, alpacaSecretKey);
        if (alpacaSpot && alpacaSpot > 0) {
          console.log(`[OptionsBot] Using Alpaca live spot $${alpacaSpot.toFixed(2)} (Yahoo candle was $${spotPrice.toFixed(2)})`);
          spotPrice = alpacaSpot;
        }
      } catch (_) {}
    }

    // Base IV by symbol type — calibrated to real market observed IVs
    const etfs = ['SPY','QQQ','IWM','DIA','GLD','TLT','XLF','XLE','XLK','XLV','EEM','VXX'];
    const highVol = ['TSLA','NVDA','AMD','MSTR','COIN','PLTR','GME','AMC','RIVN','LCID'];
    let baseIv = etfs.includes(symbol) ? 0.18 : highVol.includes(symbol) ? 0.55 : 0.30;

    // VIX adjustment skipped (Polygon removed)

    // Blend with historical vol from candles (40% weight)
    const closes = candles.map((c: any) => c.close);
    const histVol = calcHistoricalVolatility(closes, 20, interval);
    if (histVol > 0.01 && histVol < 5) {
      baseIv = baseIv * 0.6 + histVol * 0.4;
    }

    // 0DTE IV boost: same-day expiry options carry higher IV due to gamma risk
    let iv = baseIv;
    if (expiryType === '0dte') {
      iv = baseIv * 1.5;  // 0DTE ~1.5x baseline IV (gamma risk)
    } else if (expiryType === '1dte') {
      iv = baseIv * 1.2;  // 1DTE elevated but less than same-day
    } else if (expiryType === 'weekly') {
      iv = baseIv * 1.05; // minimal premium for weekly
    }

    // Use 4PM ET (20:00 UTC) on expiry date as expiry time — not midnight
    const expParts = expiration.split('-');
    const expDate = new Date(Date.UTC(Number(expParts[0]), Number(expParts[1]) - 1, Number(expParts[2]), 20, 0, 0));
    const T = Math.max(1 / (365 * 24 * 60), (expDate.getTime() - Date.now()) / (365 * 24 * 60 * 60 * 1000));
    const price = blackScholes(spotPrice, strike, T, 0.05, iv, optionType as 'call' | 'put');
    console.log(`[OptionsBot] BS price for ${symbol} ${optionType} $${strike} (IV=${(iv*100).toFixed(0)}% histVol=${(histVol*100).toFixed(0)}% expiryType=${expiryType} T=${(T*365*24).toFixed(1)}h): $${price.toFixed(4)}`);
    return price;
  } catch (_) { return 0; }
}

function getExpirationDate(type: string): string {
  const now = new Date();
  if (type === '0dte') {
    // Find the closest future valid expiration day (today if available, otherwise next available day)
    const target = new Date(now.getTime());
    
    // Search up to 7 days forward for the next valid trading day
    for (let i = 0; i < 7; i++) {
      const candidate = new Date(target.getTime());
      candidate.setDate(candidate.getDate() + i);
      const day = candidate.getDay();
      
      // Skip weekends (0=Sunday, 6=Saturday)
      if (day === 0 || day === 6) continue;
      
      // Return first valid weekday (handles holidays via findValidExpiration later)
      return candidate.toISOString().split('T')[0];
    }
    
    // Fallback to today if no valid day found (shouldn't happen)
    return target.toISOString().split('T')[0];
  } else if (type === '1dte') {
    // Next trading day (skip weekends, assume no holiday check needed — findValidExpiration handles it)
    const target = new Date(now.getTime());
    for (let i = 1; i <= 7; i++) {
      const candidate = new Date(target.getTime());
      candidate.setDate(candidate.getDate() + i);
      const day = candidate.getDay();
      if (day !== 0 && day !== 6) return candidate.toISOString().split('T')[0];
    }
    return new Date(now.getTime() + 86400000).toISOString().split('T')[0];
  } else if (type === 'weekly') {
    // Always pick NEXT Friday for consistent 7+ day holds (minimum 7 days)
    const thisFriday = new Date(now.getTime());
    const daysToThisFriday = (5 - thisFriday.getDay() + 7) % 7;
    thisFriday.setDate(thisFriday.getDate() + daysToThisFriday);
    
    const nextFriday = new Date(thisFriday.getTime());
    nextFriday.setDate(nextFriday.getDate() + 7);
    
    // Always use next Friday (at least 7 days from today)
    return nextFriday.toISOString().split('T')[0];
  } else if (type === 'biweekly') {
    // Biweekly — closest Friday to 14 days from now (could be 13, 14, or 15 days out)
    const target = new Date(now.getTime());
    target.setDate(target.getDate() + 14);
    const dow = target.getDay();
    const fwdDays = (5 - dow + 7) % 7;           // days forward to reach Friday
    const bkDays = dow === 5 ? 0 : (dow - 5 + 7) % 7; // days back to reach Friday
    const closestFri = new Date(target.getTime());
    closestFri.setDate(target.getDate() + (fwdDays <= bkDays ? fwdDays : -bkDays));
    return closestFri.toISOString().split('T')[0];
  } else {
    // Monthly — third Friday closest to 30 days away
    // Find this month's and next month's third Friday
    const thisMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    let thisFridays = 0, thisThirdFriday: Date | null = null;
    for (let d = 1; d <= 31; d++) {
      const date = new Date(thisMonth.getFullYear(), thisMonth.getMonth(), d);
      if (date.getMonth() !== thisMonth.getMonth()) break;
      if (date.getDay() === 5) {
        thisFridays++;
        if (thisFridays === 3) { thisThirdFriday = date; break; }
      }
    }
    
    const nextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    let nextFridays = 0, nextThirdFriday: Date | null = null;
    for (let d = 1; d <= 31; d++) {
      const date = new Date(nextMonth.getFullYear(), nextMonth.getMonth(), d);
      if (date.getMonth() !== nextMonth.getMonth()) break;
      if (date.getDay() === 5) {
        nextFridays++;
        if (nextFridays === 3) { nextThirdFriday = date; break; }
      }
    }
    
    // Pick whichever third Friday is closest to 30 days from now
    const daysToThis = thisThirdFriday ? Math.ceil((thisThirdFriday.getTime() - now.getTime()) / (24 * 60 * 60 * 1000)) : Infinity;
    const daysToNext = nextThirdFriday ? Math.ceil((nextThirdFriday.getTime() - now.getTime()) / (24 * 60 * 60 * 1000)) : Infinity;
    
    const diffFrom30This = Math.abs(daysToThis - 30);
    const diffFrom30Next = Math.abs(daysToNext - 30);
    
    const target = diffFrom30This <= diffFrom30Next && daysToThis > 0 ? thisThirdFriday : nextThirdFriday;
    return target ? target.toISOString().split('T')[0] : (thisThirdFriday || nextThirdFriday || now).toISOString().split('T')[0];
  }
}

// Find nearest valid expiration: tries target, then -1 day, then +1 day, then -2 day, then +2 day
function findValidExpiration(targetDate: string): string {
  const target = new Date(targetDate);
  const candidates = [
    target,
    new Date(target.getTime() - 1 * 24 * 60 * 60 * 1000), // -1 day
    new Date(target.getTime() + 1 * 24 * 60 * 60 * 1000), // +1 day
    new Date(target.getTime() - 2 * 24 * 60 * 60 * 1000), // -2 days
    new Date(target.getTime() + 2 * 24 * 60 * 60 * 1000), // +2 days
  ];
  for (const d of candidates) {
    const day = d.getDay();
    if (day !== 0 && day !== 6) return d.toISOString().split('T')[0]; // Skip weekends
  }
  return targetDate; // Fallback to original
}

function pickStrike(spotPrice: number, otmStrikes: number, optionType: 'call' | 'put', strikeInterval = 5): number {
  // Round spot to nearest strike interval
  const atm = Math.round(spotPrice / strikeInterval) * strikeInterval;
  if (optionType === 'call') return atm + otmStrikes * strikeInterval;
  return atm - otmStrikes * strikeInterval;
}

// Smart strike selection: target ~0.30 delta for best risk/reward
function pickSmartStrike(
  spotPrice: number, optionType: 'call' | 'put', T: number, sigma: number,
  strikeInterval: number, budget: number, targetDelta = 0.30
): { strike: number; premium: number; delta: number } {
  const atm = Math.round(spotPrice / strikeInterval) * strikeInterval;
  const R = 0.05;
  
  // Scan strikes from 10 ITM to 10 OTM
  let bestStrike = atm;
  let bestPremium = blackScholes(spotPrice, atm, T, R, sigma, optionType);
  let bestDelta = 0.5; // ATM delta is ~0.5
  let bestDeltaDiff = Math.abs(0.5 - targetDelta);
  
  for (let offset = -10; offset <= 10; offset++) {
    const s = atm + offset * strikeInterval;
    if (s <= 0) continue;
    
    const p = blackScholes(spotPrice, s, T, R, sigma, optionType);
    if (p <= 0.01) continue;
    
    // Approximate delta using Black-Scholes
    const d1 = (Math.log(spotPrice / s) + (R + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
    let delta: number;
    if (optionType === 'call') {
      delta = normCDF(d1);
    } else {
      delta = Math.abs(normCDF(d1) - 1); // Put delta as positive number
    }
    
    const deltaDiff = Math.abs(delta - targetDelta);
    const affordable = p * 100 <= budget;
    
    // Pick strike closest to target delta that's within budget
    if (affordable && deltaDiff < bestDeltaDiff) {
      bestStrike = s;
      bestPremium = p;
      bestDelta = delta;
      bestDeltaDiff = deltaDiff;
    }
  }
  
  return { strike: bestStrike, premium: bestPremium, delta: bestDelta };
}

// ─────────────────────────────────────────────
// SETTINGS INTERFACE
// ─────────────────────────────────────────────

interface BotSettings {
  atrLength: number; atrMultiplier: number; emaLength: number;
  adxLength: number; adxThreshold: number; symbol: string;
  dollarAmount: number; interval: string; tradeDirection: string;
  expiryType: string; otmStrikes: number;
  strikeMode: string; manualStrike: number | null;
  takeProfitPct: number; stopLossPct: number;
  symbolRules: Array<{symbol:string;tp:number;sl:number;dir?:string}>;
  marketOpenDelayMin: number;
  botSignal: string;
  signalInterval: string;
  entryInterval: string;
}

// ─────────────────────────────────────────────
// ALPACA OPTIONS TRADING
// ─────────────────────────────────────────────

// Format option symbol for Alpaca: SPY240531C00580000
function formatOptionSymbol(symbol: string, expirationDate: string, optionType: 'call' | 'put', strike: number): string {
  const date = new Date(expirationDate);
  const year = date.getFullYear().toString().slice(2); // 24
  const month = (date.getMonth() + 1).toString().padStart(2, '0'); // 06
  const day = date.getDate().toString().padStart(2, '0'); // 15
  const type = optionType === 'call' ? 'C' : 'P';
  const strikeStr = Math.round(strike * 1000).toString().padStart(8, '0'); // 00580000
  return `${symbol.toUpperCase()}${year}${month}${day}${type}${strikeStr}`;
}

// Place options order via Tastytrade
async function placeTastytradeOptionOrder(
  supabase: any,
  userId: string,
  symbol: string,
  expirationDate: string,
  optionType: 'call' | 'put',
  strike: number,
  side: 'Buy to Open' | 'Sell to Close',
  qty: number
): Promise<{ success: boolean; orderId?: string; error?: string; status?: string; fillPrice?: number }> {
  try {
    const { data: creds } = await supabase.from('broker_credentials')
      .select('credentials')
      .eq('user_id', userId)
      .eq('broker', 'tastytrade')
      .maybeSingle();

    if (!creds?.credentials?.refresh_token) {
      return { success: false, error: 'No Tastytrade credentials found' };
    }

    // Get fresh access token
    const tokenRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/tasty-oauth?action=refresh&user_id=${userId}`, {
      headers: { 'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`, 'apikey': Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '' }
    });
    const tokenJson = await tokenRes.json();
    if (!tokenJson.access_token) return { success: false, error: 'Failed to get access token' };

    const accessToken = tokenJson.access_token;
    const accountNumber = creds.credentials.account_number;
    if (!accountNumber) return { success: false, error: 'No account number found' };

    // Format Tastytrade OCC option symbol: SPY 260523C00590000
    const expParts = expirationDate.split('-');
    const yy = expParts[0].slice(2);
    const mm = expParts[1];
    const dd = expParts[2];
    const typeChar = optionType === 'call' ? 'C' : 'P';
    const strikeStr = String(Math.round(strike * 1000)).padStart(8, '0');
    const occSymbol = `${symbol}  ${yy}${mm}${dd}${typeChar}${strikeStr}`;

    const orderBody = {
      'order-type': 'Market',
      'time-in-force': 'Day',
      legs: [{
        'instrument-type': 'Equity Option',
        symbol: occSymbol,
        quantity: qty,
        action: side,
      }]
    };

    console.log(`[TastyOptions] Placing order: ${side} ${qty}x ${occSymbol} on account ${accountNumber}`);

    const res = await fetch(`https://api.tastytrade.com/accounts/${accountNumber}/orders`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(orderBody),
    });

    const orderJson = await res.json();

    if (!res.ok) {
      const errMsg = orderJson?.error?.message || orderJson?.errors?.[0]?.message || JSON.stringify(orderJson);
      console.error('[TastyOptions] Order failed:', errMsg);
      return { success: false, error: errMsg, status: 'failed' };
    }

    const order = orderJson?.data?.order;
    const orderId = order?.id ? String(order.id) : null;
    const orderStatus = order?.status || 'received';
    console.log(`[TastyOptions] Order placed: id=${orderId} status=${orderStatus}`);

    // Poll up to 10s for fill price
    let fillPrice: number | undefined;
    if (orderId) {
      for (let i = 0; i < 5; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const pollRes = await fetch(`https://api.tastytrade.com/accounts/${accountNumber}/orders/${orderId}`, {
          headers: { 'Authorization': `Bearer ${accessToken}` }
        });
        const polled = await pollRes.json();
        const filledOrder = polled?.data;
        const legs = filledOrder?.legs || [];
        const avgFill = legs[0]?.['average-fill-price'] || filledOrder?.['average-fill-price'];
        console.log(`[TastyOptions] Poll ${i+1}: status=${filledOrder?.status} avg_fill=$${avgFill}`);
        if (avgFill) { fillPrice = Number(avgFill); break; }
        if (filledOrder?.status === 'Filled') { fillPrice = Number(avgFill); break; }
      }
    }

    return { success: true, orderId: orderId || undefined, status: orderStatus, fillPrice };
  } catch (err) {
    console.error('[TastyOptions] Error:', err);
    return { success: false, error: String(err), status: 'error' };
  }
}

// Place options order via Alpaca
async function placeAlpacaOptionOrder(
  supabase: any,
  userId: string,
  symbol: string,
  expirationDate: string,
  optionType: 'call' | 'put',
  strike: number,
  side: 'buy' | 'sell',
  qty: number,
  forcePaper = false,
  midPrice?: number
): Promise<{ success: boolean; orderId?: string; error?: string; status?: string; fillPrice?: number }> {
  try {
    // Fetch Alpaca credentials
    const { data: creds } = await supabase
      .from('broker_credentials')
      .select('credentials')
      .eq('user_id', userId)
      .eq('broker', 'alpaca')
      .maybeSingle();

    if (!creds) {
      return { success: false, error: 'No Alpaca credentials found' };
    }

    const { api_key, secret_key, env } = creds.credentials;
    const baseUrl = (!forcePaper && env === 'live')
      ? 'https://api.alpaca.markets'
      : 'https://paper-api.alpaca.markets';

    const optionSymbol = formatOptionSymbol(symbol, expirationDate, optionType, strike);

    const BUFFER = 0.02;
    const limitPrice = midPrice && midPrice > 0
      ? (side === 'buy' ? Math.round((midPrice + BUFFER) * 100) / 100 : Math.round((midPrice - BUFFER) * 100) / 100)
      : null;

    const orderBody: any = {
      symbol: optionSymbol,
      side,
      type: limitPrice ? 'limit' : 'market',
      time_in_force: 'day',
      qty: String(qty),
      ...(limitPrice ? { limit_price: String(limitPrice.toFixed(2)) } : {}),
    };

    console.log(`[AlpacaOptions] Placing order: ${side} ${qty} x ${optionSymbol} type=${orderBody.type} limit=${limitPrice ?? 'n/a'}`);

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
      console.error('[AlpacaOptions] Order failed:', order.message || order);
      return { success: false, error: order.message || 'Alpaca order failed', status: 'failed' };
    }

    console.log(`[AlpacaOptions] Order placed: ${order.id} status=${order.status} filled_avg_price=${order.filled_avg_price}`);

    let fillPrice: number | undefined = order.filled_avg_price ? Number(order.filled_avg_price) : undefined;
    let finalOrderId: string = order.id;
    let finalStatus: string = order.status;

    if (!fillPrice && order.status !== 'filled') {
      // Poll for 5s to see if limit fills
      await new Promise(r => setTimeout(r, 5000));
      const pollRes = await fetch(`${baseUrl}/v2/orders/${order.id}`, {
        headers: { 'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key }
      });
      const polled = await pollRes.json();
      console.log(`[AlpacaOptions] After 5s: status=${polled.status} filled_avg_price=${polled.filled_avg_price}`);

      if (polled.filled_avg_price) {
        fillPrice = Number(polled.filled_avg_price);
        finalStatus = polled.status;
      } else if (polled.status !== 'filled') {
        // Limit didn't fill — cancel and resubmit as market
        console.log(`[AlpacaOptions] Limit unfilled, cancelling ${order.id} and resubmitting as market`);
        await fetch(`${baseUrl}/v2/orders/${order.id}`, {
          method: 'DELETE',
          headers: { 'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key }
        });
        const mktRes = await fetch(`${baseUrl}/v2/orders`, {
          method: 'POST',
          headers: { 'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key, 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: optionSymbol, side, type: 'market', time_in_force: 'day', qty: String(qty) }),
        });
        const mktOrder = await mktRes.json();
        if (mktRes.ok) {
          finalOrderId = mktOrder.id;
          finalStatus = mktOrder.status;
          fillPrice = mktOrder.filled_avg_price ? Number(mktOrder.filled_avg_price) : undefined;
          console.log(`[AlpacaOptions] Market fallback placed: ${mktOrder.id} status=${mktOrder.status}`);
          // Brief poll for market fill price
          if (!fillPrice) {
            await new Promise(r => setTimeout(r, 2000));
            const mktPoll = await fetch(`${baseUrl}/v2/orders/${mktOrder.id}`, {
              headers: { 'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key }
            });
            const mktPolled = await mktPoll.json();
            if (mktPolled.filled_avg_price) fillPrice = Number(mktPolled.filled_avg_price);
          }
        } else {
          console.error('[AlpacaOptions] Market fallback failed:', mktOrder.message || mktOrder);
        }
      }
    }

    return { success: true, orderId: finalOrderId, status: finalStatus, fillPrice };

  } catch (err) {
    console.error('[AlpacaOptions] Error:', err);
    return { success: false, error: String(err), status: 'error' };
  }
}

// ─────────────────────────────────────────────
// MAIN HANDLER
// ─────────────────────────────────────────────

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  );

  // GET /portfolio-value?bot_id=xxx — returns cash + live value of open positions
  if (req.method === 'GET') {
    const url = new URL(req.url);
    const botId = url.searchParams.get('bot_id');
    if (!botId) return new Response(JSON.stringify({ error: 'bot_id required' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

    const { data: bot } = await supabase.from('options_bots').select('paper_balance, bot_interval').eq('id', botId).single();
    const cash = Number(bot?.paper_balance ?? 100000);
    const interval = bot?.bot_interval ?? '1h';

    const { data: openTrades } = await supabase.from('options_trades').select('*').eq('bot_id', botId).eq('status', 'open');
    let openValue = 0;
    const R = 0.05;
    if (openTrades && openTrades.length > 0) {
      for (const t of openTrades) {
        try {
          const candles = await fetchCandles(t.symbol, interval, 60);
          if (!candles.length) { openValue += Number(t.total_cost); continue; }
          const price = candles[candles.length - 1].close;
          const sigma = calcHistoricalVolatility(candles.map(c => c.close), 20, interval);
          const expDate = new Date(t.expiration_date);
          const T = Math.max(0, (expDate.getTime() - Date.now()) / (365 * 24 * 60 * 60 * 1000));
          const currentPremium = blackScholes(price, t.strike, T, R, sigma, t.option_type);
          openValue += currentPremium * t.contracts * 100;
        } catch (_) { openValue += Number(t.total_cost); }
      }
    }

    return new Response(JSON.stringify({ cash, open_value: openValue, total: cash + openValue }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }

  // Parse body once for all POST handlers
  let _parsedBody: any = null;
  if (req.method === 'POST') {
    _parsedBody = await req.json().catch(() => ({}));
  }

  // ── INSTANT ACTIONS (POST with action field) ──
  if (req.method === 'POST') {
    const body = _parsedBody;
    const action = body.action;

    // Fetch current option price for frontend P&L display
    if (action === 'get_option_price') {
      const { symbol, strike, expiration, option_type, user_id } = body;
      if (!symbol || !strike || !expiration || !option_type) return new Response(JSON.stringify({ price: null }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
      let alpacaKey, alpacaSecret;
      if (user_id) {
        const { data: ac } = await supabase.from('broker_credentials').select('credentials').eq('user_id', user_id).eq('broker', 'alpaca').maybeSingle();
        alpacaKey = ac?.credentials?.api_key;
        alpacaSecret = ac?.credentials?.secret_key;
      }
      // Auto-detect expiryType from expiration date
      const todayStr = new Date().toISOString().slice(0, 10);
      const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
      const detectedExpiryType = expiration === todayStr ? '0dte' : expiration === tomorrowStr ? '1dte' : 'weekly';
      let price = await fetchRealOptionPrice(symbol, Number(strike), expiration, option_type, '1h', user_id, detectedExpiryType, alpacaKey, alpacaSecret);
      console.log(`[get_option_price] ${symbol} ${option_type} $${strike} exp=${expiration} type=${detectedExpiryType} alpacaKey=${!!alpacaKey} => price=${price}`);
      return new Response(JSON.stringify({ price: price > 0 ? price : null }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Get daily bot stats for historical analysis
    if (action === 'get_daily_stats') {
      const { bot_id, days = 30 } = body;
      if (!bot_id) return new Response(JSON.stringify({ error: 'bot_id required' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

      const { data: stats } = await supabase.from('daily_bot_stats')
        .select('*')
        .eq('bot_id', bot_id)
        .order('date', { ascending: false })
        .limit(days);

      return new Response(JSON.stringify({ stats }), { headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Instant TP/SL check: called immediately when user saves new thresholds
    if (action === 'check_tpsl') {
      const botId = body.bot_id;
      if (!botId) return new Response(JSON.stringify({ error: 'bot_id required' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

      const { data: bot } = await supabase.from('options_bots').select('*').eq('id', botId).single();
      if (!bot) return new Response(JSON.stringify({ error: 'Bot not found' }), { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

      const takeProfitPct = Number(body.take_profit_pct ?? bot.take_profit_pct ?? 100);
      const stopLossPct   = Number(body.stop_loss_pct  ?? bot.stop_loss_pct  ?? 20);
      const interval      = bot.bot_interval ?? '1h';
      const R = 0.05;
      const closed: object[] = [];

      const { data: openTrades } = await supabase.from('options_trades').select('*').eq('bot_id', botId).eq('status', 'open');
      for (const open of (openTrades || [])) {
        try {
          const { data: alpacaCredsForTpsl } = await supabase.from('broker_credentials').select('credentials').eq('user_id', bot.user_id).eq('broker', 'alpaca').maybeSingle();
          const tpslExpiryType = bot.bot_expiry_type ?? 'weekly';
          let optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, interval, bot.user_id, tpslExpiryType, alpacaCredsForTpsl?.credentials?.api_key, alpacaCredsForTpsl?.credentials?.secret_key);
          if (!optionPrice || optionPrice <= 0) {
            console.log(`[check_tpsl] SKIP: no real price for ${open.symbol} $${open.strike}`);
            continue;
          }
          const totalCost = Number(open.total_cost) || (Number(open.premium_per_contract) * open.contracts * 100);
          const currentValue = optionPrice * open.contracts * 100;
          const pnl = currentValue - totalCost;
          const pctChange = (pnl / totalCost) * 100;
          const slThreshold = stopLossPct < 0 ? stopLossPct : -Math.abs(stopLossPct);
          const shouldTP = pctChange >= takeProfitPct;
          const shouldSL = pctChange <= slThreshold;
          if (shouldTP || shouldSL) {
            const isPaper = bot.broker === 'paper';
            const exactPnl = isPaper ? Math.round(totalCost * (shouldTP ? takeProfitPct : slThreshold) / 100 * 100) / 100 : pnl;
            await supabase.from('options_trades').update({ status: 'closed', exit_price: optionPrice, pnl: exactPnl, closed_at: new Date().toISOString(), exit_type: shouldTP ? 'tp' : 'sl' }).eq('id', open.id);
            if (isPaper) {
              const { data: bRow } = await supabase.from('options_bots').select('paper_balance').eq('id', botId).single();
              const bal = Number(bRow?.paper_balance ?? 100000);
              await supabase.from('options_bots').update({ paper_balance: bal + totalCost + exactPnl }).eq('id', botId);
            }
            closed.push({ id: open.id, symbol: open.symbol, pct_change: (exactPnl/totalCost*100).toFixed(1) + '%', pnl: exactPnl.toFixed(2), reason: shouldTP ? 'take_profit' : 'stop_loss' });
          }
        } catch (_) {}
      }
      return new Response(JSON.stringify({ checked: (openTrades || []).length, closed }), { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Fast TP/SL Daemon: checks ALL open positions every 30 seconds for instant exit
    if (action === 'tpsl_daemon') {
      const now = new Date();
      
      // Get all open trades with their bot settings
      const { data: openTrades } = await supabase.from('options_trades')
        .select('*, take_profit_pct, stop_loss_pct, options_bots!inner(take_profit_pct, stop_loss_pct, symbol_rules, bot_interval, broker, user_id, name, bot_expiry_type, bot_signal)')
        .eq('status', 'open');
      
      if (!openTrades || openTrades.length === 0) {
        return new Response(JSON.stringify({ checked: 0, closed: [], message: 'No open positions' }), { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
      }
      
      console.log(`[TPSL_Daemon] Checking ${openTrades.length} open positions for TP/SL...`);
      const closed: object[] = [];
      const R = 0.05;
      // Cache Alpaca creds per user to avoid repeated DB queries
      const alpacaCredsCache: Record<string, { api_key?: string; secret_key?: string }> = {};

      for (const open of openTrades) {
        try {
          const bot = (open as any).options_bots;
          const botSignal = bot?.bot_signal || 'supertrend';
          const symRulesDaemon: Array<{symbol:string;tp:number;sl:number}> = (bot?.symbol_rules as any) || [];
          const symRuleDaemon = symRulesDaemon.find((r:any) => r.symbol?.toUpperCase() === (open as any).symbol?.toUpperCase());
          // For boof22: use per-trade ATR-computed TP/SL stored at entry; others use bot/symbol-rule settings
          const tradeHasAtrTpSl = botSignal === 'boof22' && (open as any).take_profit_pct != null && (open as any).stop_loss_pct != null;
          const takeProfitPct  = tradeHasAtrTpSl ? Number((open as any).take_profit_pct) : symRuleDaemon ? Number(symRuleDaemon.tp) : Number(bot?.take_profit_pct ?? 35);
          const stopLossPct    = tradeHasAtrTpSl ? Number((open as any).stop_loss_pct)   : symRuleDaemon ? Number(symRuleDaemon.sl) : Number(bot?.stop_loss_pct ?? -25);
          const interval = bot?.bot_interval ?? '1h';
          const userId = bot?.user_id;
          
          // Fetch Alpaca creds once per user (cached)
          if (userId && !alpacaCredsCache[userId]) {
            const { data: alpacaCredsRow } = await supabase.from('broker_credentials').select('credentials').eq('user_id', userId).eq('broker', 'alpaca').maybeSingle();
            alpacaCredsCache[userId] = alpacaCredsRow?.credentials ?? {};
          }
          const alpacaApiKey = alpacaCredsCache[userId]?.api_key;
          const alpacaSecretKey = alpacaCredsCache[userId]?.secret_key;
          const botExpiryType = bot?.bot_expiry_type ?? 'weekly';
          
          // Boof 15.0: Use exit signals instead of TP/SL
          if (botSignal === 'boof15') {
            const candles15 = await fetchCandles(open.symbol, interval, 100, alpacaApiKey, alpacaSecretKey);
            if (candles15.length < 50) {
              console.log(`[TPSL_Daemon] SKIP: not enough candles for Boof 15.0 exit check on ${open.symbol}`);
              continue;
            }
            
            const positionDirection = (open as any).signal === 'buy' ? 'LONG' : 'SHORT';
            const entryPrice = Number(open.entry_price);
            const entryTime = new Date((open as any).created_at).getTime();
            
            const exitResult = generateExitSignals15(candles15, positionDirection, entryPrice, entryTime);
            
            if (exitResult.shouldExit) {
              const optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, interval, userId, botExpiryType, alpacaApiKey, alpacaSecretKey);
              if (!optionPrice || optionPrice <= 0) {
                console.log(`[TPSL_Daemon] SKIP: no real price for ${open.symbol} $${open.strike}`);
                continue;
              }
              
              const totalCost = Number(open.total_cost) || (Number(open.premium_per_contract) * open.contracts * 100);
              const pnl = optionPrice * open.contracts * 100 - totalCost;
              
              await supabase.from('options_trades').update({ 
                status: 'closed', 
                exit_price: optionPrice, 
                pnl, 
                closed_at: now.toISOString(),
                exit_reason: exitResult.exitReason
              }).eq('id', open.id);
              
              if (bot?.broker === 'paper') {
                const { data: bRow } = await supabase.from('options_bots').select('paper_balance').eq('id', open.bot_id).single();
                const bal = Number(bRow?.paper_balance ?? 100000);
                await supabase.from('options_bots').update({ paper_balance: bal + totalCost + pnl }).eq('id', open.bot_id);
              }
              
              closed.push({ 
                id: open.id, 
                bot_name: bot?.name || 'Unknown',
                symbol: open.symbol, 
                strike: open.strike,
                pct_change: ((pnl / totalCost) * 100).toFixed(1) + '%', 
                pnl: pnl.toFixed(2), 
                reason: exitResult.exitReason,
                source: 'boof15_exit'
              });
              console.log(`[TPSL_Daemon] Boof 15.0 closed ${open.symbol}: ${exitResult.exitReason}`);
              continue;
            }
          }
          
          // Standard TP/SL for other strategies
          // Fetch real-time price — Alpaca OPRA → Black-Scholes
          const optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, interval, userId, botExpiryType, alpacaApiKey, alpacaSecretKey);
          const source = optionPrice > 0 ? 'alpaca/bs' : 'none';
          
          if (!optionPrice || optionPrice <= 0) {
            console.log(`[TPSL_Daemon] SKIP: no real price for ${open.symbol} $${open.strike}`);
            continue;
          }

          const totalCost = Number(open.total_cost) || (Number(open.premium_per_contract) * open.contracts * 100);
          const currentValue = optionPrice * open.contracts * 100;
          const pnl = currentValue - totalCost;
          const pctChange = (pnl / totalCost) * 100;
          
          // 1DTE special handling: 30-min time exit, but use bot's TP/SL settings
          const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
          const todayStr = new Date().toISOString().slice(0, 10);
          const expDateStr = open.expiration_date?.slice(0, 10) || open.expiration_date;
          const is1dte = botExpiryType === '1dte' || expDateStr === tomorrowStr;
          const is0dte = botExpiryType === '0dte' || expDateStr === todayStr;
          
          console.log(`[TPSL_Daemon] DATE_CHECK: expDate=${expDateStr} tomorrow=${tomorrowStr} today=${todayStr} is1dte=${is1dte} is0dte=${is0dte} botExpiry=${botExpiryType}`);
          
          const slThreshold = stopLossPct < 0 ? stopLossPct : -Math.abs(stopLossPct);
          const shouldTP = pctChange >= takeProfitPct;
          const shouldSL = pctChange <= slThreshold;
          const isPaperTrade = bot?.broker === 'paper';

          // 1DTE 30-minute time exit: if neither TP nor SL hit after 30 mins, exit at market
          const entryTime = new Date(open.created_at || open.filled_at || now);
          const minutesHeld = (now.getTime() - entryTime.getTime()) / (1000 * 60);
          const shouldTimeExit1DTE = is1dte && minutesHeld >= 30 && !shouldTP && !shouldSL;
          
          // 0DTE 20-minute time exit: close if held longer than 20 minutes
          const shouldTimeExit0DTE = is0dte && minutesHeld >= 20 && !shouldTP && !shouldSL;

          // EOD auto-close: force-close all 0DTE positions at 12:00 PM MST (18:00 UTC)
          // 1DTE positions close 1 minute before market close (3:59 PM ET = 19:59 UTC)
          const utcHour = now.getUTCHours();
          const utcMinute = now.getUTCMinutes();
          const shouldEOD_0dte = is0dte && (utcHour > 18 || (utcHour === 18 && utcMinute >= 0));
          const shouldEOD_1dte = is1dte && (utcHour === 19 && utcMinute >= 59);
          const shouldEOD = shouldEOD_0dte || shouldEOD_1dte || shouldTimeExit1DTE || shouldTimeExit0DTE;
          
          console.log(`[TPSL_Daemon] ${open.symbol} ${open.option_type} $${open.strike}: current=$${optionPrice.toFixed(2)} entry=$${Number(open.premium_per_contract).toFixed(2)} pct=${pctChange.toFixed(1)}% tp=${takeProfitPct}% sl=${slThreshold}% minsHeld=${minutesHeld.toFixed(1)} shouldTP=${shouldTP} shouldSL=${shouldSL} timeExit0DTE=${shouldTimeExit0DTE} timeExit1DTE=${shouldTimeExit1DTE} shouldEOD=${shouldEOD} source=${source}`);
          
          if (shouldTP || shouldSL || shouldEOD) {
            const exitReason = shouldEOD ? 'eod_close_noon_mst' : shouldTP ? 'take_profit' : 'stop_loss';
            const exactPnl = isPaperTrade && !shouldEOD ? Math.round(totalCost * (shouldTP ? takeProfitPct : slThreshold) / 100 * 100) / 100 : pnl;
            const exitType = shouldTP ? 'tp' : shouldSL ? 'sl' : (shouldTimeExit1DTE || shouldTimeExit0DTE) ? 'time_exit' : 'eod';
            
            console.log(`[TPSL_Daemon] ✓ CLOSING ${open.symbol} ${open.option_type} $${open.strike}: reason=${exitReason} exitType=${exitType} pnl=$${exactPnl.toFixed(2)}`);
            
            try {
              // Minimal update first - just status and pnl
              const { error: err1 } = await supabase.from('options_trades').update({ 
                status: 'closed', 
                pnl: exactPnl
              }).eq('id', open.id);
              
              if (err1) {
                console.log(`[TPSL_Daemon] ✗ Failed step 1 for ${open.symbol}: ${err1.message} (code: ${err1.code})`);
                continue;
              }
              
              // Step 2 - add exit details
              const { error: err2 } = await supabase.from('options_trades').update({ 
                exit_price: optionPrice, 
                closed_at: now.toISOString(),
                exit_reason: exitReason,
                exit_type: exitType
              }).eq('id', open.id);
              
              if (err2) {
                console.log(`[TPSL_Daemon] ✗ Failed step 2 for ${open.symbol}: ${err2.message} (code: ${err2.code})`);
                // Still count as closed since status changed
              }
              
              console.log(`[TPSL_Daemon] ✓ Successfully closed ${open.symbol} ${open.id}`);
            } catch (err) {
              console.log(`[TPSL_Daemon] ✗ Exception closing ${open.symbol}: ${err}`);
              continue;
            }
            
            // Update paper balance if paper trading
            if (isPaperTrade) {
              const { data: bRow } = await supabase.from('options_bots').select('paper_balance').eq('id', open.bot_id).single();
              const bal = Number(bRow?.paper_balance ?? 100000);
              await supabase.from('options_bots').update({ paper_balance: bal + totalCost + exactPnl }).eq('id', open.bot_id);
            }

            // Consecutive loss tracking
            const isLoss = exactPnl < 0;
            const { data: botRow } = await supabase.from('options_bots').select('consecutive_losses, max_consecutive_losses, cooldown_minutes, name, bot_symbol, bot_signal').eq('id', open.bot_id).single();
            const currentLosses = (botRow?.consecutive_losses as number) ?? 0;
            const maxLosses = (botRow?.max_consecutive_losses as number) ?? 8;
            const cooldownMins = (botRow?.cooldown_minutes as number) ?? 10;

            if (isLoss) {
              const newLosses = currentLosses + 1;
              const updates: any = { consecutive_losses: newLosses };
              if (newLosses >= maxLosses) {
                const cooldownUntil = new Date(now.getTime() + cooldownMins * 60000);
                updates.cooldown_until = cooldownUntil.toISOString();
                console.log(`[TPSL_Daemon] 🛑 Cooldown triggered for bot ${open.bot_id}: ${newLosses} consecutive losses, pausing for ${cooldownMins} minutes until ${cooldownUntil.toISOString()}`);
              }
              await supabase.from('options_bots').update(updates).eq('id', open.bot_id);
            } else {
              // Reset consecutive losses on win
              await supabase.from('options_bots').update({ consecutive_losses: 0, cooldown_until: null }).eq('id', open.bot_id);
            }

            // Record daily stats
            await recordDailyStats(open.bot_id, botRow?.name || 'Unknown', botRow?.bot_symbol || 'Unknown', botRow?.bot_signal || 'Unknown');

            // Recalculate and store bot stats after trade closes
            await recalculateBotStats(open.bot_id, alpacaApiKey, alpacaSecretKey);
            
            closed.push({ 
              id: open.id, 
              bot_name: bot?.name || 'Unknown',
              symbol: open.symbol, 
              strike: open.strike,
              pct_change: (exactPnl/totalCost*100).toFixed(1) + '%', 
              pnl: exactPnl.toFixed(2), 
              reason: exitReason,
              source
            });
          }
        } catch (err) {
          console.log(`[TPSL_Daemon] Error checking trade ${open.id}:`, err);
        }
      }
      
      console.log(`[TPSL_Daemon] Closed ${closed.length} positions`);
      return new Response(JSON.stringify({ checked: openTrades.length, closed }), { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

    // Helper: Recalculate and update all bot stats aggregates
    async function recalculateBotStats(botId: string, alpacaApiKey?: string, alpacaSecretKey?: string) {
      const { data: allTrades } = await supabase.from('options_trades').select('*').eq('bot_id', botId);
      const closedTrades = (allTrades || []).filter(t => t.status === 'closed');
      const openTrades = (allTrades || []).filter(t => t.status === 'open');

      // Fetch live prices for open trades and update current_price
      for (const trade of openTrades) {
        if (alpacaApiKey && alpacaSecretKey) {
          try {
            const price = await fetchRealOptionPrice(
              trade.symbol,
              Number(trade.strike),
              trade.expiration_date,
              trade.option_type,
              '1h',
              undefined,
              trade.expiry_type || 'weekly',
              alpacaApiKey,
              alpacaSecretKey
            );
            if (price > 0) {
              trade.current_price = price;
              // Update the trade in DB with new current price
              await supabase.from('options_trades')
                .update({ current_price: price, updated_at: new Date().toISOString() })
                .eq('id', trade.id);
            }
          } catch (e) {
            console.log(`[recalculateBotStats] Failed to fetch price for ${trade.symbol} ${trade.strike}: ${e}`);
          }
        }
      }

      const realizedPnl = closedTrades.reduce((sum, t) => sum + (Number(t.pnl) || 0), 0);
      const unrealizedPnl = openTrades.reduce((sum, t) => {
        if (!t.current_price || t.current_price <= 0) return sum;
        const entry = Number(t.premium_per_contract) || 0;
        const contracts = Number(t.contracts) || 1;
        return sum + ((t.current_price - entry) * contracts * 100);
      }, 0);

      const wins = closedTrades.filter(t => (Number(t.pnl) || 0) > 0).length;
      const losses = closedTrades.filter(t => (Number(t.pnl) || 0) <= 0).length;
      const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : 0;

      // Calculate peak/trough
      const sorted = closedTrades.slice().sort((a, b) => (a.closed_at || '').localeCompare(b.closed_at || ''));
      let running = 0, peak = 0, trough = 0;
      sorted.forEach(t => { running += (Number(t.pnl) || 0); if (running > peak) peak = running; if (running < trough) trough = running; });

      await supabase.from('options_bots').update({
        stats_realized_pnl: realizedPnl,
        stats_unrealized_pnl: unrealizedPnl,
        stats_total_pnl: realizedPnl + unrealizedPnl,
        stats_peak_pnl: peak,
        stats_trough_pnl: trough,
        stats_total_trades: closedTrades.length,
        stats_wins: wins,
        stats_losses: losses,
        stats_win_rate: winRate.toFixed(2),
        stats_open_count: openTrades.length,
        stats_updated_at: new Date().toISOString()
      }).eq('id', botId);
    }

    async function recordDailyStats(botId: string, botName: string, botSymbol: string, botSignal: string) {
      const today = new Date().toISOString().split('T')[0];
      const { data: bot } = await supabase.from('options_bots').select('*').eq('id', botId).single();
      if (!bot) return;

      // Get today's trades
      const { data: todayTrades } = await supabase.from('options_trades')
        .select('*')
        .eq('bot_id', botId)
        .gte('created_at', `${today}T00:00:00Z`)
        .lte('created_at', `${today}T23:59:59Z`);

      const closedToday = (todayTrades || []).filter(t => t.status === 'closed');
      const totalTrades = closedToday.length;
      const winningTrades = closedToday.filter(t => (Number(t.pnl) || 0) > 0).length;
      const losingTrades = closedToday.filter(t => (Number(t.pnl) || 0) <= 0).length;

      const totalPnl = closedToday.reduce((sum, t) => sum + (Number(t.pnl) || 0), 0);
      const totalPremium = closedToday.reduce((sum, t) => sum + (Number(t.total_cost) || (Number(t.premium_per_contract) * t.contracts * 100)), 0);

      const winPnls = closedToday.filter(t => (Number(t.pnl) || 0) > 0).map(t => Number(t.pnl));
      const lossPnls = closedToday.filter(t => (Number(t.pnl) || 0) <= 0).map(t => Number(t.pnl));
      const avgWin = winPnls.length > 0 ? winPnls.reduce((a, b) => a + b, 0) / winPnls.length : 0;
      const avgLoss = lossPnls.length > 0 ? lossPnls.reduce((a, b) => a + b, 0) / lossPnls.length : 0;

      const totalWins = winPnls.reduce((a, b) => a + b, 0);
      const totalLosses = Math.abs(lossPnls.reduce((a, b) => a + b, 0));
      const profitFactor = totalLosses > 0 ? totalWins / totalLosses : totalWins > 0 ? 999 : 0;
      const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

      const firstTrade = closedToday.length > 0 ? closedToday[0].created_at : null;
      const lastTrade = closedToday.length > 0 ? closedToday[closedToday.length - 1].closed_at : null;

      const consecutiveLosses = (bot.consecutive_losses as number) ?? 0;
      const maxConsecLosses = (bot.max_consecutive_losses as number) ?? 8;
      const cooldownMins = (bot.cooldown_minutes as number) ?? 10;
      const cooldownTriggered = consecutiveLosses >= maxConsecLosses;

      const dailyProfitTarget = bot.daily_profit_target ? Number(bot.daily_profit_target) : 0;
      const dailyFloorAmount = bot.daily_floor_amount ? Number(bot.daily_floor_amount) : 0;
      const hitProfitTarget = totalPnl >= dailyProfitTarget;
      const hitDailyFloor = totalPnl <= dailyFloorAmount;

      const paperBalanceStart = bot.paper_balance_start ? Number(bot.paper_balance_start) : 0;
      const paperBalanceEnd = bot.paper_balance ? Number(bot.paper_balance) : 0;

      // Upsert daily stats
      await supabase.from('daily_bot_stats').upsert({
        bot_id: botId,
        bot_name: botName,
        bot_symbol: botSymbol,
        bot_signal: botSignal,
        date: today,
        total_trades: totalTrades,
        winning_trades: winningTrades,
        losing_trades: losingTrades,
        total_pnl: totalPnl,
        total_premium: totalPremium,
        avg_win: avgWin,
        avg_loss: avgLoss,
        profit_factor: profitFactor,
        win_rate: winRate,
        first_trade_time: firstTrade,
        last_trade_time: lastTrade,
        consecutive_losses: consecutiveLosses,
        max_consecutive_losses: maxConsecLosses,
        cooldown_triggered: cooldownTriggered,
        cooldown_minutes: cooldownMins,
        daily_profit_target: dailyProfitTarget,
        daily_floor_amount: dailyFloorAmount,
        hit_profit_target: hitProfitTarget,
        hit_daily_floor: hitDailyFloor,
        paper_balance_start: paperBalanceStart,
        paper_balance_end: paperBalanceEnd,
        updated_at: new Date().toISOString()
      }, { onConflict: 'bot_id,date' });
    }

    // Instant manual close: called when user clicks "Close Now" on a specific trade
    if (action === 'close_trade') {
      const tradeId = body.trade_id;
      if (!tradeId) return new Response(JSON.stringify({ error: 'trade_id required' }), { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

      const { data: open } = await supabase.from('options_trades').select('*').eq('id', tradeId).single();
      if (!open) return new Response(JSON.stringify({ error: 'Trade not found' }), { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });

      const { data: bot } = await supabase.from('options_bots').select('*').eq('id', open.bot_id).single();
      const interval = bot?.bot_interval ?? '1h';
      const R = 0.05;

      let optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, interval, bot?.user_id);
      if (!optionPrice || optionPrice <= 0) {
        const candles = await fetchCandles(open.symbol, interval, 60);
        if (candles.length) {
          const spotPrice = candles[candles.length - 1].close;
          const sigma = calcHistoricalVolatility(candles.map((c: any) => c.close), 20, interval);
          const expDate = new Date(open.expiration_date);
          const T = Math.max(0, (expDate.getTime() - Date.now()) / (365 * 24 * 60 * 60 * 1000));
          optionPrice = blackScholes(spotPrice, open.strike, T, R, sigma, open.option_type);
        }
      }
      if (!optionPrice || optionPrice <= 0) optionPrice = Number(open.premium_per_contract);
      // Sanity clamp: exit price can never be negative or produce loss > 100% of entry
      const _entryPremium1 = Number(open.premium_per_contract);
      optionPrice = Math.max(0, Math.min(optionPrice, _entryPremium1 * 10));

      const pnl = Math.max(-(Number(open.total_cost) || _entryPremium1 * open.contracts * 100), (optionPrice - _entryPremium1) * open.contracts * 100);
      await supabase.from('options_trades').update({ status: 'closed', exit_price: optionPrice, pnl, closed_at: new Date().toISOString() }).eq('id', tradeId);

      if (bot && bot.broker === 'paper') {
        const bal = Number(bot.paper_balance ?? 100000);
        await supabase.from('options_bots').update({ paper_balance: bal + Number(open.total_cost) + pnl }).eq('id', open.bot_id);
      }
      return new Response(JSON.stringify({ success: true, symbol: open.symbol, exit_price: optionPrice, pnl: pnl.toFixed(2) }), { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
    }

  }

  try {
    let targetBotId: string | null = null;
    let targetUserId: string | null = null;
    let forceRun = false;

    // INDEPENDENT MODE: Options bot runs on its own schedule via cron
    // No sync trigger from stock bot - generates its own signals
    if (req.method === 'POST') {
      const authHeader = req.headers.get('Authorization');
      const body = _parsedBody || {};
      const cronSecret = body.cron_secret;
      const validCron  = cronSecret === Deno.env.get('CRON_SECRET');
      if (!validCron && authHeader) {
        const token = authHeader.replace('Bearer ', '');
        const { data: { user } } = await supabase.auth.getUser(token);
        if (user) targetUserId = user.id;
      }
      targetBotId = body.bot_id || null;
      targetUserId = targetUserId || body.user_id || null;
      forceRun = body.force === true;
    }

    let query = supabase.from('options_bots').select('*');
    if (!forceRun) query = query.eq('enabled', true).eq('auto_submit', true);
    if (targetBotId)  query = query.eq('id', targetBotId);
    if (targetUserId) query = query.eq('user_id', targetUserId);

    console.log(`[OptionsBot] Query: targetBotId=${targetBotId}, targetUserId=${targetUserId}, independent_mode=true`);

    const { data: bots, error: botErr } = await query;
    
    if (botErr) {
      console.error('[OptionsBot] Query error:', botErr);
    }
    console.log(`[OptionsBot] Found ${bots?.length || 0} bots`);
    if (bots && bots.length > 0) {
      console.log('[OptionsBot] Bot names:', bots.map(b => b.name).join(', '));
    }
    if (botErr) throw botErr;
    if (!bots || bots.length === 0) {
      return new Response(JSON.stringify({ message: 'No active options bots', debug: { targetBotId, targetUserId } }), {
        status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    console.log(`Found ${bots.length} active bots:`, bots.map(b => ({ id: b.id, name: b.name, user_id: b.user_id?.slice(0,8), symbol: b.bot_symbol, scan_mode: b.bot_scan_mode })));

    const results: object[] = [];
    const R = 0.05; // risk-free rate
    const now = new Date();
    
    // Check market hours (options on stocks only trade 9:30 AM - 4:00 PM ET)
    // Use UTC offset for ET (UTC-5 or UTC-4 depending on DST)
    const utcHour = now.getUTCHours();
    const utcMinute = now.getUTCMinutes();
    const utcDay = now.getUTCDay();
    
    // Convert UTC to ET using proper timezone (handles DST automatically)
    const etNowStr = now.toLocaleString('en-US', { timeZone: 'America/New_York' });
    const etDate = new Date(etNowStr);
    let etHour = etDate.getHours();
    let etMinute = etDate.getMinutes();
    let etDay = etDate.getDay();
    
    const isWeekday = etDay >= 1 && etDay <= 5;
    const isOptionsMarketHours = isWeekday && (etHour > 9 || (etHour === 9 && etMinute >= 30)) && (etHour < 15 || (etHour === 15 && etMinute <= 59));
    
    const isAfter930Buffer = etHour >= 9;
    
    console.log(`[OptionsBot] Market hours check: ET=${etHour}:${etMinute}, day=${etDay}, weekday=${isWeekday}, open=${isOptionsMarketHours}, after930buffer=${isAfter930Buffer}`);

    const SCAN_STOCKS = [
      'AAPL','MSFT','AMZN','NVDA','TSLA','GOOG','META','NFLX',
      'JPM','BAC','WFC','V','MA','PG','KO','PFE','UNH','HD',
      'INTC','CSCO','ADBE','CRM','ORCL','AMD','QCOM','TXN','IBM','AVGO',
      'XOM','CVX','BA','CAT','MMM','GE','HON','LMT','NOC','DE',
      'C','GS','MS','AXP','BLK','SCHW','BK','SPGI','ICE',
      'MRK','ABBV','AMGN','BMY','LLY','GILD','JNJ','REGN','VRTX','BIIB',
      'WMT','COST','TGT','LOW','MCD','SBUX','NKE','BKNG',
      'SNAP','UBER','LYFT','SPOT','ZM','DOCU','PINS','ROKU','SHOP',
      'CVS','TMO','MDT','ISRG','F','GM',
      // High volatility growth stocks (great for options)
      'SNOW','CRWD','NET','DDOG','MDB','OKTA','SPLK','FSLR','ENPH','SEDG',
      'DKNG','CHPT','LCID','RIVN','HOOD','SOFI','AI','PLTR','ASML','MU',
      'LRCX','KLAC','AMAT','MRVL','NXPI','CDNS','SNPS','ANET','FTNT','PANW',
      'GME','AMC','BBBY','EXPR','KOSS','NAKD','SNDL','TLRY','ACB','CGC',
      // ETFs (high volume options)
      'QQQ','SPY','VOO','IVV','VTI','VUG','QQQM','SCHG','XLK','VGT','SMH','TQQQ',
    ];

    const SCAN_ETFS = [
      'QQQ','SPY','VOO','IVV','VTI','VUG','QQQM','SCHG','XLK','VGT','SMH','TQQQ',
    ];

    const SCAN_TOP10 = [
      'SMCI','TSLA','NVDA','COIN','PLTR','AMD','MRNA','MSTY','ENPH','VKTX','CCL',
    ];

    const SCAN_BOOF = [
      'QQQ','SPY','TSLA','NVDA','AMD','AAPL','MSFT','AMZN',
    ];

    const SCAN_BOOF_OPTIONS = [
      'RIVN','AMC','SOFI','NIO','XPEV','LCID','GME','HOOD','SPCE','NKLA','PLUG','FCEL','SENS',
    ];

    const SCAN_BOOFINATOR = [
      'SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOG',
    ];

    const SCAN_BOOFINATOR_STOCKS = [
      'TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOG',
    ];

    const SCAN_BOOF5 = [
      'NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD',
    ];

    const SCAN_BOOF5_WITH_ETF = [
      'NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD','QQQ','SPY',
    ];

    const SCAN_BOOF5_22 = [
      'NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD',
    ];

    const SCAN_BOOF5_WITH_ETF_22 = [
      'NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD','QQQ','SPY',
    ];

    const SCAN_BOOF5_23 = [
      'NVDA','AAPL','META','GOOG','AMD',
    ];

    const SCAN_BOOF5_WITH_ETF_23 = [
      'NVDA','AAPL','META','GOOG','AMD','QQQ','SPY',
    ];

    const SCAN_BOOF24 = [
      'NVDA','AAPL','META','MSFT','AMZN','GOOG','AVGO','TSLA','LLY','PLTR',
    ];

    const SCAN_BOOF_DUO = [
      'QQQ','SPY',
    ];

    const SCAN_BOOF_NOETF = [
      'NVDA','AAPL','MSFT','AMZN','GOOG','AVGO','META','TSLA','LLY',
    ];

    const SCAN_BOOF_ETF = [
      'NVDA','AAPL','MSFT','AMZN','GOOG','AVGO','META','TSLA','LLY','QQQ','SPY',
    ];

    const SCAN_DUO = [
      'SPY','QQQ',
    ];

    const SCAN_9_BACKTEST = [
      'TSLA','NVDA','COIN','PLTR','TSM','AAPL','AMZN','META','GOOG',
    ];

    const SCAN_CRYPTO = [
      'BTC/USD','ETH/USD','SOL/USD','AVAX/USD','LINK/USD',
      'UNI/USD','AAVE/USD','CRV/USD','LDO/USD','MATIC/USD',
    ];

    const SCAN_TOP50 = [
      'SNGX','HTCO','ERAS','BIYA','ACST','ACB','AIXI','AMST','EOSE','JBLU',
      'LAES','SLS','BE','CIFR','RDW','IREN','BRLS','EDSA','KNSA','OMCL',
      'CVLT','CNC','HRI','NVTS','CLS','RBLX','PLTR','TSLA','NVDA','AMD',
      'META','NFLX','AMZN','SMCI','NVR','AZO','MELI','GEV','MPWR','CAR',
      'SPY','QQQ','AAPL','MSFT','GOOG','AVGO','INTC','PYPL','SNAP','UBER',
    ];

    // Shared signal cache: boof22/boof23 signals are broadcast to all bots using same signal type
    const sharedSignalCache = new Map<string, { signal: string; price: number; reason: string; sigResult: any }>();

    for (const bot of bots) {
      // INDEPENDENT MODE: Options bot runs on its own schedule, scans symbols like stock bot
      console.log(`[OptionsBot] Running bot "${bot.name}" independently`);
      
      // Derive run interval from trading style (bot_interval) — no separate UI setting needed
      const intervalToMinutes: Record<string, number> = { '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240 };
      const botInterval = (bot.bot_interval as string) || '5m';
      const runIntervalMin = (bot.run_interval_min as number) ?? intervalToMinutes[botInterval] ?? 5;
      const lastRunAt = bot.last_run_at ? new Date(bot.last_run_at as string) : null;
      const minutesSinceLastRun = lastRunAt ? (now.getTime() - lastRunAt.getTime()) / (1000 * 60) : Infinity;
      
      if (!forceRun && minutesSinceLastRun < runIntervalMin) {
        console.log(`[OptionsBot] Skipping "${bot.name}" - ran ${minutesSinceLastRun.toFixed(1)}m ago, interval=${runIntervalMin}m`);
        continue;
      }
      
      // Options only trade during market hours + delay buffer after 9:30 open
      // Crypto/futures trade 24/7 — skip market hours gate for those symbols
      const isCryptoBotSym = ((bot.bot_symbol as string) || '').includes('/') || ((bot.bot_symbol as string) || '').includes('-USD') || ((bot.bot_scan_mode as string) || '') === 'scan_crypto';
      const isFuturesBotSym = ((bot.bot_symbol as string) || '').includes('=F');
      const is24hBot = isCryptoBotSym || isFuturesBotSym;
      const delayMin = (bot.market_open_delay_min as number) ?? 0;
      const isAfterOpenBuffer = etHour > 9 || (etHour === 9 && etMinute >= (30 + delayMin));
      if (!forceRun && !is24hBot && (!isOptionsMarketHours || !isAfterOpenBuffer)) {
        console.log(`[OptionsBot] Skipping "${bot.name}" - markets closed or within open delay (ET=${etHour}:${etMinute}, delayMin=${delayMin})`);
        results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `Markets closed (ET=${etHour}:${etMinute})` });
        continue;
      }
      const expiryType = bot.bot_expiry_type ?? 'weekly';
      const isAfter359PM_ET = etHour > 15 || (etHour === 15 && etMinute >= 59); // 3:59 PM ET
      if (!forceRun && isAfter359PM_ET) {
        console.log(`[OptionsBot] Skipping "${bot.name}" - EOD cutoff reached (after 3:59 PM ET)`);
        continue;
      }

      // Daily profit target: skip new entries if today's realized P&L already hit the target
      const dailyProfitTarget = bot.daily_profit_target ? Number(bot.daily_profit_target) : null;
      if (!forceRun && dailyProfitTarget && dailyProfitTarget > 0) {
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const { data: todayTrades } = await supabase.from('options_trades')
          .select('pnl').eq('bot_id', bot.id).eq('status', 'closed')
          .gte('closed_at', todayStart.toISOString());
        const todayPnl = (todayTrades || []).reduce((sum: number, t: any) => sum + (Number(t.pnl) || 0), 0);
        if (todayPnl >= dailyProfitTarget) {
          console.log(`[OptionsBot] Skipping "${bot.name}" - daily profit target hit ($${todayPnl.toFixed(2)} >= $${dailyProfitTarget})`);
          results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `Daily profit target hit ($${todayPnl.toFixed(2)})` });
          continue;
        }
      }

      // Daily reset: always reset triggered flags at start of new trading day (ET date)
      const etTodayStr = now.toLocaleDateString('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });
      const [etMonth, etDay2, etYear] = etTodayStr.split('/');
      const todayStr = `${etYear}-${etMonth}-${etDay2}`;
      const todayStart = new Date(`${todayStr}T00:00:00-05:00`); // ET midnight for DB queries
      const lastResetDate = (bot.daily_reset_date as string | null) ? (bot.daily_reset_date as string).slice(0, 10) : null;
      if (lastResetDate !== todayStr) {
        await supabase.from('options_bots').update({ 
          daily_peak_pnl: 0, 
          daily_floor_triggered: false,
          daily_trailing_stop_triggered: false,
          daily_trade_count: 0,
          daily_reset_date: todayStr
        }).eq('id', bot.id);
        bot.daily_peak_pnl = 0;
        bot.daily_floor_triggered = false;
        bot.daily_trailing_stop_triggered = false;
        bot.daily_trade_count = 0;
        console.log(`[OptionsBot] "${bot.name}" - Daily stats reset for new day ${todayStr}`);
        
        // Reset symbol slack scores to baseline for new day
        await supabase.from('symbol_slack_scores').update({ 
          slack_score: 100,  // Baseline start
          daily_trades: 0,
          daily_pnl: 0,
          daily_reset_date: todayStr
        }).eq('user_id', bot.user_id).eq('bot_id', bot.id).eq('bot_signal', (bot.bot_signal as string) || 'boof23');
        console.log(`[OptionsBot] Symbol slack scores reset to baseline (100) for new day`);
      }

      // No cooldowns - track losses for monitoring only
      console.log(`[OptionsBot] "${bot.name}" has ${bot.consecutive_losses ?? 0} consecutive losses (tracking only, no cooldown)`);

      // Daily Floor: hard stop-loss for daily P&L (stop trading if below this amount)
      const dailyFloorEnabled = bot.daily_floor_enabled ?? false;
      const dailyFloorAmount = bot.daily_floor_amount ? Number(bot.daily_floor_amount) : 0;
      
      if (!forceRun && dailyFloorEnabled) {
        
        // Get current today's P&L (including open positions)
        const { data: todayTrades } = await supabase.from('options_trades')
          .select('*').eq('bot_id', bot.id).eq('status', 'closed')
          .gte('closed_at', todayStart.toISOString());
        const todayRealizedPnl = (todayTrades || []).reduce((sum: number, t: any) => sum + (Number(t.pnl) || 0), 0);
        
        // Include unrealized P&L from open trades
        const { data: openTrades } = await supabase.from('options_trades')
          .select('*').eq('bot_id', bot.id).eq('status', 'open');
        let todayUnrealizedPnl = 0;
        for (const t of (openTrades || [])) {
          if (t.current_price && t.current_price > 0) {
            const entry = Number(t.premium_per_contract) || 0;
            const contracts = Number(t.contracts) || 1;
            todayUnrealizedPnl += ((t.current_price - entry) * contracts * 100);
          }
        }
        const currentTodayPnl = todayRealizedPnl + todayUnrealizedPnl;
        
        // Update daily peak if current is higher
        const dailyPeak = Number(bot.daily_peak_pnl) || 0;
        if (currentTodayPnl > dailyPeak) {
          await supabase.from('options_bots').update({ daily_peak_pnl: currentTodayPnl }).eq('id', bot.id);
          console.log(`[OptionsBot] "${bot.name}" - New daily peak: $${currentTodayPnl.toFixed(2)} (was $${dailyPeak.toFixed(2)})`);
        }
        
        // Check daily floor: hard stop if P&L drops below floor amount
        if (dailyFloorEnabled && dailyFloorAmount > 0) {
          if (bot.daily_floor_triggered) {
            console.log(`[OptionsBot] Skipping "${bot.name}" - daily floor already triggered (floor was $${dailyFloorAmount.toFixed(2)}, current P&L $${currentTodayPnl.toFixed(2)})`);
            results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `Daily floor triggered ($${dailyFloorAmount.toFixed(2)})` });
            continue;
          }
          
          if (currentTodayPnl < dailyFloorAmount) {
            // Trigger daily floor stop
            await supabase.from('options_bots').update({ daily_floor_triggered: true }).eq('id', bot.id);
            console.log(`[OptionsBot] 🛑 DAILY FLOOR TRIGGERED for "${bot.name}" - P&L $${currentTodayPnl.toFixed(2)} dropped below floor $${dailyFloorAmount.toFixed(2)}`);
            results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `🛑 Daily floor: P&L $${currentTodayPnl.toFixed(2)} below $${dailyFloorAmount.toFixed(2)}` });
            continue;
          }
        }
        
        // Check daily trailing stop: stop if P&L drops X dollars from daily peak
        const dailyTrailingStopEnabled = bot.daily_trailing_stop_enabled ?? false;
        const dailyTrailingStopAmount = bot.daily_trailing_stop_amount ? Number(bot.daily_trailing_stop_amount) : 0;
        
        if (dailyTrailingStopEnabled && dailyTrailingStopAmount > 0) {
          const dailyPeak = Number(bot.daily_peak_pnl) || 0;
          const trailingStopLevel = dailyPeak - dailyTrailingStopAmount;
          
          if (bot.daily_trailing_stop_triggered) {
            console.log(`[OptionsBot] Skipping "${bot.name}" - daily trailing stop already triggered (peak was $${dailyPeak.toFixed(2)}, stop level $${trailingStopLevel.toFixed(2)})`);
            results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `Daily trailing stop triggered (peak $${dailyPeak.toFixed(2)})` });
            continue;
          }
          
          // Only apply trailing stop if we've made at least some profit (peak > 0)
          if (dailyPeak > 0 && currentTodayPnl < trailingStopLevel) {
            // Trigger daily trailing stop
            await supabase.from('options_bots').update({ daily_trailing_stop_triggered: true }).eq('id', bot.id);
            console.log(`[OptionsBot] 🛑 DAILY TRAILING STOP TRIGGERED for "${bot.name}" - P&L $${currentTodayPnl.toFixed(2)} dropped $${(dailyPeak - currentTodayPnl).toFixed(2)} from peak $${dailyPeak.toFixed(2)} (trailing amount: $${dailyTrailingStopAmount.toFixed(2)})`);

            // Close ALL open trades immediately
            const { data: openTrades } = await supabase.from('options_trades').select('*').eq('bot_id', bot.id).eq('status', 'open');
            if (openTrades && openTrades.length > 0) {
              console.log(`[OptionsBot] 🛑 Closing ${openTrades.length} open trade(s) for "${bot.name}" due to trailing stop`);
              for (const trade of openTrades) {
                const totalCost = Number(trade.total_cost) || (Number(trade.premium_per_contract) * trade.contracts * 100);
                // For paper: close at current P&L level (not waiting for TP/SL)
                const closePnl = totalCost * ((currentTodayPnl - (bot?.daily_peak_pnl || 0)) / (bot?.daily_peak_pnl || 1)); // proportional
                await supabase.from('options_trades').update({
                  status: 'closed',
                  exit_price: Number(trade.entry_premium) * (1 + closePnl/totalCost),
                  pnl: closePnl,
                  closed_at: new Date().toISOString(),
                  exit_type: 'trailing_stop'
                }).eq('id', trade.id);
                console.log(`[OptionsBot] 🛑 Closed trade ${trade.symbol} $${trade.strike} - P&L: $${closePnl.toFixed(2)}`);
              }
            }

            results.push({ bot_id: bot.id, symbol: bot.bot_symbol, status: 'skipped', reason: `🛑 Trailing stop: P&L dropped $${(dailyPeak - currentTodayPnl).toFixed(2)} from peak $${dailyPeak.toFixed(2)}` });
            continue;
          }
        }
      }

      const settings: BotSettings = {
        atrLength:      bot.bot_atr_length     ?? 10,
        atrMultiplier:  bot.bot_atr_multiplier ?? 3.0,
        emaLength:      bot.bot_ema_length     ?? 50,
        adxLength:      bot.bot_adx_length     ?? 14,
        adxThreshold:   bot.bot_adx_threshold  ?? 10,
        symbol:         bot.bot_symbol         ?? 'SPY',
        dollarAmount:   bot.bot_dollar_amount  ?? 500,
        interval:       bot.bot_interval       ?? '1h',
        tradeDirection: bot.bot_trade_direction ?? 'both',
        expiryType:     bot.bot_expiry_type    ?? 'weekly',
        otmStrikes:     bot.bot_otm_strikes    ?? 1,
        strikeMode:     bot.bot_strike_mode    ?? 'budget',
        manualStrike:   bot.bot_manual_strike  ?? null,
        takeProfitPct:   bot.take_profit_pct    ?? 40,
        stopLossPct:     bot.stop_loss_pct      ?? 20,
        symbolRules:     (bot.symbol_rules as any) || [],
        marketOpenDelayMin: bot.market_open_delay_min ?? 0,
        botSignal:      (bot.bot_signal as string) || 'supertrend',
        signalInterval: (bot.signal_interval as string) || '5m',
        entryInterval:  (bot.entry_interval as string)  || '1m',
      };
      
      console.log(`[OptionsBot] Running "${bot.name}" | interval=${runIntervalMin}m | expiry=${expiryType} | signalTF=${settings.signalInterval} | entryTF=${settings.entryInterval}`);

      const scanMode: string = (bot.bot_scan_mode as string) || 'single';
      
      // INDEPENDENT MODE: Build symbol list from bot's scan mode
      // Single mode supports CSV: "SPY, QQQ, NVDA" → scans all three
      const singleSymbols = (settings.symbol as string).split(',').map((s:string) => s.trim().toUpperCase()).filter(Boolean);
      const symbolList: string[] = scanMode === 'scan_stocks' ? SCAN_STOCKS
        : scanMode === 'scan_etfs' ? SCAN_ETFS
        : scanMode === 'scan_top10' ? SCAN_TOP10
        : scanMode === 'scan_top50' ? SCAN_TOP50
        : scanMode === 'scan_boof' ? SCAN_BOOF
        : scanMode === 'scan_boof_options' ? SCAN_BOOF_OPTIONS
        : scanMode === 'scan_boofinator' ? SCAN_BOOFINATOR
        : scanMode === 'scan_boofinator_stocks' ? SCAN_BOOFINATOR_STOCKS
        : scanMode === 'scan_boof5' ? SCAN_BOOF5
        : scanMode === 'scan_boof5_with_etf' ? SCAN_BOOF5_WITH_ETF
        : scanMode === 'scan_boof5_22' ? SCAN_BOOF5_22
        : scanMode === 'scan_boof5_with_etf_22' ? SCAN_BOOF5_WITH_ETF_22
        : scanMode === 'scan_boof5_23' ? SCAN_BOOF5_23
        : scanMode === 'scan_boof5_with_etf_23' ? SCAN_BOOF5_WITH_ETF_23
        : scanMode === 'scan_boof24' ? SCAN_BOOF24
        : scanMode === 'scan_boof_duo' ? SCAN_BOOF_DUO
        : scanMode === 'scan_boof_noetf' ? SCAN_BOOF_NOETF
        : scanMode === 'scan_boof_etf' ? SCAN_BOOF_ETF
        : scanMode === 'scan_9_backtest' ? SCAN_9_BACKTEST
        : scanMode === 'scan_duo' ? SCAN_DUO
        : scanMode === 'scan_crypto' ? SCAN_CRYPTO
        : singleSymbols;

      console.log(`[OptionsBot] "${bot.name}" | scanMode=${scanMode} | symbols=${symbolList.length} | list=[${symbolList.slice(0,5).join(',')}...${symbolList.slice(-3).join(',')}]`);

      // Fetch symbol slack scores for filtering/ranking
      const { data: slackScores } = await supabase
        .from('symbol_slack_scores')
        .select('symbol, slack_score, win_rate, avg_pnl_per_trade, total_trades')
        .eq('user_id', bot.user_id)
        .eq('bot_id', bot.id)
        .eq('bot_signal', (bot.bot_signal as string) || 'boof23')
        .in('symbol', symbolList);
      
      interface SlackScore {
        symbol: string;
        slack_score: number;
        win_rate: number;
        avg_pnl_per_trade: number;
        total_trades: number;
      }
      
      const slackMap = new Map<string, SlackScore>((slackScores || []).map((s: any) => [s.symbol, s as SlackScore]));
      
      // Log slack summary (no longer filtering - trade all symbols with adjusted size)
      console.log(`[OptionsBot] Symbol Slack Summary:`);
      symbolList.forEach((sym: string) => {
        const s = slackMap.get(sym);
        if (s) {
          const rating = s.slack_score > 500 ? 'HIGH' : s.slack_score > 100 ? 'MED' : s.slack_score > 50 ? 'LOW' : 'MIN';
          console.log(`  ${sym}: slack=${s.slack_score.toFixed(1)} | win=${s.win_rate.toFixed(1)}% | avg=$${s.avg_pnl_per_trade.toFixed(2)} | trades=${s.total_trades} [${rating}]`);
        } else {
          console.log(`  ${sym}: (no history yet)`);
        }
      });
      
      // No filtering - trade all symbols with position size adjusted by slack score
      const finalSymbolList = symbolList;
      console.log(`[OptionsBot] "${bot.name}" | scanning ${finalSymbolList.length} symbols (no slack filter)`);

      try {
        // Fetch Alpaca creds once per bot run (used for both TP/SL and new trade pricing)
        const alpacaCreds = await supabase.from('broker_credentials').select('credentials').eq('user_id', bot.user_id).eq('broker', 'alpaca').maybeSingle().then((r: any) => r.data?.credentials);

        // ── TP/SL check on all open positions using REAL option prices ──
        const { data: allOpen } = await supabase.from('options_trades').select('*').eq('bot_id', bot.id).eq('status', 'open');
        if (allOpen && allOpen.length > 0) {
          for (const open of allOpen) {
            try {
              // Minimum hold time (paper trading only): skip TP/SL for very new trades
              // 1m bots use 30s hold, others use 2 minutes — avoids Black-Scholes misfires at entry
              if (bot.broker === 'paper') {
                const tradeAgeMs = Date.now() - new Date(open.created_at).getTime();
                const minHoldMs = settings.interval === '1m' ? 30 * 1000 : 2 * 60 * 1000;
                if (tradeAgeMs < minHoldMs) {
                  console.log(`[OptionsBot] SKIP TP/SL for ${open.symbol} — paper trade only ${Math.round(tradeAgeMs/1000)}s old, min hold=${minHoldMs/1000}s`);
                  continue;
                }
              }

              // Build Tradier option symbol format: SPY241231C00580000
              const expDate = new Date(open.expiration_date);
              const yy = String(expDate.getFullYear()).slice(-2);
              const mm = String(expDate.getMonth() + 1).padStart(2, '0');
              const dd = String(expDate.getDate()).padStart(2, '0');
              const strikeCents = Math.round(open.strike * 1000);
              const optSymbol = `${open.symbol}${yy}${mm}${dd}${open.option_type.toUpperCase().charAt(0)}${String(strikeCents).padStart(8, '0')}`;
              
              // Fetch REAL option price — Alpaca OPRA → Black-Scholes
              // Try Alpaca first to see if we get a real quote
              let optionPrice = 0;
              let source = 'none';
              if (alpacaCreds?.api_key) {
                optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, settings.interval, bot.user_id, settings.expiryType, alpacaCreds.api_key, alpacaCreds.secret_key);
                source = optionPrice > 0 ? 'alpaca_real' : 'alpaca_miss';
              }
              // Fall back to Black-Scholes if Alpaca returned nothing
              if (!optionPrice || optionPrice <= 0) {
                optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, settings.interval, bot.user_id, settings.expiryType, undefined, undefined);
                source = optionPrice > 0 ? 'black_scholes' : 'none';
              }

              if (!optionPrice || optionPrice <= 0) {
                console.log(`[OptionsBot] SKIP TP/SL for ${open.symbol} $${open.strike} — no real price available, will retry next cycle`);
                continue;
              }

              const totalCost = Number(open.total_cost) || (Number(open.premium_per_contract) * open.contracts * 100);
              const currentValue = optionPrice * open.contracts * 100;
              const pnlNow = currentValue - totalCost;
              const pctChange = (pnlNow / totalCost) * 100;
              const entryPremium = Number(open.premium_per_contract);

              // Sanity check: block if showing worse than -95% (likely bad price data)
              if (pctChange < -95) {
                console.log(`[OptionsBot] SKIP TP/SL for ${open.symbol} $${open.strike} — pct ${pctChange.toFixed(1)}% looks wrong, skipping`);
                continue;
              }
              // Sanity check: when using Black-Scholes (no Alpaca real quote),
              // cross-check against delta-estimated P&L using actual spot movement.
              // If BS shows >2x what delta math predicts, replace with delta estimate.
              if (source === 'black_scholes' && open.entry_spot) {
                try {
                  const tpslCandles = await fetchCandles(open.symbol, settings.interval, 5);
                  const spotNow = tpslCandles.length > 0 ? tpslCandles[tpslCandles.length - 1].close : 0;
                  if (spotNow > 0) {
                    const spotMove = spotNow - Number(open.entry_spot);
                    const delta = open.option_type === 'call' ? 0.5 : -0.5;
                    const deltaEstPnl = delta * spotMove * open.contracts * 100;
                    const deltaEstPct = (deltaEstPnl / totalCost) * 100;
                    // If BS pctChange is more than 2x worse than delta estimate, it's wrong
                    if (pctChange < -5 && deltaEstPct > pctChange * 2) {
                      console.log(`[OptionsBot] BS price override for ${open.symbol}: BS=${pctChange.toFixed(1)}% but delta estimate=${deltaEstPct.toFixed(1)}% (spot moved $${spotMove.toFixed(2)}). Using delta estimate.`);
                      const correctedPnl = deltaEstPnl;
                      const correctedPct = deltaEstPct;
                      // Re-evaluate TP/SL with corrected values
                      const slThreshold2 = settings.stopLossPct < 0 ? settings.stopLossPct : -Math.abs(settings.stopLossPct);
                      if (correctedPct < slThreshold2 || correctedPct >= settings.takeProfitPct) {
                        // Corrected value still triggers — allow with corrected P&L
                        const exitPrice2 = entryPremium + (delta * spotMove);
                        await supabase.from('options_trades').update({ status: 'closed', exit_price: Math.max(0, exitPrice2), pnl: correctedPnl, closed_at: new Date().toISOString() }).eq('id', open.id);
                        if (bot.broker === 'paper') {
                          const bal2 = Number((await supabase.from('options_bots').select('paper_balance').eq('id', bot.id).single()).data?.paper_balance ?? 100000);
                          await supabase.from('options_bots').update({ paper_balance: bal2 + totalCost + correctedPnl }).eq('id', bot.id);
                        }
                        results.push({ bot_id: bot.id, symbol: open.symbol, status: 'closed', pnl: correctedPnl.toFixed(2), reason: `TP/SL triggered (delta-corrected): ${correctedPct.toFixed(1)}%` });
                      } else {
                        console.log(`[OptionsBot] After delta correction, ${open.symbol} pct=${correctedPct.toFixed(1)}% — no TP/SL trigger`);
                      }
                      continue;
                    }
                  }
                } catch (_) {}
              }

              const symRuleMain = settings.symbolRules?.find(r => r.symbol?.toUpperCase() === (open as any).symbol?.toUpperCase());
              const effectiveTP = symRuleMain ? Number(symRuleMain.tp) : settings.takeProfitPct;
              const effectiveSL = symRuleMain ? Number(symRuleMain.sl) : settings.stopLossPct;
              const slThreshold = effectiveSL < 0 ? effectiveSL : -Math.abs(effectiveSL);
              const shouldTP = pctChange >= effectiveTP;
              const shouldSL = pctChange <= slThreshold;
              console.log(`[OptionsBot] TP/SL ${open.symbol} ${open.option_type} $${open.strike}: current=$${optionPrice.toFixed(2)} entry=$${Number(open.premium_per_contract).toFixed(2)} pct=${pctChange.toFixed(1)}% tp=${settings.takeProfitPct}% sl=${slThreshold}% shouldTP=${shouldTP} shouldSL=${shouldSL} source=${source}`);
              
              // EOD exit: 0DTE options — force close all positions at 2:00 PM ET
              // 1DTE options — force close 1 minute before market close (3:59 PM ET = 19:59 UTC)
              // Compute ET date correctly: ET = UTC - 4 hours (DST) or -5 hours (standard)
              // Since March 10 - Nov 3 is DST, during most trading hours we use -4
              const isDST = etDate.getHours() !== now.getUTCHours(); // Simple DST check
              const etOffsetMs = (isDST ? 4 : 5) * 60 * 60 * 1000;
              const etAdjustedDate = new Date(now.getTime() - etOffsetMs);
              const etDateStr = etAdjustedDate.toISOString().split('T')[0];
              const is0DTE = open.expiration_date === etDateStr;
              const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
              const is1DTE = open.expiration_date === tomorrowStr;
              const utcHour = now.getUTCHours();
              const utcMinute = now.getUTCMinutes();
              const isAfter359_EOD = utcHour > 19 || (utcHour === 19 && utcMinute >= 59); // 3:59 PM ET = 19:59 UTC
              const shouldEOD_0dte = is0DTE && isAfter359_EOD;
              const shouldEOD_1dte = is1DTE && isAfter359_EOD;
              const shouldEOD = shouldEOD_0dte || shouldEOD_1dte;
              console.log(`[OptionsBot] EOD Check ${open.symbol} ${open.option_type} $${open.strike}: exp=${open.expiration_date} etDate=${etDateStr} is0DTE=${is0DTE} is1DTE=${is1DTE} isAfter359=${isAfter359_EOD} shouldEOD=${shouldEOD}`);
              
              if (shouldTP || shouldSL || shouldEOD) {
                const pnl = pnlNow;
                let closeStatus = 'closed';
                let closeOrderId = null;
                let closeError = null;

                // Close live position
                if (bot.broker === 'tastytrade') {
                  console.log(`[OptionsBot] Closing Tastytrade position: ${open.contracts} contracts of ${open.symbol} ${open.option_type}`);
                  const tastyResult = await placeTastytradeOptionOrder(
                    supabase, bot.user_id, open.symbol, open.expiration_date,
                    open.option_type, open.strike, 'Sell to Close', open.contracts
                  );
                  if (tastyResult.success) {
                    closeStatus = 'closed';
                    closeOrderId = tastyResult.orderId;
                    if (tastyResult.fillPrice && tastyResult.fillPrice > 0) {
                      optionPrice = tastyResult.fillPrice; // use real exit price for P&L
                      console.log(`[OptionsBot] Tastytrade real exit price: $${optionPrice.toFixed(2)}/contract`);
                    }
                  } else {
                    closeError = tastyResult.error;
                    console.error(`[OptionsBot] Tastytrade close failed: ${closeError}`);
                  }
                } else if ((bot.broker === 'alpaca' || bot.broker === 'alpaca_paper') && open.order_id) {
                  console.log(`[OptionsBot] Closing Alpaca position: ${open.contracts} contracts of ${open.symbol} ${open.option_type}`);
                  const alpacaResult = await placeAlpacaOptionOrder(
                    supabase, bot.user_id, open.symbol, open.expiration_date,
                    open.option_type, open.strike, 'sell', open.contracts, bot.broker === 'alpaca_paper', optionPrice
                  );
                  if (alpacaResult.success) {
                    closeStatus = alpacaResult.status === 'filled' ? 'closed' : 'closing';
                    closeOrderId = alpacaResult.orderId;
                    if (alpacaResult.fillPrice && alpacaResult.fillPrice > 0) {
                      optionPrice = alpacaResult.fillPrice;
                    }
                  } else {
                    closeError = alpacaResult.error;
                    console.error(`[OptionsBot] Alpaca close failed: ${closeError}`);
                  }
                } else {
                  // Paper trading: update virtual balance
                  const { data: botRow } = await supabase.from('options_bots').select('paper_balance').eq('id', bot.id).single();
                  const bal = Number(botRow?.paper_balance ?? 100000);
                  await supabase.from('options_bots').update({ paper_balance: bal + (open.total_cost + pnl) }).eq('id', bot.id);
                }

                await supabase.from('options_trades').update({ 
                  status: closeStatus, 
                  exit_price: optionPrice, 
                  pnl, 
                  close_order_id: closeOrderId,
                  broker_error: closeError,
                  closed_at: new Date().toISOString() 
                }).eq('id', open.id);
                
                const exitReason = shouldEOD ? 'eod_exit' : shouldTP ? 'take_profit' : 'stop_loss';
                results.push({ bot_id: bot.id, symbol: open.symbol, status: exitReason, pct_change: pctChange.toFixed(1) + '%', pnl: pnl.toFixed(2), order_id: closeOrderId, broker_error: closeError });
              }
            } catch (_) {}
          }
        }

        const tradedThisRun = new Set<string>();
        const botSignal = settings.botSignal || 'supertrend';
        const isMultiTfBot = botSignal === 'boof22' || botSignal === 'boof23';
        
        for (const sym of finalSymbolList) {
          try {
              // MULTI-TIMEFRAME: For Boof 22/23, use signalInterval as primary fetch
              // Otherwise use legacy settings.interval
              const primaryInterval = isMultiTfBot ? settings.signalInterval : settings.interval;
              const barsToFetch = primaryInterval === '1m' ? 1560 : 150;
              const candles = await fetchCandles(sym, primaryInterval, barsToFetch, alpacaCreds?.api_key, alpacaCreds?.secret_key);
              if (candles.length < 60) { results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Not enough candle data' }); continue; }

              // INDEPENDENT MODE: Always generate our own signal based on bot_signal setting
              let signal: 'buy' | 'sell' | 'none';
              let price: number;
              let reason: string;
              
              let sigResult: { signal: 'buy' | 'sell' | 'none', price: number, reason: string, trend?: number, ema?: number, adx?: number, ev?: number, stopLoss?: number, takeProfit?: number };
              if (botSignal === 'rsi_macd') {
                sigResult = generateSignalRSIMACD(candles, settings.tradeDirection);
              } else if (botSignal === 'boof20') {
                // Tightened for 1m scalping: ~3 trades/hour target (0.8% threshold vs 0.3% default)
                sigResult = generateSignalBoof20(candles, settings.tradeDirection, 0.008, -0.008);
              } else if (botSignal === 'boof30') {
                sigResult = generateSignalBoof30(candles, settings.tradeDirection);
              } else if (botSignal === 'boof50') {
                // Boof 5.0: Six-Factor Quant Model with optional trend filter
                const boof50TrendFilter = bot.trend_filter as string || 'none';
                const tfCandles = boof50TrendFilter !== 'none' ? await fetchCandles(sym, boof50TrendFilter, 100, alpacaCreds?.api_key, alpacaCreds?.secret_key) : undefined;
                sigResult = generateSignalBoof50(candles, settings.tradeDirection, tfCandles);
              } else if (botSignal === 'boof60') {
                // Boof 6.0: Multi-Timeframe Scalping System
                // Fetches 1h (trend lock), 15m (EMA confirm), 1m (VWAP) in parallel
                const [b60_1h, b60_15m, b60_1m] = await Promise.all([
                  fetchCandles(sym, '1h', 50, alpacaCreds?.api_key, alpacaCreds?.secret_key).catch(() => [] as Candle[]),
                  fetchCandles(sym, '15m', 50, alpacaCreds?.api_key, alpacaCreds?.secret_key).catch(() => [] as Candle[]),
                  fetchCandles(sym, '1m', 390, alpacaCreds?.api_key, alpacaCreds?.secret_key).catch(() => [] as Candle[]),
                ]);
                sigResult = generateSignalBoof60(candles, b60_1h, b60_15m, b60_1m, settings.tradeDirection);
              } else if (botSignal === 'longer_swing') {
                // For 30m swing, fetch more candles and use Boof 3.0 for regime detection
                const swingCandles = await fetchCandles(sym, '30m', 200, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                if (swingCandles.length < 60) {
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Not enough 30m candle data' });
                  continue;
                }
                sigResult = generateSignalBoof30(swingCandles, settings.tradeDirection);
              } else if (botSignal === 'boof70') {
                const { data: recentTrades70 } = await supabase.from('options_trades')
                  .select('pnl').eq('bot_id', bot.id as string).eq('symbol', sym)
                  .not('pnl', 'is', null).order('closed_at', { ascending: false }).limit(20);
                const pnls70 = (recentTrades70 || []).map((t: any) => Number(t.pnl));
                const wins70 = pnls70.filter((p: number) => p > 0).length;
                const recentWinRate70 = pnls70.length > 0 ? wins70 / pnls70.length : 0.5;
                let consecutiveLosses70 = 0;
                for (const p of pnls70) { if (p <= 0) consecutiveLosses70++; else break; }
                const isCryptoSym70 = sym.includes('-USD') || sym.includes('/USD');
                // Kill-switch: 7+ consecutive losses → skip
                if (consecutiveLosses70 >= 7) {
                  console.log(`[Boof7.0][OptionsBot] Kill-switch: ${consecutiveLosses70} consecutive losses — paused`);
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Boof 7.0 kill-switch: ${consecutiveLosses70} consecutive losses` });
                  continue;
                }
                // Adaptive position sizing
                let sizePct70 = 1.0;
                if (recentWinRate70 >= 0.60) sizePct70 = 1.25;
                else if (recentWinRate70 < 0.40) sizePct70 = 0.60;
                if (consecutiveLosses70 >= 5) sizePct70 *= 0.25;
                else if (consecutiveLosses70 >= 3) sizePct70 *= 0.50;
                sizePct70 = Math.max(0.10, Math.min(1.50, sizePct70));
                if (sizePct70 !== 1.0) {
                  const orig = settings.dollarAmount;
                  settings.dollarAmount = Math.round(settings.dollarAmount * sizePct70);
                  console.log(`[Boof7.0][OptionsBot] Position size: ${(sizePct70*100).toFixed(0)}% → $${orig} → $${settings.dollarAmount}`);
                  await supabase.from('options_bots').update({ last_position_size_pct: sizePct70 }).eq('id', bot.id as string);
                }
                sigResult = generateSignalBoof70(candles, settings.tradeDirection, recentWinRate70, consecutiveLosses70, isCryptoSym70);
              } else if (botSignal === 'boof80') {
                // Boof 8.0: Adaptive AI Scalper — self-tunes TP/SL from trade history
                const { data: recentTrades80 } = await supabase.from('options_trades')
                  .select('reason, pnl, regime, premium_per_contract, contracts, total_cost').eq('bot_id', bot.id as string).eq('symbol', sym)
                  .not('pnl', 'is', null).order('closed_at', { ascending: false }).limit(20);
                const trades80 = (recentTrades80 || []).map((t: any) => {
                  const cost = Number(t.total_cost) || (Number(t.premium_per_contract) * Number(t.contracts) * 100);
                  const pnlPct = cost > 0 ? (Number(t.pnl) / cost) * 100 : Number(t.pnl) || 0;
                  return { reason: t.reason || '', pnlPct, regime: t.regime || 'UNKNOWN' };
                });
                const pnls80  = trades80.map((t: { pnlPct: number }) => t.pnlPct);
                const wins80  = pnls80.filter((p: number) => p > 0).length;
                const winRate80 = pnls80.length > 0 ? wins80 / pnls80.length : 0.5;
                let consLosses80 = 0;
                for (const p of pnls80) { if (p <= 0) consLosses80++; else break; }
                const isCrypto80 = sym.includes('-USD') || sym.includes('/USD');
                const boof80result = generateSignalBoof80(candles, settings.tradeDirection, {
                  recentTrades:      trades80,
                  consecutiveLosses: consLosses80,
                  recentWinRate:     winRate80,
                  isCrypto:          isCrypto80,
                });
                if (boof80result.killSwitch) {
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Boof 8.0 kill-switch: ${boof80result.killReason}` });
                  continue;
                }
                sigResult = { signal: boof80result.signal, price: boof80result.price, reason: boof80result.reason, trend: boof80result.trend, ema: boof80result.ema, adx: boof80result.adx };
                // Write adaptive TP/SL back to symbol_rules so UI reflects live values (even if no signal)
                if (boof80result.dynamicTP > 0) {
                  const currentRules: Array<{symbol:string;tp:number;sl:number;dir?:string;adapted_at?:string;base_tp?:number;base_sl?:number}> = (bot.symbol_rules as any) || [];
                  const ruleIdx = currentRules.findIndex((r: any) => r.symbol?.toUpperCase() === sym.toUpperCase());
                  // Hard SL floor by expiry — 0DTE can't go past -15%, 1DTE -20%, weekly+ -25%
                  const slFloor = settings.expiryType === '0dte' ? -15 : settings.expiryType === '1dte' ? -20 : -25;
                  const adaptedSL = Math.max(slFloor, boof80result.dynamicSL);
                  const existingRule = ruleIdx >= 0 ? currentRules[ruleIdx] : null;
                  const adaptedRule = {
                    symbol:     sym,
                    tp:         Math.round(boof80result.dynamicTP * 10) / 10,
                    sl:         Math.round(adaptedSL * 10) / 10,
                    dir:        existingRule?.dir || 'both',
                    base_tp:    existingRule?.base_tp ?? existingRule?.tp ?? Math.round(boof80result.dynamicTP * 10) / 10,
                    base_sl:    existingRule?.base_sl ?? existingRule?.sl ?? Math.round(adaptedSL * 10) / 10,
                    adapted_at: new Date().toISOString(),
                  };
                  const updatedRules = ruleIdx >= 0
                    ? currentRules.map((r: any, idx: number) => idx === ruleIdx ? adaptedRule : r)
                    : [...currentRules, adaptedRule];
                  await supabase.from('options_bots').update({ symbol_rules: updatedRules, last_ci: Math.round(boof80result.choppiness * 10) / 10 }).eq('id', bot.id as string);
                  console.log(`[Boof8.0] Adaptive TP/SL written: ${sym} tp=${adaptedRule.tp}% sl=${adaptedRule.sl}% ci=${boof80result.choppiness.toFixed(1)} pw=${boof80result.patternWeight.toFixed(2)}`);
                }
              } else if (botSignal === 'boof90') {
                // BOOF 9.0 - Precision Sniper (ultra-strict, multi-timeframe confluence)
                const [c1d, c4h] = await Promise.all([
                  fetchCandles(sym, '1d',  250, bot.user_id as string),
                  fetchCandles(sym, '4h', 100, bot.user_id as string),
                ]);
                sigResult = generateSignalBoof90(candles, c1d, c4h, settings.tradeDirection);
              } else if (botSignal === 'boof15') {
                // BOOF 15.0 - EV-Based Adaptive Trader (using new ported logic)
                const regime = classifyRegime150(candles);
                const boof150Result = generateSignalBoof150(candles, sym, regime, false, settings.tradeDirection);
                sigResult = { 
                  signal: boof150Result.signal === 'buy' ? 'buy' : boof150Result.signal === 'sell' ? 'sell' : 'none', 
                  price: boof150Result.price, 
                  reason: boof150Result.reason, 
                  ev: boof150Result.ev,
                  stopLoss: boof150Result.price * 0.997,  // -0.3% SL
                  takeProfit: boof150Result.price * 1.005  // +0.5% TP
                };
                console.log(`[OptionsBot] ${sym} Boof 15.0: signal=${boof150Result.signal} ev=${boof150Result.ev?.toFixed(4)} regime=${regime} score=${boof150Result.score.toFixed(1)}`);
                // Store regime for exit logic
                await supabase.from('options_trades').update({ regime }).eq('bot_id', bot.id as string);
              } else if (botSignal === 'boof16') {
                // BOOF 16.0 - Kelly Criterion + Transaction Costs (using new ported logic)
                const regime = classifyRegime150(candles);
                const boof150Result = generateSignalBoof150(candles, sym, regime, true, settings.tradeDirection);  // useKelly=true
                sigResult = { 
                  signal: boof150Result.signal === 'buy' ? 'buy' : boof150Result.signal === 'sell' ? 'sell' : 'none', 
                  price: boof150Result.price, 
                  reason: boof150Result.reason, 
                  ev: boof150Result.ev,
                  stopLoss: boof150Result.price * 0.997,  // -0.3% SL
                  takeProfit: boof150Result.price * 1.005  // +0.5% TP
                };
                console.log(`[OptionsBot] ${sym} Boof 16.0: signal=${boof150Result.signal} ev=${boof150Result.ev?.toFixed(4)} regime=${regime} score=${boof150Result.score.toFixed(1)} posSize=${boof150Result.positionSize.toFixed(2)}`);
                // Store regime for exit logic
                await supabase.from('options_trades').update({ regime }).eq('bot_id', bot.id as string);
              } else if (botSignal === 'boof14') {
                // BOOF 14.0 - Simplified EV-Based Entry (backup of original Boof 15.0)
                const boof14Result = generateSignalBoof14(candles, sym, settings.tradeDirection);
                sigResult = {
                  signal: boof14Result.signal,
                  price: boof14Result.price,
                  reason: boof14Result.reason
                };
                console.log(`[OptionsBot] ${sym} Boof 14.0: signal=${boof14Result.signal} score=${boof14Result.score.toFixed(1)} ev=${boof14Result.ev.toFixed(3)} regime=${boof14Result.regime} session=${boof14Result.session}`);
              } else if (botSignal === 'boof18') {
                // BOOF 18.0 - ORB + Compression + Regime Filter
                const boof18Result = generateSignalBoof18(candles, 50);  // Default symbol score of 50
                sigResult = {
                  signal: boof18Result.signal,
                  price: boof18Result.price,
                  reason: boof18Result.reason
                };
                console.log(`[OptionsBot] ${sym} Boof 18.0: signal=${boof18Result.signal} regime=${boof18Result.regime} signal_type=${boof18Result.signal_type} orb_strength=${boof18Result.orb_strength.toFixed(3)}`);
              } else if (botSignal === 'boof19') {
                // BOOF 19.0 - 0DTE Scalping for SPY/QQQ
                const boof19Result = generateSignalBoof19(candles, sym, settings.tradeDirection);
                sigResult = {
                  signal: boof19Result.signal,
                  price: boof19Result.price,
                  reason: boof19Result.reason
                };
                console.log(`[OptionsBot] ${sym} Boof 19.0: signal=${boof19Result.signal} layer=${boof19Result.layer} reason=${boof19Result.reason}`);
              } else if (botSignal === 'boof19v2') {
                // BOOF 19.0 V2 - Event-Driven High-Quality System
                const boof19v2Result = generateSignalBoof19V2(candles, sym, settings.tradeDirection);
                sigResult = {
                  signal: boof19v2Result.signal,
                  price: boof19v2Result.price,
                  reason: boof19v2Result.reason
                };
                console.log(`[OptionsBot] ${sym} Boof 19.0 V2: signal=${boof19v2Result.signal} setupType=${boof19v2Result.setupType} reason=${boof19v2Result.reason}`);
              } else if (botSignal === 'boof21') {
                // BOOF 21.0 — Volume Cluster S/R MTF Retest (10-min levels, 1-min entry)
                const cacheKey21 = `boof21:${sym}`;
                const cached21 = sharedSignalCache.get(cacheKey21);
                if (cached21) {
                  sigResult = (cached21 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 21.0: using shared signal from cache`);
                } else {
                  const b21TpPct = Number(bot.take_profit_pct ?? 35) / 100;
                  const b21SlPct = Math.abs(Number(bot.stop_loss_pct ?? 10)) / 100;
                  const boof21Result = generateSignalBoof21(candles, sym, b21TpPct, b21SlPct);
                  sigResult = {
                    signal: boof21Result.signal,
                    price: boof21Result.price,
                    reason: boof21Result.reason,
                    slack: boof21Result.slack
                  };
                  if (boof21Result.signal !== 'none') sharedSignalCache.set(cacheKey21, { signal: boof21Result.signal, price: boof21Result.price, reason: boof21Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 21.0: signal=${boof21Result.signal} direction=${boof21Result.direction} level=${boof21Result.level.toFixed(2)} str=${boof21Result.levelStrength.toFixed(1)} slack=${boof21Result.slack.toFixed(2)} tp=${b21TpPct*100}% sl=-${b21SlPct*100}% reason=${boof21Result.reason}`);
                }
              } else if (botSignal === 'boof22') {
                // BOOF 22.0 — Volume Cluster Array + ZigZag ATR Reversal (Multi-Timeframe)
                const cacheKey22 = `boof22:${sym}`;
                const cached22 = sharedSignalCache.get(cacheKey22);
                if (cached22) {
                  sigResult = (cached22 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 22.0: using shared signal from cache`);
                } else {
                  // MULTI-TIMEFRAME: candles already fetched at signalInterval, use them directly
                  const signalInterval = settings.signalInterval || '5m';
                  const entryInterval = settings.entryInterval || '1m';
                  const isMultiTf = signalInterval !== entryInterval;
                  
                  const b22TpPct = Number(bot.take_profit_pct ?? 35) / 100;
                  const b22SlPct = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
                  const boof22Result = getBoof22Signal(candles, sym, b22TpPct, b22SlPct);
                  
                  // MULTI-TIMEFRAME: If signal fires, fetch entry_interval for execution price
                  let entryPrice = boof22Result.price;
                  if (isMultiTf && boof22Result.signal !== 'none') {
                    const entryCandles = await fetchCandles(sym, entryInterval, 60, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                    if (entryCandles.length > 0) {
                      entryPrice = entryCandles[entryCandles.length - 1].close;
                      console.log(`[OptionsBot] ${sym} Boof 22.0 MTF: signal on ${signalInterval} @ ${boof22Result.price.toFixed(2)}, entry on ${entryInterval} @ ${entryPrice.toFixed(2)}`);
                    }
                  }
                  
                  sigResult = {
                    signal:     boof22Result.signal,
                    price:      entryPrice,
                    reason:     boof22Result.reason + (isMultiTf ? ` (MTF: ${signalInterval}→${entryInterval})` : ''),
                    atr:        boof22Result.atr,
                    takeProfit: boof22Result.tpPct * 100,
                    stopLoss:  -boof22Result.slPct * 100,
                    tier:       boof22Result.tier,
                    slack:      boof22Result.slack,
                  } as any;
                  if (boof22Result.signal !== 'none') sharedSignalCache.set(cacheKey22, { signal: boof22Result.signal, price: entryPrice, reason: boof22Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 22.0: signal=${boof22Result.signal} direction=${boof22Result.direction} tier=${boof22Result.tier} slack=${boof22Result.slack.toFixed(2)} cluster=${boof22Result.nearestCluster.toFixed(2)} str=${boof22Result.clusterStrength} atr=${boof22Result.atr.toFixed(4)} tp=+${(boof22Result.tpPct*100).toFixed(0)}% sl=-${(boof22Result.slPct*100).toFixed(0)}% reason=${boof22Result.reason}`);
                }
              } else if (botSignal === 'boof23') {
                // BOOF 23.0 — SR Cluster Entry + ZigZag Regime Filter (Multi-Timeframe)
                const cacheKey23 = `boof23:${sym}`;
                const cached23 = sharedSignalCache.get(cacheKey23);
                if (cached23) {
                  sigResult = (cached23 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 23.0: using shared signal from cache`);
                } else {
                  // MULTI-TIMEFRAME: candles already fetched at signalInterval, use them directly
                  const signalInterval = settings.signalInterval || '5m';
                  const entryInterval = settings.entryInterval || '1m';
                  const isMultiTf = signalInterval !== entryInterval;
                  
                  const b23TpPct = Number(bot.take_profit_pct ?? 0.45) / 100;
                  const b23SlPct = Math.abs(Number(bot.stop_loss_pct ?? 0.18)) / 100;
                  const boof23Result = getBoof23Signal(candles, sym, b23TpPct, b23SlPct);
                  
                  // MULTI-TIMEFRAME: If signal fires, fetch entry_interval for execution price
                  let entryPrice = boof23Result.price;
                  if (isMultiTf && boof23Result.signal !== 'none') {
                    const entryCandles = await fetchCandles(sym, entryInterval, 60, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                    if (entryCandles.length > 0) {
                      entryPrice = entryCandles[entryCandles.length - 1].close;
                      console.log(`[OptionsBot] ${sym} Boof 23.0 MTF: signal on ${signalInterval} @ ${boof23Result.price.toFixed(2)}, entry on ${entryInterval} @ ${entryPrice.toFixed(2)}`);
                    }
                  }
                  
                  sigResult = {
                    signal:     boof23Result.signal,
                    price:      entryPrice,
                    reason:     boof23Result.reason + (isMultiTf ? ` (MTF: ${signalInterval}→${entryInterval})` : ''),
                    atr:        boof23Result.atr,
                    takeProfit: boof23Result.tpPct * 100,
                    stopLoss:  -boof23Result.slPct * 100,
                    tier:       boof23Result.tier,
                    slack:      boof23Result.slack,
                    zzTrend:    boof23Result.zzTrend,
                  } as any;
                  if (boof23Result.signal !== 'none') sharedSignalCache.set(cacheKey23, { signal: boof23Result.signal, price: entryPrice, reason: boof23Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 23.0: signal=${boof23Result.signal} dir=${boof23Result.direction} tier=${boof23Result.tier} slack=${boof23Result.slack.toFixed(2)} zz=${boof23Result.zzTrend} cluster=${boof23Result.nearestCluster.toFixed(2)} str=${boof23Result.clusterStrength} atr=${boof23Result.atr.toFixed(4)} tp=+${(boof23Result.tpPct*100).toFixed(0)}% sl=-${(boof23Result.slPct*100).toFixed(0)}% reason=${boof23Result.reason}`);
                }
              } else if (botSignal === 'boof22_5') {
                // BOOF 22.5 — Fractal + ADX Chop Detection
                const cacheKey22_5 = `boof22_5:${sym}`;
                const cached22_5 = sharedSignalCache.get(cacheKey22_5);
                if (cached22_5) {
                  sigResult = (cached22_5 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 22.5: using shared signal from cache`);
                } else {
                  // Pre-detect chop via a quick ADX check so we pass the right TP/SL into the signal
                  const b22_5_TrendTp = Number(bot.take_profit_pct ?? 35) / 100;
                  const b22_5_TrendSl = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
                  const b22_5_ChopTp  = Number(bot.chop_take_profit_pct ?? bot.take_profit_pct ?? 25) / 100;
                  const b22_5_ChopSl  = Math.abs(Number(bot.chop_stop_loss_pct ?? bot.stop_loss_pct ?? 8)) / 100;
                  // Run once with trend values to get ADX tag, then re-run with correct TP/SL
                  const boof22_5_Probe = getBoof22v2Signal(candles, sym, b22_5_TrendTp, b22_5_TrendSl);
                  const b22_5_Chop = boof22_5_Probe.reason.includes('CHOP MODE');
                  const b22_5_TpPct = b22_5_Chop ? b22_5_ChopTp : b22_5_TrendTp;
                  const b22_5_SlPct = b22_5_Chop ? b22_5_ChopSl : b22_5_TrendSl;
                  const boof22_5_Result = b22_5_Chop ? getBoof22v2Signal(candles, sym, b22_5_TpPct, b22_5_SlPct) : boof22_5_Probe;
                  
                  sigResult = {
                    signal:     boof22_5_Result.signal,
                    price:      boof22_5_Result.price,
                    reason:     boof22_5_Result.reason,
                    atr:        boof22_5_Result.atr,
                    takeProfit: boof22_5_Result.tpPct * 100,
                    stopLoss:  -boof22_5_Result.slPct * 100,
                    tier:       boof22_5_Result.tier,
                    slack:      boof22_5_Result.slack,
                    mode:       boof22_5_Result.reason.includes('CHOP MODE') ? 'chop' : 'trend',
                  } as any;
                  if (boof22_5_Result.signal !== 'none') sharedSignalCache.set(cacheKey22_5, { signal: boof22_5_Result.signal, price: boof22_5_Result.price, reason: boof22_5_Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 22.5: signal=${boof22_5_Result.signal} dir=${boof22_5_Result.direction} tier=${boof22_5_Result.tier} slack=${boof22_5_Result.slack.toFixed(2)} atr=${boof22_5_Result.atr.toFixed(4)} tp=+${(boof22_5_Result.tpPct*100).toFixed(0)}% sl=-${(boof22_5_Result.slPct*100).toFixed(0)}% reason=${boof22_5_Result.reason}`);
                }
              } else if (botSignal === 'boof23_5') {
                // BOOF 23.5 — ZigZag + ADX Chop Detection
                const cacheKey23_5 = `boof23_5:${sym}`;
                const cached23_5 = sharedSignalCache.get(cacheKey23_5);
                if (cached23_5) {
                  sigResult = (cached23_5 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 23.5: using shared signal from cache`);
                } else {
                  const b23_5_TrendTp = Number(bot.take_profit_pct ?? 35) / 100;
                  const b23_5_TrendSl = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
                  const b23_5_ChopTp  = Number(bot.chop_take_profit_pct ?? bot.take_profit_pct ?? 25) / 100;
                  const b23_5_ChopSl  = Math.abs(Number(bot.chop_stop_loss_pct ?? bot.stop_loss_pct ?? 8)) / 100;
                  const boof23_5_Probe = getBoof23v2Signal(candles, sym, b23_5_TrendTp, b23_5_TrendSl);
                  const b23_5_Chop = boof23_5_Probe.reason.includes('CHOP MODE');
                  const b23_5_TpPct = b23_5_Chop ? b23_5_ChopTp : b23_5_TrendTp;
                  const b23_5_SlPct = b23_5_Chop ? b23_5_ChopSl : b23_5_TrendSl;
                  const boof23_5_Result = b23_5_Chop ? getBoof23v2Signal(candles, sym, b23_5_TpPct, b23_5_SlPct) : boof23_5_Probe;
                  
                  sigResult = {
                    signal:     boof23_5_Result.signal,
                    price:      boof23_5_Result.price,
                    reason:     boof23_5_Result.reason,
                    atr:        boof23_5_Result.atr,
                    takeProfit: boof23_5_Result.tpPct * 100,
                    stopLoss:  -boof23_5_Result.slPct * 100,
                    tier:       boof23_5_Result.tier,
                    slack:      boof23_5_Result.slack,
                    mode:       boof23_5_Result.reason.includes('CHOP MODE') ? 'chop' : 'trend',
                  } as any;
                  if (boof23_5_Result.signal !== 'none') sharedSignalCache.set(cacheKey23_5, { signal: boof23_5_Result.signal, price: boof23_5_Result.price, reason: boof23_5_Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 23.5: signal=${boof23_5_Result.signal} dir=${boof23_5_Result.direction} tier=${boof23_5_Result.tier} slack=${boof23_5_Result.slack.toFixed(2)} atr=${boof23_5_Result.atr.toFixed(4)} tp=+${(boof23_5_Result.tpPct*100).toFixed(0)}% sl=-${(boof23_5_Result.slPct*100).toFixed(0)}% reason=${boof23_5_Result.reason}`);
                }
              } else if (botSignal === 'boof24') {
                // BOOF 24.0 — Opening Range Breakout (ORB)
                const cacheKey24 = `boof24:${sym}`;
                const cached24 = sharedSignalCache.get(cacheKey24);
                if (cached24) {
                  sigResult = (cached24 as any).sigResult;
                  console.log(`[OptionsBot] ${sym} Boof 24.0 ORB: using shared signal from cache`);
                } else {
                  // Fetch SPY candles for market trend filter
                  const spyCandles = await fetchCandles('SPY', settings.interval, barsToFetch, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                  const boof24Result = getBoof24Signal(candles, sym, spyCandles);
                  sigResult = {
                    signal:     boof24Result.signal,
                    price:      boof24Result.price,
                    reason:     boof24Result.reason,
                    takeProfit: boof24Result.tpPct,
                    stopLoss:   boof24Result.slPct,
                    orbHigh:    boof24Result.orbHigh,
                    orbLow:     boof24Result.orbLow,
                  } as any;
                  if (boof24Result.signal !== 'none') sharedSignalCache.set(cacheKey24, { signal: boof24Result.signal, price: boof24Result.price, reason: boof24Result.reason, sigResult });
                  console.log(`[OptionsBot] ${sym} Boof 24.0 ORB: signal=${boof24Result.signal} dir=${boof24Result.direction} orb=[${boof24Result.orbLow?.toFixed(2)}-${boof24Result.orbHigh?.toFixed(2)}] vol=${boof24Result.relVolume?.toFixed(2)}x spy=${boof24Result.spyTrend} vwap=${boof24Result.vwapDist?.toFixed(2)}% tp=+${boof24Result.tpPct}% sl=${boof24Result.slPct}% reason=${boof24Result.reason}`);
                }
              } else if (botSignal === 'test_always_buy') {
                // TEST MODE: Always fires BUY signal to test trade execution
                const lastClose = candles[candles.length - 1].close;
                sigResult = { signal: 'buy', price: lastClose, reason: 'TEST MODE: Always BUY' };
              } else if (botSignal === 'test_always_sell') {
                // TEST MODE: Always fires SELL signal to test trade execution
                const lastClose = candles[candles.length - 1].close;
                sigResult = { signal: 'sell', price: lastClose, reason: 'TEST MODE: Always SELL' };
              } else {
                sigResult = generateSignal(candles, settings);
              }
              signal = sigResult.signal;
              price = sigResult.price;
              reason = sigResult.reason;

              // ── ADX GATE: Block all signals in choppy/ranging markets ──
              // ADX < 20 = no trend = chop = skip. Applies to ALL strategies EXCEPT boof24 (chop mode).
              // Boof 5.0 & SuperTrend return adx in sigResult. For others, calculate it.
              const isCryptoFuturesSym = sym.includes('/') || sym.includes('-USD') || sym.includes('=F');
              if (signal !== 'none' && botSignal !== 'test_always_buy' && botSignal !== 'test_always_sell' && !isCryptoFuturesSym && botSignal !== 'boof21' && botSignal !== 'boof22' && botSignal !== 'boof23' && botSignal !== 'boof24') {
                let adxVal = sigResult.adx ?? 0;
                if (!adxVal || adxVal <= 0) {
                  // Calculate ADX from current candles if not returned by signal
                  const dmi = calcDMI(candles.map(c => c.high), candles.map(c => c.low), candles.map(c => c.close), 14);
                  adxVal = dmi.adx[dmi.adx.length - 1] ?? 0;
                }
                const adxThreshold = settings.adxThreshold ?? 20;
                if (adxVal > 0 && adxVal < adxThreshold) {
                  console.log(`[OptionsBot] ${sym} ADX GATE: adx=${adxVal.toFixed(1)} < ${adxThreshold} — market is choppy, skipping signal`);
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `ADX gate: ${adxVal.toFixed(1)} < ${adxThreshold} (choppy market)` });
                  continue;
                }
                console.log(`[OptionsBot] ${sym} ADX GATE: adx=${adxVal.toFixed(1)} >= ${adxThreshold} — trending, allowing signal`);
              }

              // ── EMA PRICE CONFIRMATION GATE ──
              // Always uses a HIGHER timeframe EMA to avoid noise from fast signal intervals.
              // 0DTE bots: 15m EMA20. Weekly+: 1h EMA20. Prevents 5m chop from bypassing gate.
              const isBoofMeanReversion = botSignal === 'boof21' || botSignal === 'boof22' || botSignal === 'boof23';
              if (signal !== 'none' && botSignal !== 'test_always_buy' && botSignal !== 'test_always_sell' && !isCryptoFuturesSym && !isBoofMeanReversion) {
                const curClose = candles[candles.length - 1].close;
                const gateInterval = settings.expiryType === '0dte' ? '15m' : '1h';
                let emaVal = 0;
                try {
                  const gateCandles = await fetchCandles(sym, gateInterval, 40, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                  if (gateCandles.length >= 20) {
                    const ema20 = calcEMA(gateCandles.map(c => c.close), 20);
                    emaVal = ema20[ema20.length - 1] ?? 0;
                  }
                } catch (_) {}
                if (!emaVal || emaVal <= 0) {
                  // EMA unavailable (likely Yahoo rate limit) — warn but allow trade through
                  // Blocking on data failure kills good trades; the other gates (ADX, trend filter) still protect
                  console.log(`[OptionsBot] ${sym} EMA GATE: cannot compute ${gateInterval} EMA — passing through (other gates active)`);
                } else {
                  if (signal === 'buy' && curClose < emaVal) {
                    console.log(`[OptionsBot] ${sym} EMA GATE: BUY blocked — close=$${curClose.toFixed(2)} < ${gateInterval} ema=$${emaVal.toFixed(2)}`);
                    results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `EMA gate: BUY blocked, close $${curClose.toFixed(2)} < ${gateInterval} EMA $${emaVal.toFixed(2)}` });
                    continue;
                  }
                  if (signal === 'sell' && curClose > emaVal) {
                    console.log(`[OptionsBot] ${sym} EMA GATE: SELL blocked — close=$${curClose.toFixed(2)} > ${gateInterval} ema=$${emaVal.toFixed(2)}`);
                    results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `EMA gate: SELL blocked, close $${curClose.toFixed(2)} > ${gateInterval} EMA $${emaVal.toFixed(2)}` });
                    continue;
                  }
                  console.log(`[OptionsBot] ${sym} EMA GATE: ${signal.toUpperCase()} confirmed — close=$${curClose.toFixed(2)} ${gateInterval} ema=$${emaVal.toFixed(2)}`);
                }
              }

              console.log(`[OptionsBot] "${bot.name}" | ${sym} | SIGNAL: ${signal} | price=$${price.toFixed(2)} | signal_type=${botSignal} | ${reason}`);
              console.log(`[OptionsBot] ${sym} STEP 1: Signal generated, proceeding to trend filter...`);

              // Trend Filter: EMA 25 on selected timeframe (or EMA 150 on 1m) — 2-candle confirmation required
              const trendFilter = bot.trend_filter as string || 'none';
              console.log(`[OptionsBot] ${sym} trend filter check: trendFilter=${trendFilter}, signal=${signal}`);
              
              if (trendFilter !== 'none' && signal !== 'none') {
                try {
                  // VWAP 1m filter — uses today's 1m candles
                  if (trendFilter === 'vwap_1m') {
                    const vwapCandles: Candle[] = await Promise.race([
                      fetchCandles(sym, '1m', 390, alpacaCreds?.api_key, alpacaCreds?.secret_key),
                      new Promise<Candle[]>((_, reject) => setTimeout(() => reject(new Error('Timeout')), 10000))
                    ]) as Candle[];
                    if (vwapCandles.length < 30) {
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `VWAP: not enough 1m candles (${vwapCandles.length}/30) — waiting for 30min after open` });
                      continue;
                    }
                    const vwap = calcVWAP(vwapCandles);
                    const lastClose = vwapCandles[vwapCandles.length - 1].close;
                    const prevClose = vwapCandles[vwapCandles.length - 2].close;
                    const lastAboveVwap = lastClose >= vwap;
                    const prevAboveVwap = prevClose >= vwap;
                    console.log(`[OptionsBot] ${sym} VWAP 1m: price=${lastClose.toFixed(2)} vwap=${vwap.toFixed(2)} last=${lastAboveVwap?'above':'below'} prev=${prevAboveVwap?'above':'below'}`);
                    if (signal === 'buy' && !(lastAboveVwap && prevAboveVwap)) {
                      console.log(`[OptionsBot] ${sym} BUY blocked — price not confirmed above VWAP`);
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'BUY blocked: price below VWAP' });
                      continue;
                    }
                    if (signal === 'sell' && (lastAboveVwap || prevAboveVwap)) {
                      console.log(`[OptionsBot] ${sym} SELL blocked — price not confirmed below VWAP`);
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'SELL blocked: price above VWAP' });
                      continue;
                    }
                    console.log(`[OptionsBot] ${sym} VWAP filter passed — signal aligned with VWAP`);
                  } else {
                  const is1mEma150 = trendFilter === '1m_ema150';
                  const tfToFetch = is1mEma150 ? '1m' : trendFilter;
                  const emaPeriod = is1mEma150 ? 150 : 25;
                  const minCandles = is1mEma150 ? 160 : 30;
                  const candlesToFetch = is1mEma150 ? 300 : 120;
                  console.log(`[OptionsBot] ${sym} fetching ${tfToFetch} candles for EMA${emaPeriod} trend check...`);
                  const higherTfCandles: Candle[] = await Promise.race([
                    fetchCandles(sym, tfToFetch, candlesToFetch, alpacaCreds?.api_key, alpacaCreds?.secret_key),
                    new Promise<Candle[]>((_, reject) => setTimeout(() => reject(new Error('Timeout')), 10000))
                  ]) as Candle[];
                  console.log(`[OptionsBot] ${sym} fetched ${higherTfCandles.length} ${tfToFetch} candles`);
                  if (higherTfCandles.length < minCandles) {
                    console.log(`[OptionsBot] ${sym} trend filter: not enough candles (${higherTfCandles.length}) — blocking trade`);
                    results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Trend filter: insufficient candles` });
                    continue;
                  }
                  if (higherTfCandles.length >= minCandles) {
                    const higherTfCloses = higherTfCandles.map((c: Candle) => c.close);
                    const higherTfEma = calcEMA(higherTfCloses, emaPeriod);
                    const emaLast = higherTfEma[higherTfEma.length - 1];
                    const emaPrev = higherTfEma[higherTfEma.length - 2];
                    const priceLast = higherTfCloses[higherTfCloses.length - 1];
                    const pricePrev = higherTfCloses[higherTfCloses.length - 2];
                    // 2-candle confirmation: both recent closes must be on same side of EMA
                    const lastAbove = priceLast >= emaLast;
                    const prevAbove = pricePrev >= emaPrev;
                    let higherTfTrend: string;
                    if (lastAbove && prevAbove) higherTfTrend = 'up';
                    else if (!lastAbove && !prevAbove) higherTfTrend = 'down';
                    else higherTfTrend = 'neutral'; // mixed — don't trade
                    const higherTfEmaVal = emaLast;
                    const currentPrice = priceLast;
                    console.log(`[OptionsBot] ${sym} EMA25 ${trendFilter}: price=${priceLast.toFixed(2)} ema=${emaLast.toFixed(2)} trend=${higherTfTrend} (2-bar confirm: last=${lastAbove?'above':'below'} prev=${prevAbove?'above':'below'})`);
                    if (higherTfTrend === 'neutral') {
                      console.log(`[OptionsBot] ${sym} BLOCKED — price crossing EMA25, no confirmed trend`);
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Trend filter: no confirmed trend (crossing EMA25)' });
                      continue;
                    }
                    
                    // Filter signal: Only trade if aligned with higher timeframe
                    if (signal === 'buy' && higherTfTrend === 'down') {
                      console.log(`[OptionsBot] ${sym} BUY blocked - ${trendFilter} trend is DOWN (price ${currentPrice.toFixed(2)} < EMA ${higherTfEmaVal.toFixed(2)})`);
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `BUY blocked: ${trendFilter} trend is DOWN` });
                      continue;
                    }
                    if (signal === 'sell' && higherTfTrend === 'up') {
                      console.log(`[OptionsBot] ${sym} SELL blocked - ${trendFilter} trend is UP (price ${currentPrice.toFixed(2)} > EMA ${higherTfEmaVal.toFixed(2)})`);
                      results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `SELL blocked: ${trendFilter} trend is UP` });
                      continue;
                    }
                    console.log(`[OptionsBot] ${sym} ${signal} approved - ${trendFilter} trend aligned (${higherTfTrend})`);
                  }
                  } // end else (non-VWAP filter)
                } catch (e) {
                  console.log(`[OptionsBot] ${sym} trend filter error — blocking trade to be safe: ${e}`);
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Trend filter error: ${e}` });
                  continue;
                }
              } else {
                console.log(`[OptionsBot] ${sym} no trend filter or no signal, proceeding`);
              }
              
              console.log(`[OptionsBot] ${sym} STEP 2: Trend filter passed, checking signal validity...`);
              if (signal === 'none') {
                console.log(`[OptionsBot] ${sym} signal is none, skipping`);
                // Clear pending signal if trend reversed
                if (bot.last_signal && bot.last_signal !== 'none') {
                  await supabase.from('options_bots').update({ last_signal: null, last_signal_at: null }).eq('id', bot.id);
                }
                results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'no_signal' }); continue;
              }
              console.log(`[OptionsBot] ${sym} signal=${signal}, direction=${settings.tradeDirection}`);
              
              if (signal === 'buy'  && settings.tradeDirection === 'short') { console.log(`[OptionsBot] ${sym} blocked by direction filter (buy vs short)`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Direction filter' }); continue; }
              if (signal === 'sell' && settings.tradeDirection === 'long')  { console.log(`[OptionsBot] ${sym} blocked by direction filter (sell vs long)`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Direction filter' }); continue; }
              console.log(`[OptionsBot] ${sym} STEP 3: Direction filter passed, checking dedup...`);

              // In-memory dedup: prevent parallel batch from trading same symbol twice in one run
              console.log(`[OptionsBot] ${sym} checking tradedThisRun...`);
              if (tradedThisRun.has(sym)) { console.log(`[OptionsBot] ${sym} blocked - already traded this run`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Already traded this symbol in this run' }); continue; }
              tradedThisRun.add(sym);
              console.log(`[OptionsBot] ${sym} STEP 4: Dedup passed, checking 1-min race...`);
              console.log(`[OptionsBot] ${sym} checking 1-minute race condition...`);
              const oneMinuteAgo = new Date(Date.now() - 60 * 1000).toISOString();
              const { data: recent1m } = await supabase.from('options_trades').select('id').eq('bot_id', bot.id).eq('symbol', sym).gte('created_at', oneMinuteAgo).limit(1);
              console.log(`[OptionsBot] ${sym} recent1m check: ${recent1m?.length || 0} trades found`);
              if (recent1m && recent1m.length > 0) { console.log(`[OptionsBot] ${sym} STEP 4.5: Race condition hit, skipping`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Trade within 1 minute' }); continue; }
              console.log(`[OptionsBot] ${sym} STEP 5: Race check passed, checking open positions...`);
              if (recent1m && recent1m.length > 0) { console.log(`[OptionsBot] ${sym} blocked - 1min race condition`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Duplicate trade within 1 minute (race condition)` }); continue; }
              console.log(`[OptionsBot] ${sym} passed 1-minute check`);

              // Block if already in open position on this symbol for this bot
              console.log(`[OptionsBot] ${sym} checking existing open positions...`);
              const { data: existingOpen } = await supabase.from('options_trades').select('id').eq('bot_id', bot.id).eq('symbol', sym).eq('status', 'open').limit(1);
              console.log(`[OptionsBot] ${sym} existingOpen check: ${existingOpen?.length || 0} open trades`);
              if (existingOpen && existingOpen.length > 0) { console.log(`[OptionsBot] ${sym} blocked - already in open position`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Already in open position' }); continue; }
              console.log(`[OptionsBot] ${sym} passed existingOpen check`);

              // Distributed lock: check for any trade inserted in last 5 seconds (concurrent invocation guard)
              console.log(`[OptionsBot] ${sym} checking 5-second lock...`);
              const fiveSecAgo = new Date(Date.now() - 5 * 1000).toISOString();
              const { data: veryRecent } = await supabase.from('options_trades').select('id').eq('bot_id', bot.id).eq('symbol', sym).gte('created_at', fiveSecAgo).limit(1);
              console.log(`[OptionsBot] ${sym} veryRecent check: ${veryRecent?.length || 0} recent trades`);
              if (veryRecent && veryRecent.length > 0) { console.log(`[OptionsBot] ${sym} blocked - 5sec lock`); results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'Concurrent invocation guard (5s lock)' }); continue; }
              console.log(`[OptionsBot] ${sym} passed 5-second check`);

              console.log(`[OptionsBot] ${sym} passed ALL checks, proceeding to entry!`);

              const sigma = calcHistoricalVolatility(candles.map(c => c.close), 20, settings.interval);

              // Determine option type based on signal and bot setting
              let optionType: 'call' | 'put';
              const botOptionType = bot.bot_option_type || 'both';
              if (botOptionType === 'call') {
                optionType = 'call';
              } else if (botOptionType === 'put') {
                optionType = 'put';
              } else {
                // 'both' - follow signal
                optionType = signal === 'buy' ? 'call' : 'put';
              }
              const targetExpiration = getExpirationDate(settings.expiryType);
              const expirationDate = findValidExpiration(targetExpiration);
              // Fetch Tastytrade access token for ALL bots if user has Tastytrade connected
              // This ensures paper trading uses the same real data as live trading
              let tastyAccessToken: string | null = null;
              try {
                const { data: tastyCreds } = await supabase.from('broker_credentials')
                  .select('credentials').eq('user_id', bot.user_id).eq('broker', 'tastytrade').maybeSingle();
                console.log(`[OptionsBot] ${sym} Tastytrade creds check: has_creds=${!!tastyCreds}, has_refresh=${!!tastyCreds?.credentials?.refresh_token}`);
                if (tastyCreds?.credentials?.refresh_token) {
                  const tokenRes = await fetch(`${Deno.env.get('SUPABASE_URL')}/functions/v1/tasty-oauth?action=refresh&user_id=${bot.user_id}`, {
                    headers: {
                      'Authorization': `Bearer ${Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')}`,
                      'apikey': Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
                    }
                  });
                  const tokenJson = await tokenRes.json();
                  console.log(`[OptionsBot] ${sym} Tastytrade token refresh: status=${tokenRes.status}, has_access_token=${!!tokenJson.access_token}, error=${tokenJson.error || 'none'}`);
                  if (tokenJson.access_token) tastyAccessToken = tokenJson.access_token;
                }
              } catch (e) {
                console.log(`[OptionsBot] ${sym} Tastytrade token refresh error: ${e}`);
              }

              // Track per-symbol losses for logging only (no cooldown)
              const symCooldowns: Record<string, any> = (bot.symbol_cooldowns as any) ?? {};
              const symKey = (sym as string).toUpperCase();
              const symState = symCooldowns[symKey];
              if (symState?.losses) {
                console.log(`[OptionsBot] ${sym} has ${symState.losses} recent SL hits (tracking only, no cooldown)`);
              }

              // Spot price priority: Alpaca → Tastytrade → Yahoo
              // Alpaca is first — real-time SIP data, most accurate
              let spotPrice: number | null = null;

              // 1. Try Alpaca first (real-time SIP data, always accurate)
              if (alpacaCreds?.api_key) {
                spotPrice = await fetchAlpacaSpotPrice(sym, alpacaCreds.api_key, alpacaCreds.secret_key);
                if (spotPrice && !sanityCheckSpot(sym, spotPrice, price)) spotPrice = null;
              }

              // 2. Try Tastytrade real-time
              if (!spotPrice && tastyAccessToken) {
                spotPrice = await fetchTastytradeSpotPrice(sym, tastyAccessToken);
              }

              // 3. Yahoo fallback — sanity check required
              if (!spotPrice) {
                try {
                  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1m&range=1d`;
                  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
                  const json = await res.json();
                  const meta = json?.chart?.result?.[0]?.meta;
                  const p = meta?.regularMarketPrice ?? meta?.price;
                  if (p && p > 0 && sanityCheckSpot(sym, p, price)) spotPrice = p;
                } catch (_) {}
              }

              // HARD STOP: if we can't get a sane spot price, don't trade
              if (!spotPrice || spotPrice <= 0) {
                console.log(`[OptionsBot] BLOCKED: Cannot get reliable spot price for ${sym} — skipping trade`);
                results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: 'No reliable spot price' });
                continue;
              }
              console.log(`[OptionsBot] Spot price for ${sym}: $${spotPrice} (broker=${bot.broker})`);
              const strikeInterval = spotPrice > 500 ? 5 : spotPrice > 100 ? 5 : spotPrice > 50 ? 2.5 : 1;
              // Boof 21 + 22 + 23: simple tiered sizing based on signal slack
              // Core (slack >= 0.8): 2x | Expanded: 1x | Reduced (risk off): 0.5x
              const tieredSignal = botSignal === 'boof21' || botSignal === 'boof22' || botSignal === 'boof23';
              const signalSlack = (sigResult as any).slack ?? 0;
              // Boof 23: risk 1% of account equity per trade
              const accountEquity = (bot as any).account_equity ?? 0;
              const boof23RiskAmount = botSignal === 'boof23' && accountEquity > 0
                ? Math.round(accountEquity * 0.01)
                : 0;
              const baseAmount = boof23RiskAmount > 0 ? boof23RiskAmount : (bot.bot_dollar_amount || 200);

              // Calculate daily P&L for risk overlay
              const dailyTrades = bot.trades?.filter((t: any) => {
                const tradeDate = new Date(t.timestamp);
                const today = new Date();
                return tradeDate.toDateString() === today.toDateString();
              }) || [];
              const dailyPnL = dailyTrades.reduce((sum: number, t: any) => sum + (t.pnl || 0), 0);
              const dailyR = dailyPnL / baseAmount; // Convert to R multiples

              // Get symbol historical slack score for additional sizing
              const symbolSlackData = slackMap.get(sym);
              const symbolSlackScore = symbolSlackData?.slack_score ?? 100; // Default to 100 (baseline) if no history
              const hasHistory = (symbolSlackData?.total_trades ?? 0) >= 5;
              
              // Calculate symbol slack multiplier: 
              // - No history or score >= 100: 1.0x (full size - use configured dollar amount)
              // - Score 50-99: 0.5x (reduced)
              // - Score < 50: 0.25x (minimum size, but still trade)
              let symbolSlackMultiplier = 1.0; // Default to full size for new symbols
              let slackStatus = 'normal';
              if (hasHistory) {
                if (symbolSlackScore < 50) {
                  symbolSlackMultiplier = 0.25;
                  slackStatus = 'min-size';
                } else if (symbolSlackScore < 100) {
                  symbolSlackMultiplier = 0.5;
                  slackStatus = 'reduced';
                }
              }
              
              // Risk overlay: scale down if losing or very low confidence
              const isLosingStreak = dailyR < -2.0; // Down more than 2R today
              const isVeryLowSlack = signalSlack < 0.3; // No confidence
              const riskOff = isLosingStreak || isVeryLowSlack;

              let isCore = signalSlack >= 0.8 && !riskOff;
              let signalMultiplier = riskOff ? 0.5 : (isCore ? 2.0 : 1.0);
              let tieredTier = tieredSignal 
                ? (riskOff ? 'reduced' : (isCore ? 'core' : 'expanded')) 
                : null;
              
              // Combine signal and symbol slack multipliers
              const combinedMultiplier = signalMultiplier * symbolSlackMultiplier;
              
              // Discrete sizing based on slack score tiers
              // Low slack (< 80): $100 | Mid slack (80-120): $250 | High slack (> 120): $500
              let slackTierAmount: number;
              if (symbolSlackScore < 80) {
                slackTierAmount = 100;
              } else if (symbolSlackScore <= 120) {
                slackTierAmount = 250;
              } else {
                slackTierAmount = 500;
              }
              const dollarAmount = tieredSignal ? slackTierAmount : (bot.bot_dollar_amount || 250);
              
              console.log(`[OptionsBot] ${bot.name} sizing: signalSlack=${signalSlack.toFixed(2)}, symbolSlack=${symbolSlackScore.toFixed(1)} [${slackStatus}], dailyR=${dailyR.toFixed(2)}, riskOff=${riskOff}, tier=${tieredTier}, combinedMult=${combinedMultiplier.toFixed(2)}x, amount=$${dollarAmount}`);

              // Strike selection:
              // - 0DTE: start 2 strikes ITM (higher delta ~0.65-0.75, moves more with stock)
              // - Weekly/Monthly: start ATM (~0.50 delta)
              // Walk toward OTM until 1-contract cost fits budget.
              // Hard minimum: $1.00/contract. Never buy cheap far-OTM garbage.
              const atmStrike = Math.round(spotPrice / strikeInterval) * strikeInterval;
              const MIN_PREMIUM = 1.00; // $100/contract minimum
              // Max premium based on slack tier: $100 tier=$1.25, $250 tier=$2.75, $500 tier=$5.25 (+$0.25 buffer)
              const MAX_PREMIUM = dollarAmount <= 100 ? 1.25 : dollarAmount <= 250 ? 2.75 : 5.25;
              // High-priced stocks (TSLA, NVDA, etc) need more strikes to find budget-fitting option
              const MAX_STRIKES_WALK = spotPrice > 300 ? 20 : spotPrice > 100 ? 15 : 10;
              const MAX_STRIKE_PCT_FROM_SPOT = spotPrice > 300 ? 0.15 : 0.10; // wider range for expensive stocks
              // For 0DTE, start ITM (negative offset = ITM for calls, positive = ITM for puts)
              const startOffset = expiryType === '0dte' ? -2 : 0;
              const startStrike = optionType === 'call'
                ? atmStrike + startOffset * strikeInterval  // calls: go lower = ITM
                : atmStrike - startOffset * strikeInterval; // puts: go higher = ITM
              let strike = startStrike;
              let premium = 0;
              let cheapestStrike = startStrike;
              let cheapestPremium = 0;

              console.log(`[OptionsBot] ${sym} starting strike selection: spot=$${spotPrice}, budget=$${dollarAmount}, startStrike=$${startStrike}, optionType=${optionType}`);
              
              for (let offset = 0; offset <= MAX_STRIKES_WALK; offset++) {
                const candidateStrike = optionType === 'call'
                  ? startStrike + offset * strikeInterval
                  : startStrike - offset * strikeInterval;
                console.log(`[OptionsBot] ${sym} trying strike $${candidateStrike} (offset=${offset})...`);
                
                const candidatePremium = await fetchRealOptionPrice(sym, candidateStrike, expirationDate, optionType, settings.interval, bot.user_id, expiryType, alpacaCreds?.api_key, alpacaCreds?.secret_key);
                console.log(`[OptionsBot] ${sym} $${candidateStrike} premium=$${candidatePremium?.toFixed(2) ?? 'null'}, tastyAccessToken=${tastyAccessToken ? 'YES' : 'NO'}`);
                
                // If no price found, continue to next strike
                if (!candidatePremium || candidatePremium <= 0) {
                  console.log(`[OptionsBot] ${sym} CONTINUING: No price for $${candidateStrike}, trying next offset`);
                  continue;
                }

                // Track cheapest valid strike seen (above min premium)
                if (candidatePremium >= MIN_PREMIUM && (cheapestPremium === 0 || candidatePremium < cheapestPremium)) {
                  cheapestStrike = candidateStrike;
                  cheapestPremium = candidatePremium;
                }

                // Too cheap — stop walking further OTM (premiums only get cheaper from here)
                if (candidatePremium < MIN_PREMIUM) {
                  console.log(`[OptionsBot] $${candidateStrike} premium $${candidatePremium.toFixed(2)} below $${MIN_PREMIUM} min — stopping walk`);
                  break;
                }

                // Sanity check: strike must be within 10% of spot price
                const pctFromSpot = Math.abs(candidateStrike - spotPrice) / spotPrice;
                if (pctFromSpot > MAX_STRIKE_PCT_FROM_SPOT) {
                  console.log(`[OptionsBot] BLOCKED deep OTM: $${candidateStrike} is ${(pctFromSpot*100).toFixed(1)}% from spot $${spotPrice.toFixed(2)} — stopping walk`);
                  break;
                }

                // Track closest-to-budget strike (highest premium within budget + $50 buffer)
                if (candidatePremium * 100 <= dollarAmount + 50) {
                  if (!premium || candidatePremium > premium) {
                    strike = candidateStrike;
                    premium = candidatePremium;
                  }
                  break;
                }

                console.log(`[OptionsBot] $${candidateStrike} @ $${candidatePremium.toFixed(2)}/contract ($${(candidatePremium*100).toFixed(0)}) exceeds budget $${dollarAmount} — trying next strike`);
              }

              // If nothing fit budget, skip trade — don't buy over-budget
              if ((!premium || premium < MIN_PREMIUM) && cheapestPremium >= MIN_PREMIUM) {
                console.log(`[OptionsBot] ${sym} BLOCKED: cheapest option $${cheapestStrike} @ $${cheapestPremium.toFixed(2)}/contract ($${(cheapestPremium*100).toFixed(0)}) exceeds budget $${dollarAmount} — skipping trade. Increase budget or trade cheaper symbols.`);
                results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `${sym} cheapest option $${(cheapestPremium*100).toFixed(0)} exceeds budget $${dollarAmount} — increase bot dollar amount` });
                continue;
              }

              // HARD STOP — never trade below $1.00 premium under any circumstance
              console.log(`[OptionsBot] ${sym} strike selection complete: final strike=$${strike}, final premium=$${premium?.toFixed(2) ?? '0'}`);
              
              if (!premium || premium < MIN_PREMIUM) {
                console.log(`[OptionsBot] BLOCKED: ${sym} premium $${premium?.toFixed(2) ?? '0'} < $${MIN_PREMIUM} — refusing to trade`);
                continue;
              }

              // Hard cap: never spend more than dollarAmount — floor division then verify
              const contracts = Math.max(1, Math.floor(dollarAmount / (premium * 100)));
              const totalCost = contracts * premium * 100;
              if (totalCost > dollarAmount) {
                console.log(`[OptionsBot] BLOCKED: ${sym} 1 contract @ $${(premium*100).toFixed(0)} exceeds budget $${dollarAmount} — skipping`);
                results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `${sym} cheapest option $${(premium*100).toFixed(0)} exceeds budget $${dollarAmount} — increase bot dollar amount` });
                continue;
              }
              console.log(`[OptionsBot] Selected: ${sym} ${optionType} $${strike} @ $${premium.toFixed(2)}/contract x${contracts} = $${totalCost.toFixed(2)} (budget=$${dollarAmount} spot=$${spotPrice.toFixed(2)})`);

              // Check max daily trades limit
              const maxDailyTrades = bot.max_daily_trades;
              if (maxDailyTrades && maxDailyTrades > 0) {
                const todayStr = new Date().toISOString().slice(0, 10);
                const lastResetDate = bot.daily_reset_date ? new Date(bot.daily_reset_date).toISOString().slice(0, 10) : null;
                // Reset count if new day
                let currentDailyCount = (lastResetDate === todayStr) ? (bot.daily_trade_count || 0) : 0;
                if (currentDailyCount >= maxDailyTrades) {
                  console.log(`[OptionsBot] ${sym} BLOCKED: daily trade limit reached ${currentDailyCount}/${maxDailyTrades} — skipping trade`);
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Daily trade limit reached ${currentDailyCount}/${maxDailyTrades}` });
                  continue;
                }
              }

              let tradeStatus = 'open';
              let orderId = null;
              let brokerError = null;

              // Live trading
              if (bot.broker === 'tastytrade') {
                console.log(`[OptionsBot] Placing Tastytrade order: ${contracts} contracts of ${sym} ${optionType}`);
                const tastyResult = await placeTastytradeOptionOrder(
                  supabase, bot.user_id, sym, expirationDate, optionType, strike, 'Buy to Open', contracts
                );
                if (tastyResult.success) {
                  tradeStatus = 'open';
                  orderId = tastyResult.orderId;
                  if (tastyResult.fillPrice && tastyResult.fillPrice > 0) {
                    premium = tastyResult.fillPrice;
                    console.log(`[OptionsBot] Tastytrade real fill price: $${premium.toFixed(2)}/contract`);
                  } else {
                    console.log(`[OptionsBot] Tastytrade fill pending, using estimate: $${premium.toFixed(2)}/contract`);
                  }
                } else {
                  tradeStatus = 'failed';
                  brokerError = tastyResult.error;
                  console.error(`[OptionsBot] Tastytrade order failed: ${brokerError}`);
                }
              } else if (bot.broker === 'alpaca' || bot.broker === 'alpaca_paper') {
                console.log(`[OptionsBot] Placing Alpaca order: ${contracts} contracts of ${sym} ${optionType}`);
                const alpacaResult = await placeAlpacaOptionOrder(
                  supabase, bot.user_id, sym, expirationDate, optionType, strike, 'buy', contracts, bot.broker === 'alpaca_paper', premium
                );
                if (alpacaResult.success) {
                  tradeStatus = alpacaResult.status === 'filled' ? 'filled' : 'pending';
                  orderId = alpacaResult.orderId;
                  if (alpacaResult.fillPrice && alpacaResult.fillPrice > 0) {
                    premium = alpacaResult.fillPrice;
                    console.log(`[OptionsBot] Alpaca real fill price: $${premium.toFixed(2)}/contract`);
                  }
                } else {
                  tradeStatus = 'failed';
                  brokerError = alpacaResult.error;
                  console.error(`[OptionsBot] Alpaca order failed: ${brokerError}`);
                }
              } else {
                // Paper trading: check balance before entering
                const { data: botRow } = await supabase.from('options_bots').select('paper_balance').eq('id', bot.id).single();
                const currentBalance = Number(botRow?.paper_balance ?? 100000);
                if (currentBalance < totalCost) {
                  console.log(`[OptionsBot] SKIP: insufficient paper balance $${currentBalance.toFixed(2)} for ${sym} trade costing $${totalCost.toFixed(2)}`);
                  results.push({ bot_id: bot.id, symbol: sym, status: 'skipped', reason: `Insufficient balance ($${currentBalance.toFixed(2)} < $${totalCost.toFixed(2)})` });
                  continue;
                }
                await supabase.from('options_bots').update({ paper_balance: currentBalance - totalCost }).eq('id', bot.id);
              }

              console.log(`[OptionsBot] Inserting trade: ${sym} ${optionType} strike=${strike} premium=$${premium.toFixed(2)} contracts=${contracts} total=$${totalCost.toFixed(2)} status=${tradeStatus}`);
              const tradeNow = new Date();
              const { error: insertErr } = await supabase.from('options_trades').insert({
                user_id: bot.user_id, bot_id: bot.id, symbol: sym,
                option_type: optionType, strike, expiration_date: expirationDate,
                contracts, premium_per_contract: premium, total_cost: totalCost,
                entry_price: premium, status: tradeStatus, signal, reason,
                broker: bot.broker || 'paper',
                broker_error: brokerError,
                created_at: tradeNow.toISOString(),
                // Use ATR-based TP/SL for boof22; dynamic from boof15 if available; else bot defaults
                take_profit_pct: botSignal === 'boof22' && (sigResult as any).takeProfit
                  ? (sigResult as any).takeProfit
                  : sigResult.stopLoss && sigResult.takeProfit
                    ? ((sigResult.takeProfit - price) / price) * 100
                    : (Number(bot.take_profit_pct) || 35),
                stop_loss_pct: botSignal === 'boof22' && (sigResult as any).stopLoss
                  ? (sigResult as any).stopLoss
                  : sigResult.stopLoss && sigResult.takeProfit
                    ? ((sigResult.stopLoss - price) / price) * 100
                    : (Number(bot.stop_loss_pct) || -25),
                // ML features for Boof 4.0 training
                mode: (sigResult as any).mode || ((sigResult as any).reason?.toUpperCase().includes('CHOP') ? 'chop' : 'trend'),
                entry_regime: (sigResult as any).regime,
                entry_rsi: (sigResult as any).rsi,
                entry_slope: (sigResult as any).slope,
                entry_atr: (sigResult as any).atr,
                entry_spot: price,
                entry_ema: sigResult.ema,
                entry_slack: (sigResult as any).slack ?? null,
                hour_of_day: tradeNow.getHours(),
                day_of_week: tradeNow.getDay(),
                signal_version: botSignal,
              });
              if (insertErr) console.error(`[OptionsBot] INSERT FAILED for ${sym}:`, insertErr.message);

              // Increment daily trade count on successful trade
              if (!insertErr && (tradeStatus === 'open' || tradeStatus === 'filled' || tradeStatus === 'pending')) {
                const newDailyCount = (bot.daily_trade_count || 0) + 1;
                await supabase.from('options_bots').update({ daily_trade_count: newDailyCount }).eq('id', bot.id);
                bot.daily_trade_count = newDailyCount;
                console.log(`[OptionsBot] "${bot.name}" - Daily trade count: ${newDailyCount}${bot.max_daily_trades ? `/${bot.max_daily_trades}` : ''}`);
              }

              // Persist last tier and slack for B21/B22/B23 so UI shows signal quality
              if (botSignal === 'boof21' || botSignal === 'boof22' || botSignal === 'boof23') {
                await supabase.from('options_bots').update({ last_tier: tieredTier, last_slack: signalSlack }).eq('id', bot.id);
              }

              // Broadcast trade to all sibling bots with the same signal type
              if (!insertErr && (botSignal === 'boof21' || botSignal === 'boof22' || botSignal === 'boof23')) {
                const siblingBots = bots.filter((b: any) => b.bot_signal === botSignal && b.id !== bot.id);
                for (const sibling of siblingBots) {
                  // Skip if sibling already has open position on this symbol
                  const { data: sibOpen } = await supabase.from('options_trades').select('id').eq('bot_id', sibling.id).eq('symbol', sym).eq('status', 'open').limit(1);
                  if (sibOpen && sibOpen.length > 0) { console.log(`[OptionsBot] Broadcast skip ${sibling.name} ${sym} - already open`); continue; }
                  // Check budget
                  const sibBalance = Number(sibling.paper_balance ?? sibling.budget ?? 0);
                  if (sibling.broker === 'paper' && sibBalance < totalCost) { console.log(`[OptionsBot] Broadcast skip ${sibling.name} ${sym} - insufficient balance`); continue; }
                  const sibNow = new Date();
                  const { error: sibErr } = await supabase.from('options_trades').insert({
                    user_id: sibling.user_id, bot_id: sibling.id, symbol: sym,
                    option_type: optionType, strike, expiration_date: expirationDate,
                    contracts, premium_per_contract: premium, total_cost: totalCost,
                    entry_price: premium, status: tradeStatus, signal, reason,
                    broker: sibling.broker || 'paper',
                    created_at: sibNow.toISOString(),
                    take_profit_pct: Number(sibling.take_profit_pct) || Number(bot.take_profit_pct) || 35,
                    stop_loss_pct: Number(sibling.stop_loss_pct) || Number(bot.stop_loss_pct) || -25,
                    entry_atr: (sigResult as any).atr,
                    entry_spot: price,
                    signal_version: botSignal,
                    hour_of_day: sibNow.getHours(),
                    day_of_week: sibNow.getDay(),
                  });
                  if (sibErr) console.error(`[OptionsBot] Broadcast INSERT FAILED ${sibling.name} ${sym}:`, sibErr.message);
                  else {
                    console.log(`[OptionsBot] Broadcast trade to ${sibling.name} | ${sym} ${optionType} strike=${strike} premium=$${premium.toFixed(2)}`);
                    if (sibling.broker === 'paper') await supabase.from('options_bots').update({ paper_balance: sibBalance - totalCost }).eq('id', sibling.id);
                    results.push({ bot_id: sibling.id, status: tradeStatus, symbol: sym, option_type: optionType, strike, premium: premium.toFixed(2), total_cost: totalCost.toFixed(2), signal, reason: `broadcast from ${bot.name}` });
                  }
                }
              }

              results.push({ bot_id: bot.id, status: tradeStatus, symbol: sym, option_type: optionType, strike, expiration_date: expirationDate, contracts, premium: premium.toFixed(2), total_cost: totalCost.toFixed(2), budget: dollarAmount, order_id: orderId, broker_error: brokerError, sigma: (sigma * 100).toFixed(1) + '%', signal, reason });

          } catch (err) {
            results.push({ bot_id: bot.id, symbol: sym, status: 'error', error: String(err) });
          }
        }
      } catch (err) {
        results.push({ bot_id: bot.id, status: 'error', error: String(err) });
      }
      
      // Update last_run_at after successful processing
      await supabase.from('options_bots').update({ last_run_at: now.toISOString() }).eq('id', bot.id);
    }

    console.log(`Processed ${results.length} results:`, results);

    return new Response(JSON.stringify({ processed: results.length, results }), {
      status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
});
