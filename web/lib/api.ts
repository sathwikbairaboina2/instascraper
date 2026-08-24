export type StatusBody = {
  worker: 'running' | 'stopped'
  adapter: 'graph' | 'fake'
  token_configured: boolean
  breaker: {
    tripped: boolean
    permanent: boolean
    reason: string | null
    seconds_remaining: number | null
  }
  queue_depth: number
  /** Percentage of Meta's hourly quota spent, as Meta last reported it.
   *  Null when the live adapter never calls Meta. */
  usage: number | null
  /** Our own scraping caps, not Meta's. Null when the live adapter never
   *  reaches instagram.com. */
  reel_limits: {
    hour: { used: number; max: number; resets_at: string | null }
    day: { used: number; max: number; resets_at: string | null }
  } | null
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
  followers_count: number | null
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
  /** Carousel slides that are video, by child index. A carousel is never
   *  is_video itself, so this is the only way to know. */
  video_children: number[]
  child_count: number
  full_status: 'none' | 'queued' | 'fetching' | 'ready' | 'failed'
  full_error: string | null
  thumb_url: string
  ig_url: string
}

export type RecreateItem = {
  shortcode: string
  username: string
  ig_url: string
  caption: string | null
  status: 'selected' | 'submitted' | 'done' | 'failed'
  error: string | null
  added_at: string
  thumb_url: string
}

export type MediaPage = { items: MediaSummary[]; total: number; exhausted: boolean }
export type EnsureResult = {
  statuses: Record<string, string>
  errors: Record<string, string>
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

export const setAdapter = (adapter: 'graph' | 'fake') =>
  call<{ adapter: 'graph' | 'fake' }>('/api/adapter', {
    method: 'POST',
    body: JSON.stringify({ adapter }),
  })

export const listRecreate = () => call<{ items: RecreateItem[] }>('/api/recreate')
export const getRecreateItem = (shortcode: string) =>
  call<RecreateItem>(`/api/recreate/${encodeURIComponent(shortcode)}`)
export const markRecreate = (shortcodes: string[]) =>
  call<{ added: number; unknown: string[] }>('/api/recreate', {
    method: 'POST',
    body: JSON.stringify({ shortcodes }),
  })
export const unmarkRecreate = (shortcode: string) =>
  call<{ removed: number }>(`/api/recreate/${encodeURIComponent(shortcode)}`, {
    method: 'DELETE',
  })
