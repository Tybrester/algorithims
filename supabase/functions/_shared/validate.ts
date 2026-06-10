// Shared input validation utilities for all edge functions

export const MAX_BODY_BYTES = 64 * 1024; // 64KB max payload

/** Read body with size limit — throws if oversized */
export async function readBodyWithLimit(req: Request): Promise<unknown> {
  const contentLength = Number(req.headers.get('content-length') || 0);
  if (contentLength > MAX_BODY_BYTES) {
    throw new Error('PAYLOAD_TOO_LARGE');
  }
  const raw = await req.text();
  if (raw.length > MAX_BODY_BYTES) throw new Error('PAYLOAD_TOO_LARGE');
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error('INVALID_JSON');
  }
}

/** Strip string to max length and remove control chars */
export function sanitizeString(val: unknown, maxLen = 256): string {
  if (typeof val !== 'string') return '';
  return val.replace(/[\x00-\x1F\x7F]/g, '').trim().slice(0, maxLen);
}

/** Validate a UUID format */
export function isValidUUID(val: unknown): boolean {
  return typeof val === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(val);
}

/** Validate a stock ticker symbol (1-10 uppercase letters/numbers) */
export function isValidSymbol(val: unknown): boolean {
  return typeof val === 'string' && /^[A-Z0-9./:!-]{1,20}$/.test(val.toUpperCase());
}

/** Validate a numeric value within range */
export function isValidNumber(val: unknown, min: number, max: number): boolean {
  const n = Number(val);
  return !isNaN(n) && isFinite(n) && n >= min && n <= max;
}

/** Response helpers */
export const json400 = (msg: string, cors: Record<string, string>) =>
  new Response(JSON.stringify({ error: msg }), { status: 400, headers: { ...cors, 'Content-Type': 'application/json' } });

export const json413 = (cors: Record<string, string>) =>
  new Response(JSON.stringify({ error: 'Payload too large' }), { status: 413, headers: { ...cors, 'Content-Type': 'application/json' } });

export const json422 = (cors: Record<string, string>) =>
  new Response(JSON.stringify({ error: 'Invalid JSON payload' }), { status: 422, headers: { ...cors, 'Content-Type': 'application/json' } });
