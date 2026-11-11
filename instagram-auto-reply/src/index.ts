import { InstagramClient, type MetaClient } from './meta';
import { D1Storage, type Storage } from './storage';

interface Env { DB: D1Database; TOKENS: KVNamespace; APP_SECRET: string; VERIFY_TOKEN: string; IG_TOKEN: string; KEYWORDS: string; DM_TEXT: string; PUBLIC_REPLY?: string }
interface Payload { object?: string; entry?: { id?: string; changes?: { field?: string; value?: { id?: string; text?: string; from?: { id?: string }; parent_id?: unknown } }[] }[] }
const encoder = new TextEncoder();

async function equal(a: string, b: string): Promise<boolean> {
  const key = await crypto.subtle.importKey('raw', encoder.encode('comparison'), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
  const digest = await crypto.subtle.sign('HMAC', key, encoder.encode(a));
  return crypto.subtle.verify('HMAC', key, digest, encoder.encode(b));
}
export async function validSignature(secret: string, body: string, signature: string | null): Promise<boolean> {
  if (!signature || !/^sha256=[0-9a-f]{64}$/i.test(signature)) return false;
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const hash = await crypto.subtle.sign('HMAC', key, encoder.encode(body));
  const hex = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
  return equal(`sha256=${hex}`, signature.toLowerCase());
}
function normalize(value: string): string {
  return value.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim().replace(/\s+/g, ' ');
}
export function matches(text: string, keywords: string[]): boolean {
  const words = ` ${normalize(text)} `;
  return keywords.some(keyword => { const normalized = normalize(keyword); return normalized.length > 0 && words.includes(` ${normalized} `); });
}
export async function handle(request: Request, config: Pick<Env, 'APP_SECRET' | 'VERIFY_TOKEN' | 'KEYWORDS' | 'DM_TEXT' | 'PUBLIC_REPLY'>, storage: Storage, meta: MetaClient): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname !== '/webhook') return new Response('Not Found', { status: 404 });
  if (request.method === 'GET') {
    const token = url.searchParams.get('hub.verify_token');
    if (url.searchParams.get('hub.mode') === 'subscribe' && token !== null && await equal(token, config.VERIFY_TOKEN) && url.searchParams.has('hub.challenge')) return new Response(url.searchParams.get('hub.challenge'));
    return new Response('Forbidden', { status: 403 });
  }
  if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405 });
  const body = await request.text();
  if (!await validSignature(config.APP_SECRET, body, request.headers.get('X-Hub-Signature-256'))) return new Response('Unauthorized', { status: 401 });
  let payload: Payload;
  try { payload = JSON.parse(body) as Payload; } catch { return new Response('Bad Request', { status: 400 }); }
  if (payload?.object === 'instagram' && Array.isArray(payload.entry)) {
    for (const entry of payload.entry) {
      if (typeof entry?.id !== 'string' || !Array.isArray(entry.changes)) continue;
      for (const change of entry.changes) {
        const value = change?.value;
        if (change?.field !== 'comments' || typeof value?.id !== 'string' || typeof value.text !== 'string' || typeof value.from?.id !== 'string' || value.from.id === entry.id || value.parent_id != null || !matches(value.text, config.KEYWORDS.split(','))) continue;
        try {
          if (!await storage.claim({ comment_id: value.id, igsid: value.from.id, created_at: Date.now() })) continue;
          await meta.privateReply(entry.id, value.id, config.DM_TEXT);
          console.log(JSON.stringify({ event: 'private_reply_sent', comment_id: value.id }));
          if (config.PUBLIC_REPLY) await meta.publicReply(value.id, config.PUBLIC_REPLY);
        } catch {
          console.error(JSON.stringify({ event: 'reply_failed', comment_id: value.id }));
        }
      }
    }
  }
  return new Response('EVENT_RECEIVED');
}
export async function cleanup(storage: Storage, now = Date.now()): Promise<number> { return storage.cleanup(now - 90 * 24 * 60 * 60 * 1000); }
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const token = await env.TOKENS.get('instagram_token') ?? env.IG_TOKEN;
    return handle(request, env, new D1Storage(env.DB), new InstagramClient(token));
  },
  async scheduled(_event: ScheduledController, env: Env): Promise<void> {
    try { const count = await cleanup(new D1Storage(env.DB)); console.log(JSON.stringify({ event: 'cleanup', deleted: count })); } catch { console.error(JSON.stringify({ event: 'cleanup_failed' })); }
    try { const current = await env.TOKENS.get('instagram_token') ?? env.IG_TOKEN; const refreshed = await new InstagramClient(current).refreshToken(); await env.TOKENS.put('instagram_token', refreshed); console.log(JSON.stringify({ event: 'token_refreshed' })); } catch { console.error(JSON.stringify({ event: 'token_refresh_failed' })); }
  },
} satisfies ExportedHandler<Env>;
