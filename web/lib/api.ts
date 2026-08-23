export type StatusBody = {
  worker: 'running' | 'stopped'
  breaker: {
    tripped: boolean
    permanent: boolean
    reason: string | null
    seconds_remaining: number | null
  }
  queue_depth: number
}

export type ProfileSummary = {
  username: string
  full_name: string | null
  post_count: number | null
  avatar_url: string
  last_synced_at: string | null
}

export type ProfileDetail = ProfileSummary & {
  biography: string | null
  is_private: boolean
  tracked: boolean
  exhausted: boolean
  cached_count: number
}

export type MediaSummary = {
  shortcode: string
  kind: 'image' | 'video' | 'reel' | 'carousel'
  taken_at: string
  caption: string | null
  is_video: boolean
  child_count: number
  full_status: 'none' | 'queued' | 'fetching' | 'ready' | 'failed'
  thumb_url: string
  ig_url: string
}

export type MediaPage = { items: MediaSummary[]; total: number; exhausted: boolean }
export type EnsureResult = {
  statuses: Record<string, string>
  ready: number
  total: number
}
export type DownloadResult = { written: string[]; out_dir: string; count: number }
export type ActivityItem = {
  id: number
  ts: string
  action: string
  target: string | null
  detail: Record<string, unknown> | null
}

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: unknown, message: string) {
    super(message)
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const detail = body?.detail
    const message =
      typeof detail === 'string' ? detail : detail?.message ?? `request failed (${res.status})`
    throw new ApiError(res.status, body, message)
  }
  return body as T
}

export const getStatus = () => call<StatusBody>('/api/status')
export const clearBreaker = () =>
  call<{ cleared: boolean }>('/api/health/clear-breaker', { method: 'POST' })

export const getProfiles = () => call<{ items: ProfileSummary[] }>('/api/profiles')
export const getProfile = (u: string) =>
  call<ProfileDetail>(`/api/profiles/${encodeURIComponent(u)}`)
export const syncProfile = (u: string) =>
  call<{ queued: boolean }>(`/api/profiles/${encodeURIComponent(u)}/sync`, { method: 'POST' })
export const setTracked = (u: string, tracked: boolean) =>
  call<{ tracked: boolean }>(`/api/profiles/${encodeURIComponent(u)}/tracked`, {
    method: 'PUT',
    body: JSON.stringify({ tracked }),
  })
export const clearCache = (u: string) =>
  call<{ removed_files: number }>(`/api/profiles/${encodeURIComponent(u)}/cache`, {
    method: 'DELETE',
  })
export const getMedia = (u: string, limit: number, offset: number) =>
  call<MediaPage>(`/api/profiles/${encodeURIComponent(u)}/media?limit=${limit}&offset=${offset}`)
export const loadMore = (u: string) =>
  call<{ queued: boolean; exhausted: boolean }>(
    `/api/profiles/${encodeURIComponent(u)}/load-more`,
    { method: 'POST' },
  )

export const ensureMedia = (shortcodes: string[], retry = false) =>
  call<EnsureResult>('/api/media/ensure', {
    method: 'POST',
    body: JSON.stringify({ shortcodes, retry }),
  })
export const createDownload = (shortcodes: string[], base: string) =>
  call<DownloadResult>('/api/downloads', {
    method: 'POST',
    body: JSON.stringify({ shortcodes, base }),
  })

export const getActivity = (limit = 100) =>
  call<{ items: ActivityItem[] }>(`/api/activity?limit=${limit}`)
