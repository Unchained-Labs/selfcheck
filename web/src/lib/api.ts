import type {
  DiffPayload, Note, NoteStatus, Review, ReviewDetail, Run, Severity, Status,
} from './types'

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { 'content-type': 'application/json', ...init?.headers } : init?.headers,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep the status line */ }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

const body = (v: unknown) => ({ method: 'POST', body: JSON.stringify(v) })

export const api = {
  status: () => req<Status>('/api/status'),

  listReviews: () => req<{ reviews: Review[] }>('/api/reviews').then((r) => r.reviews),

  addReview: (url: string, opts: { watch?: boolean; review_now?: boolean } = {}) =>
    req<{ review: Review; run: Run | null }>('/api/reviews', body({ url, ...opts })),

  getReview: (id: string) => req<ReviewDetail>(`/api/reviews/${id}`),

  deleteReview: (id: string) => req<{ deleted: string }>(`/api/reviews/${id}`, { method: 'DELETE' }),

  setFlags: (id: string, flags: { watch?: boolean; pinned?: boolean; archived?: boolean }) =>
    req<{ review: Review }>(`/api/reviews/${id}/flags`, {
      method: 'PATCH', body: JSON.stringify(flags), headers: { 'content-type': 'application/json' },
    }),

  sync: (id: string) =>
    req<{ review: Review; head_changed: boolean }>(`/api/reviews/${id}/sync`, { method: 'POST' }),

  diff: (id: string, refresh = false) =>
    req<DiffPayload>(`/api/reviews/${id}/diff${refresh ? '?refresh=true' : ''}`),

  blob: (id: string, path: string, side: 'new' | 'old') =>
    req<string>(`/api/reviews/${id}/blob?path=${encodeURIComponent(path)}&side=${side}`),

  setFileViewed: (id: string, path: string, viewed: boolean) =>
    req<{ file_path: string; viewed: boolean }>(
      `/api/reviews/${id}/files/viewed`,
      body({ path, viewed }),
    ),

  startRun: (id: string, guidance = '') =>
    req<{ run: Run }>(`/api/reviews/${id}/runs`, body({ guidance, trigger: 'manual' })),

  cancelRun: (runId: string) => req<{ run: Run }>(`/api/runs/${runId}/cancel`, { method: 'POST' }),

  getRun: (runId: string) => req<{ run: Run }>(`/api/runs/${runId}`),

  addNote: (
    id: string,
    note: {
      file: string; line_start?: number | null; line_end?: number | null
      side?: 'new' | 'old'; severity: Severity; category: string; title: string; body: string
    },
  ) => req<{ notes: Note[] }>(`/api/reviews/${id}/notes`, body({ origin: 'human', notes: [note] })),

  patchNote: (
    noteId: string,
    patch: Partial<{
      status: NoteStatus; severity: Severity; title: string; body: string
      suggestion: string; stale: boolean
    }>,
  ) =>
    req<{ note: Note }>(`/api/notes/${noteId}`, {
      method: 'PATCH', body: JSON.stringify(patch), headers: { 'content-type': 'application/json' },
    }),

  deleteNote: (noteId: string) => req<{ deleted: string }>(`/api/notes/${noteId}`, { method: 'DELETE' }),

  exportUrl: (id: string, includeResolved = false) =>
    `/api/reviews/${id}/export.md${includeResolved ? '?include_resolved=true' : ''}`,

  exportMarkdown: (id: string, includeResolved = false) =>
    req<string>(api.exportUrl(id, includeResolved)),
}

export { ApiError }
