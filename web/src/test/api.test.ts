import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSubmission, request, setCsrf, submissionKey } from '../api';
import { safeNext } from '../Auth';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrf('');
  clearSubmission();
});
describe('browser API boundary', () => {
  it('sends the session CSRF token with mutations and preserves structured errors', async () => {
    setCsrf('csrf-for-this-session');
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            code: 'QUEUE_FULL',
            message: '等待队列已满',
            request_id: 'r1',
            retryable: true,
          }),
          { status: 429 },
        ),
      );
    vi.stubGlobal('fetch', fetcher);
    await expect(request('/research-runs', { method: 'POST', body: '{}' })).rejects.toMatchObject({
      code: 'QUEUE_FULL',
      status: 429,
      message: '等待队列已满',
      requestId: 'r1',
      retryable: true,
    });
    expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin');
    expect(fetcher.mock.calls[0][1].headers.get('X-CSRF-Token')).toBe('csrf-for-this-session');
  });
  it('expires client session when the server rejects an expired cookie', async () => {
    const expired = vi.fn();
    window.addEventListener('wenli:session-expired', expired);
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ code: 'AUTH_REQUIRED', message: '请重新登录' }), {
            status: 401,
          }),
        ),
    );
    await expect(request('/auth/me')).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    window.removeEventListener('wenli:session-expired', expired);
  });
  it('still protects retries from duplicate submissions when session storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage unavailable');
    });
    const input = { topic: '同一请求', instructions: '请求结果未知' };
    const first = submissionKey(input);
    expect(submissionKey(input)).toBe(first);
    clearSubmission();
    expect(submissionKey(input)).not.toBe(first);
  });
  it('keeps login return destinations inside the current site', () => {
    expect(safeNext('https://example.com')).toBe('/');
    expect(safeNext('//example.com')).toBe('/');
    expect(safeNext('/\\example.com')).toBe('/');
    expect(safeNext('/research/example')).toBe('/research/example');
  });
});
