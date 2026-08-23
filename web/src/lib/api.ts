/** JSON fetch wrapper + API client. */

import { parseSSEBlock, type SSEEvent } from './useSSE';

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `请求失败 (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

async function parseDetail(resp: Response): Promise<unknown> {
  try {
    const body = await resp.json();
    return body?.detail ?? body;
  } catch {
    return resp.statusText;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) throw new ApiError(resp.status, await parseDetail(resp));
  return (await resp.json()) as T;
}

/** POST an SSE stream (used by the critique follow-up dialog). No reconnect
 *  — these streams are short-lived; the user can just send again. */
export async function postSSE(
  path: string,
  body: unknown,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) throw new ApiError(resp.status, await parseDetail(resp));
  if (!resp.body) return;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const ev = parseSSEBlock(block);
      if (ev) onEvent(ev);
    }
  }
}

export const api = {
  meta: () => apiFetch<import('./types').Meta>('/api/meta'),

  startReview: (prdText: string, prdFilename?: string, language?: 'zh' | 'en') =>
    apiFetch<{ run_id: string; stream_url: string }>('/api/reviews', {
      method: 'POST',
      body: JSON.stringify({
        prd_text: prdText,
        prd_filename: prdFilename,
        language: language ?? 'auto',
      }),
    }),

  upload: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch('/api/uploads', { method: 'POST', body: form });
    if (!resp.ok) throw new ApiError(resp.status, await parseDetail(resp));
    return resp.json() as Promise<{ filename: string; chars: number; text: string }>;
  },

  goldenPrds: () =>
    apiFetch<{ filename: string; content: string }[]>('/api/golden-prds'),

  history: () => apiFetch<import('./types').HistoryItem[]>('/api/history'),
  historyDetail: (id: string) =>
    apiFetch<import('./types').HistoryDetail>(`/api/history/${id}`),
  historyDelete: (id: string) =>
    apiFetch(`/api/history/${id}`, { method: 'DELETE' }),

  skills: () => apiFetch<import('./types').Skill[]>('/api/skills'),
  skillMd: (name: string) =>
    apiFetch<{ name: string; md: string }>(`/api/skills/${encodeURIComponent(name)}/md`),
  skillFeedback: (name: string, accepted: boolean) =>
    apiFetch(`/api/skills/${encodeURIComponent(name)}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ accepted }),
    }),
  skillDeprecate: (name: string) =>
    apiFetch(`/api/skills/${encodeURIComponent(name)}/deprecate`, { method: 'POST' }),

  distill: () => apiFetch<{ found: number }>('/api/distill', { method: 'POST' }),
  proposals: () => apiFetch<import('./types').Proposal[]>('/api/proposals'),
  proposalApprove: (id: string, editedMd?: string) =>
    apiFetch(`/api/proposals/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify(editedMd !== undefined ? { edited_md: editedMd } : {}),
    }),
  proposalReject: (id: string) =>
    apiFetch(`/api/proposals/${id}/reject`, { method: 'POST' }),
  proposalSaveEdit: (id: string, editedMd: string) =>
    apiFetch(`/api/proposals/${id}/save-edit`, {
      method: 'POST',
      body: JSON.stringify({ edited_md: editedMd }),
    }),

  ablation: () => apiFetch<unknown | null>('/api/ablation'),
  ablationRun: (quick: boolean) =>
    apiFetch<import('./types').AblationJob>('/api/ablation/run', {
      method: 'POST',
      body: JSON.stringify({ quick }),
    }),
  ablationStatus: (jobId: string) =>
    apiFetch<import('./types').AblationJobStatus>(`/api/ablation/status/${jobId}`),

  // ---- Skill Lifecycle Center ----
  lifecycleOverview: () =>
    apiFetch<import('./types').LifecycleOverview>('/api/lifecycle/overview'),
  lifecycleLibrary: () =>
    apiFetch<import('./types').LibraryRow[]>('/api/lifecycle/library'),
  lifecycleLineage: (name: string) =>
    apiFetch<import('./types').LifecycleLineage>(
      `/api/lifecycle/lineage/${encodeURIComponent(name)}`,
    ),
  lifecycleGates: (proposalId: string) =>
    apiFetch<import('./types').GateReportT[]>(
      `/api/lifecycle/gates/${encodeURIComponent(proposalId)}`,
    ),
  lifecycleRunGates: (proposalId: string, includeShadow: boolean) =>
    apiFetch<{ latest: Record<string, import('./types').GateReportT> }>(
      `/api/lifecycle/gates/${encodeURIComponent(proposalId)}/run`,
      { method: 'POST', body: JSON.stringify({ include_shadow: includeShadow }) },
    ),
  lifecycleRollback: (name: string) =>
    apiFetch(`/api/lifecycle/${encodeURIComponent(name)}/rollback`, { method: 'POST' }),
  lifecycleDeprecate: (name: string, reason?: string) =>
    apiFetch(`/api/lifecycle/${encodeURIComponent(name)}/deprecate`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason ?? '' }),
    }),
};
