import type { ArtifactBody, NewResearch, ResearchRun, RunList, Session, RunEvent } from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId = '',
    public retryable = false,
  ) {
    super(message);
  }
}
let csrf = '';
export function setCsrf(token: string) {
  csrf = token;
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && !['GET', 'HEAD'].includes(options.method) && csrf)
    headers.set('X-CSRF-Token', csrf);
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'same-origin' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK_ERROR', '暂时无法连接服务器，请检查网络后重试。', '', true);
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('wenli:session-expired'));
    const body = await response.json().catch(() => ({}));
    const info = body.error ?? body.detail ?? body;
    throw new ApiError(
      response.status,
      info.code ?? 'REQUEST_ERROR',
      typeof info.message === 'string'
        ? info.message
        : `请求未完成（${response.status}），请重试。`,
      info.request_id,
      info.retryable,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const api = {
  me: () => request<Session>('/auth/me'),
  login: (username: string, password: string) =>
    request<Session>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  changePassword: (old_password: string, new_password: string) =>
    request<Session>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ old_password, new_password }),
    }),
  list: (params = '', signal?: AbortSignal) =>
    request<RunList>(`/research-runs${params ? `?${params}` : ''}`, { signal }),
  run: (id: string, signal?: AbortSignal) =>
    request<ResearchRun>(`/research-runs/${encodeURIComponent(id)}`, { signal }),
  history: (id: string, after = 0, signal?: AbortSignal) =>
    request<{ items: RunEvent[]; next_cursor?: number; history_available: boolean }>(
      `/research-runs/${encodeURIComponent(id)}/events/history?after=${after}`,
      { signal },
    ),
  create: (input: NewResearch, key: string) =>
    request<ResearchRun>('/research-runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
      body: JSON.stringify(input),
    }),
  cancel: (id: string) =>
    request<ResearchRun>(`/research-runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  delete: (id: string) =>
    request<void>(`/research-runs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  artifact: (runId: string, artifactId: string, signal?: AbortSignal) =>
    request<ArtifactBody>(
      `/research-runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
      { signal },
    ),
  artifactUrl: (id: string, artifact: string) =>
    `/api/v1/research-runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifact)}.md`,
  reportUrl: (id: string) => `/api/v1/research-runs/${encodeURIComponent(id)}/report.md`,
};
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : '操作未完成，请重试。';
}

// Keep the key while the outcome is uncertain, including after refresh. A new input gets a new key.
const ATTEMPT_KEY = 'wenli.submit-attempt';
let localAttempt: { fingerprint: string; key: string } | null = null;
export function submissionKey(input: NewResearch) {
  const fingerprint = JSON.stringify(input);
  if (localAttempt?.fingerprint === fingerprint) return localAttempt.key;
  try {
    const saved = JSON.parse(sessionStorage.getItem(ATTEMPT_KEY) ?? 'null');
    if (saved?.fingerprint === fingerprint && typeof saved.key === 'string') {
      localAttempt = saved;
      return saved.key as string;
    }
  } catch {
    /* Ignore invalid storage, never reuse an unrelated submission. */
  }
  const key = crypto.randomUUID();
  localAttempt = { fingerprint, key };
  try {
    sessionStorage.setItem(ATTEMPT_KEY, JSON.stringify({ fingerprint, key }));
  } catch {
    /* Storage can be unavailable. */
  }
  return key;
}
export function clearSubmission() {
  localAttempt = null;
  try {
    sessionStorage.removeItem(ATTEMPT_KEY);
  } catch {
    /* Optional local state. */
  }
}
