import type { Env, Mode } from './types';
export class HttpError extends Error { constructor(message: string, public status = 400) { super(message) } }
export function assert(condition: unknown, message: string, status = 400): asserts condition { if (!condition) throw new HttpError(message, status) }
export const now = () => new Date().toISOString();
export const seconds = (a: any, b: any) => a && b ? Math.round((Date.parse(b) - Date.parse(a)) / 1000 * 1000) / 1000 : null;
export const token = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');
export async function digest(input: string | Uint8Array, algorithm = 'SHA-256') {
  const bytes = typeof input === 'string' ? new TextEncoder().encode(input) : input;
  return Array.from(new Uint8Array(await crypto.subtle.digest(algorithm, bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
export async function uuid5(value: string) {
  const ns = Uint8Array.from('6ba7b8119dad11d180b400c04fd430c8'.match(/../g)!, x => parseInt(x, 16));
  const text = new TextEncoder().encode(value), bytes = new Uint8Array(ns.length + text.length);
  bytes.set(ns); bytes.set(text, ns.length);
  const d = new Uint8Array(await crypto.subtle.digest('SHA-1', bytes)); d[6] = d[6] & 15 | 80; d[8] = d[8] & 63 | 128;
  const h = Array.from(d.slice(0, 16), x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
export function modeOf(env: Env): Mode { const mode = env.DCE_MODE || 'demo'; assert(['demo','pilot','formal'].includes(mode), 'DCE_MODE配置错误', 503); return mode as Mode }
export function cookie(request: Request, name: string) { return (request.headers.get('Cookie') || '').split(';').map(s => s.trim()).find(s => s.startsWith(name + '='))?.slice(name.length + 1) }
export function cookieHeader(request: Request, name: string, value: string, age: number) { return `${name}=${value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${age}${new URL(request.url).protocol === 'https:' ? '; Secure' : ''}` }
export function headers(type: string, request?: Request) {
  const h = new Headers({ 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" });
  if (request && new URL(request.url).protocol === 'https:') h.set('Strict-Transport-Security', 'max-age=31536000');
  return h;
}
export function json(value: unknown, status = 200, setCookie?: string) { const h = headers('application/json; charset=utf-8'); if (setCookie) h.set('Set-Cookie', setCookie); return new Response(JSON.stringify(value), { status, headers: h }) }
export function binary(data: Uint8Array | string, type: string, filename: string) { const h = headers(type); h.set('Content-Disposition', `attachment; filename="${filename}"`); return new Response(data, { headers: h }) }
export async function body(request: Request, limit = 65536): Promise<Record<string, any>> {
  assert(request.headers.get('Content-Type')?.split(';')[0] === 'application/json', '请求须为JSON');
  const declared = Number(request.headers.get('Content-Length') || 0); assert(declared <= limit, '请求超过大小限制', 413);
  assert(request.body, '请求正文缺失'); const reader = request.body.getReader(); let size = 0; const chunks: Uint8Array[] = [];
  while (true) { const {value,done} = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) { await reader.cancel(); throw new HttpError('请求超过大小限制', 413) } chunks.push(value) }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.length }
  try { const d = JSON.parse(new TextDecoder('utf-8', {fatal:true,ignoreBOM:false}).decode(bytes)); assert(d && typeof d === 'object' && !Array.isArray(d), '请求须为JSON对象'); return d } catch (e) { if (e instanceof HttpError) throw e; throw new HttpError('JSON或UTF-8格式错误') }
}
export function verifyOrigin(request: Request) { const origin = request.headers.get('Origin'); assert(!origin || origin === new URL(request.url).origin, '请求来源校验失败', 403) }
export function equal(a: string, b: string) { if (a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i); return d === 0 }
export function shuffle<T>(a: T[]) { const out = [...a]; for (let i = out.length - 1; i > 0; i--) { const j = randomInt(i + 1); [out[i],out[j]] = [out[j],out[i]] } return out }
export function randomInt(n: number) { const ceiling = Math.floor(0x100000000 / n) * n; let x: number; do { x = crypto.getRandomValues(new Uint32Array(1))[0] } while (x >= ceiling); return x % n }
export function timestamp(v: any, required = false) { assert(!required || v, '缺少时间戳'); if (v) assert(typeof v === 'string' && /^\d{4}-\d\d-\d\dT/.test(v) && Number.isFinite(Date.parse(v)), '时间戳不合法') }
