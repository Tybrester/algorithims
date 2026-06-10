"use strict";
// =========================================================
// BOOF 25.0 — Mean Reversion Strategy
// Detects overbought/oversold conditions for reversal entries
// Best for choppy, range-bound markets
// =========================================================
Object.defineProperty(exports, "__esModule", { value: true });
exports.getBoof25Signal = getBoof25Signal;
// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const CFG = {
    RSI_LEN: 14,
    BB_LEN: 20,
    BB_MULT: 2.0,
    ATR_LEN: 14,
    VOL_LEN: 50,
    RSI_OVERSOLD: 30,
    RSI_OVERBOUGHT: 70,
    RSI_EXTREME_LOW: 20,
    RSI_EXTREME_HIGH: 80,
    MIN_BARS: 50,
    ATR_TP_MULT: 3.0,
    ATR_SL_MULT: 1.5,
    REVERSAL_LOOKBACK: 3, // Bars to confirm reversal
};
// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────
function computeATR(candles, period) {
    const atr = new Array(candles.length).fill(0);
    for (let i = 1; i < candles.length; i++) {
        const tr = Math.max(candles[i].high - candles[i].low, Math.abs(candles[i].high - candles[i - 1].close), Math.abs(candles[i].low - candles[i - 1].close));
        atr[i] = i < period
            ? tr
            : atr[i - 1] * (period - 1) / period + tr / period;
    }
    return atr;
}
function computeRSI(candles, period) {
    const rsi = new Array(candles.length).fill(50);
    let avgGain = 0, avgLoss = 0;
    for (let i = 1; i < candles.length; i++) {
        const change = candles[i].close - candles[i - 1].close;
        const gain = change > 0 ? change : 0;
        const loss = change < 0 ? -change : 0;
        if (i <= period) {
            avgGain += gain / period;
            avgLoss += loss / period;
        }
        else {
            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;
        }
        if (i >= period) {
            const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
            rsi[i] = avgLoss === 0 ? 100 : 100 - (100 / (1 + rs));
        }
    }
    return rsi;
}
function computeBollingerBands(candles, period, mult) {
    const middle = new Array(candles.length).fill(0);
    const upper = new Array(candles.length).fill(0);
    const lower = new Array(candles.length).fill(0);
    for (let i = period - 1; i < candles.length; i++) {
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += candles[i - j].close;
        }
        const sma = sum / period;
        middle[i] = sma;
        let sqSum = 0;
        for (let j = 0; j < period; j++) {
            sqSum += Math.pow(candles[i - j].close - sma, 2);
        }
        const std = Math.sqrt(sqSum / period);
        upper[i] = sma + mult * std;
        lower[i] = sma - mult * std;
    }
    return { middle, upper, lower };
}
function computeVolSMA(candles, period) {
    const sma = new Array(candles.length).fill(0);
    for (let i = period - 1; i < candles.length; i++) {
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += candles[i - j].volume || 0;
        }
        sma[i] = sum / period;
    }
    return sma;
}
function isBullishReversal(candles, idx, lookback) {
    if (idx < lookback)
        return false;
    const curr = candles[idx];
    const prev = candles[idx - 1];
    // Hammer or bullish engulfing pattern
    const body = Math.abs(curr.close - curr.open);
    const lowerWick = Math.min(curr.open, curr.close) - curr.low;
    const upperWick = curr.high - Math.max(curr.open, curr.close);
    // Hammer-like: long lower wick, small body
    const isHammer = lowerWick > body * 2 && upperWick < body;
    // Bullish engulfing
    const isEngulfing = curr.close > prev.open && curr.open < prev.close &&
        curr.close > curr.open && prev.close < prev.open;
    return isHammer || isEngulfing;
}
function isBearishReversal(candles, idx, lookback) {
    if (idx < lookback)
        return false;
    const curr = candles[idx];
    const prev = candles[idx - 1];
    // Shooting star or bearish engulfing pattern
    const body = Math.abs(curr.close - curr.open);
    const upperWick = curr.high - Math.max(curr.open, curr.close);
    const lowerWick = Math.min(curr.open, curr.close) - curr.low;
    // Shooting star: long upper wick, small body
    const isShootingStar = upperWick > body * 2 && lowerWick < body;
    // Bearish engulfing
    const isEngulfing = curr.close < prev.open && curr.open > prev.close &&
        curr.close < curr.open && prev.close > prev.open;
    return isShootingStar || isEngulfing;
}
// ─────────────────────────────────────────────
// MAIN SIGNAL FUNCTION
// ─────────────────────────────────────────────
function getBoof25Signal(candles, symbol, defaultTpPct, defaultSlPct) {
    const len = candles.length;
    if (len < CFG.MIN_BARS) {
        return {
            signal: 'none',
            price: candles[len - 1]?.close || 0,
            reason: 'Insufficient data',
            direction: 'none',
            rsi: 50,
            bbPosition: 0.5,
            deviation: 0,
            atr: 0,
            tpPct: defaultTpPct || 15,
            slPct: defaultSlPct || -8,
            mode: 'chop',
            strength: 0,
        };
    }
    const i = len - 1;
    const price = candles[i].close;
    // Compute indicators
    const atr = computeATR(candles, CFG.ATR_LEN);
    const rsi = computeRSI(candles, CFG.RSI_LEN);
    const bb = computeBollingerBands(candles, CFG.BB_LEN, CFG.BB_MULT);
    const volSMA = computeVolSMA(candles, CFG.VOL_LEN);
    const currATR = atr[i];
    const currRSI = rsi[i];
    const prevRSI = rsi[i - 1];
    const currVol = candles[i].volume || 0;
    const avgVol = volSMA[i];
    const rVol = avgVol > 0 ? currVol / avgVol : 1;
    // Bollinger Band position (0 = lower, 1 = upper)
    const bbRange = bb.upper[i] - bb.lower[i];
    const bbPosition = bbRange > 0
        ? (price - bb.lower[i]) / bbRange
        : 0.5;
    // Standard deviations from middle band
    const bbMid = bb.middle[i];
    const bbStd = (bb.upper[i] - bb.lower[i]) / (2 * CFG.BB_MULT);
    const deviation = bbStd > 0 ? (price - bbMid) / bbStd : 0;
    // Determine if we're in chop (price between Bollinger bands, RSI mid-range)
    const isChop = bbPosition > 0.2 && bbPosition < 0.8 && currRSI > 40 && currRSI < 60;
    let signal = 'none';
    let reason = '';
    let strength = 0;
    // ─────────────────────────────────────────────
    // MEAN REVERSION LOGIC
    // ─────────────────────────────────────────────
    // BUY: Oversold conditions
    const oversold = currRSI <= CFG.RSI_OVERSOLD;
    const extremeOversold = currRSI <= CFG.RSI_EXTREME_LOW;
    const atLowerBand = bbPosition <= 0.1 || deviation <= -2;
    const bullishRev = isBullishReversal(candles, i, CFG.REVERSAL_LOOKBACK);
    const rsiTurningUp = prevRSI < currRSI;
    if ((oversold || extremeOversold) && (atLowerBand || bullishRev)) {
        signal = 'buy';
        strength = extremeOversold ? 90 : oversold ? 75 : 60;
        strength += bullishRev ? 10 : 0;
        strength += rsiTurningUp ? 10 : 0;
        strength = Math.min(strength, 100);
        reason = `Mean reversion LONG: RSI=${currRSI.toFixed(1)}`;
        if (extremeOversold)
            reason += ' (extreme oversold)';
        else if (oversold)
            reason += ' (oversold)';
        if (atLowerBand)
            reason += ', at lower BB';
        if (bullishRev)
            reason += ', bullish reversal';
        if (rsiTurningUp)
            reason += ', RSI turning up';
    }
    // SELL: Overbought conditions
    const overbought = currRSI >= CFG.RSI_OVERBOUGHT;
    const extremeOverbought = currRSI >= CFG.RSI_EXTREME_HIGH;
    const atUpperBand = bbPosition >= 0.9 || deviation >= 2;
    const bearishRev = isBearishReversal(candles, i, CFG.REVERSAL_LOOKBACK);
    const rsiTurningDown = prevRSI > currRSI;
    if ((overbought || extremeOverbought) && (atUpperBand || bearishRev)) {
        signal = 'sell';
        strength = extremeOverbought ? 90 : overbought ? 75 : 60;
        strength += bearishRev ? 10 : 0;
        strength += rsiTurningDown ? 10 : 0;
        strength = Math.min(strength, 100);
        reason = `Mean reversion SHORT: RSI=${currRSI.toFixed(1)}`;
        if (extremeOverbought)
            reason += ' (extreme overbought)';
        else if (overbought)
            reason += ' (overbought)';
        if (atUpperBand)
            reason += ', at upper BB';
        if (bearishRev)
            reason += ', bearish reversal';
        if (rsiTurningDown)
            reason += ', RSI turning down';
    }
    // Filter: Require minimum strength
    if (strength < 60) {
        signal = 'none';
        reason = 'Signal strength too low';
    }
    // Volume confirmation (optional boost)
    if (rVol > 1.2 && signal !== 'none') {
        strength = Math.min(strength + 5, 100);
        reason += ', vol confirm';
    }
    // Calculate TP/SL based on ATR
    const tpPct = defaultTpPct || Math.round(CFG.ATR_TP_MULT * currATR / price * 100);
    const slPct = defaultSlPct || -Math.round(CFG.ATR_SL_MULT * currATR / price * 100);
    return {
        signal,
        price,
        reason,
        direction: signal === 'buy' ? 'LONG' : signal === 'sell' ? 'SHORT' : 'none',
        rsi: currRSI,
        bbPosition,
        deviation,
        atr: currATR,
        tpPct,
        slPct,
        mode: isChop ? 'chop' : 'trend',
        strength,
    };
}
