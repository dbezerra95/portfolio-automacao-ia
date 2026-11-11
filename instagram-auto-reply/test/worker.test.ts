import { describe, expect, it, vi } from 'vitest';
import { cleanup, handle, matches } from '../src/index';
import { MemoryStorage } from '../src/storage';
import type { MetaClient } from '../src/meta';

const config = { APP_SECRET: 'test-secret', VERIFY_TOKEN: 'test-verify', KEYWORDS: 'informação', DM_TEXT: 'Resposta fictícia', PUBLIC_REPLY: '' };
function fake(): MetaClient { return { privateReply: vi.fn().mockResolvedValue(undefined), publicReply: vi.fn().mockResolvedValue(undefined), refreshToken: vi.fn().mockResolvedValue('refreshed') }; }
const payload = (text = 'Quero INFORMAÇÃO!') => JSON.stringify({ object: 'instagram', entry: [{ id: 'account-fictional', changes: [{ field: 'comments', value: { id: 'comment-fictional', text, from: { id: 'user-fictional', username: 'do-not-save' } } }] }] });
async function request(body: string, valid = true): Promise<Request> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(config.APP_SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const hash = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  const hex = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
  return new Request('https://example.test/webhook', { method: 'POST', body, headers: { 'X-Hub-Signature-256': `sha256=${valid ? hex : '0'.repeat(64)}` } });
}
describe('webhook', () => {
  it('verifies the handshake and rejects incorrect tokens', async () => {
    const store = new MemoryStorage(); const meta = fake();
    const url = 'https://example.test/webhook?hub.mode=subscribe&hub.verify_token=test-verify&hub.challenge=challenge';
    expect(await (await handle(new Request(url), config, store, meta)).text()).toBe('challenge');
    expect((await handle(new Request(url.replace('test-verify', 'wrong')), config, store, meta)).status).toBe(403);
  });
  it('accepts valid signatures and rejects invalid signatures', async () => {
    const store = new MemoryStorage(); const meta = fake(); const body = payload();
    expect((await handle(await request(body, false), config, store, meta)).status).toBe(401);
    expect((await handle(await request(body), config, store, meta)).status).toBe(200);
    expect(meta.privateReply).toHaveBeenCalledTimes(1);
  });
  it('matches whole words ignoring accents and case', () => {
    expect(matches('Mais INFORMAÇÃO, por favor', ['informacao'])).toBe(true);
    expect(matches('informacoes', ['informação'])).toBe(false);
  });
  it('deduplicates and stores only identifiers and timestamp', async () => {
    const store = new MemoryStorage(); const meta = fake();
    await handle(await request(payload()), config, store, meta);
    await handle(await request(payload()), config, store, meta);
    expect(meta.privateReply).toHaveBeenCalledTimes(1);
    expect([...store.records.values()]).toEqual([{ comment_id: 'comment-fictional', igsid: 'user-fictional', created_at: expect.any(Number) }]);
  });
  it('does not send when no keyword matches', async () => {
    const meta = fake(); await handle(await request(payload('Olá')), config, new MemoryStorage(), meta);
    expect(meta.privateReply).not.toHaveBeenCalled();
  });
  it('removes records older than 90 days', async () => {
    const store = new MemoryStorage(); const now = 100 * 86400000;
    await store.claim({ comment_id: 'old', igsid: 'a', created_at: now - 91 * 86400000 });
    await store.claim({ comment_id: 'boundary', igsid: 'b', created_at: now - 90 * 86400000 });
    expect(await cleanup(store, now)).toBe(1); expect([...store.records.keys()]).toEqual(['boundary']);
  });
  it('logs API errors, returns 200 and does not retry', async () => {
    const store = new MemoryStorage(); const meta = fake(); vi.mocked(meta.privateReply).mockRejectedValue(new Error('failure'));
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect((await handle(await request(payload()), config, store, meta)).status).toBe(200);
    await handle(await request(payload()), config, store, meta);
    expect(meta.privateReply).toHaveBeenCalledTimes(1); expect(log).toHaveBeenCalled(); log.mockRestore();
  });
});
