// Boof 15.0 stub — original file was deleted, preserved for import compatibility
export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number; }
export interface Boof150Result { signal: 'buy' | 'sell' | 'none'; price: number; reason: string; ev: number; score: number; positionSize: number; }
export function classifyRegime(candles: Candle[]): string { return 'UNKNOWN'; }
export function generateSignalBoof150(candles: Candle[], symbol: string, regime: string, useKelly = false, tradeDirection = 'both'): Boof150Result {
  return { signal: 'none', price: candles[candles.length - 1]?.close ?? 0, reason: 'boof150 deprecated', ev: 0, score: 0, positionSize: 0 };
}
