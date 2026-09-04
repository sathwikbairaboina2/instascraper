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
  /** As Business Discovery reports it. Views exist on reels only, so null
   *  means this kind of post has none rather than nobody watched. */
  like_count: number | null
  comments_count: number | null
  view_count: number | null
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
  status: 'selected' | 'prepared' | 'submitted' | 'done' | 'failed'
  error: string | null
  added_at: string
  prepared_at: string | null
  payload: RecreatePayload | null
  thumb_url: string
}

export type RecreatePayload = {
  shortcode: string
  username: string
  ig_url: string
  caption: string | null
  kind: string
  taken_at: string
  prepared_at: string
  slides: {
    index: number
    path: string
    mime: string
    bytes: number
    width: number | null
    height: number | null
  }[]
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

  // Not every failure is json. FastAPI answers an unhandled exception with
  // the plain text "Internal Server Error", and a proxy in front of it can
  // answer with html. Parsing those blindly turns any server fault into
  // "Unexpected token 'I'", which describes the parser rather than the
  // problem and sends you looking in the wrong place.
  let body: unknown = null
  let unparsed: string | null = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      unparsed = text
    }
  }

  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : ((detail as { message?: string } | undefined)?.message ??
          (unparsed ? `${res.status} ${res.statusText}: ${unparsed.slice(0, 200)}` : null) ??
          `request failed (${res.status})`)
    throw new ApiError(res.status, body, message)
  }

  if (unparsed !== null) {
    // A 200 that is not json is still broken, just less obviously.
    throw new ApiError(res.status, null, `expected json, got: ${unparsed.slice(0, 200)}`)
  }

  return body as T
}

/** Path a cached file is served from. One definition, so the pages, the
 *  lightbox and the copy control cannot drift apart on the route shape. */
export const mediaFullPath = (shortcode: string, child = 0) =>
  `/api/media/${encodeURIComponent(shortcode)}/full?child=${child}`

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
export const prepareRecreate = (shortcode: string, slides: number[] | null) =>
  call<RecreatePayload>(`/api/recreate/${encodeURIComponent(shortcode)}/prepare`, {
    method: 'POST',
    body: JSON.stringify({ slides }),
  })

export type DirectUrlItem = {
  shortcode: string
  url: string
  added_at: string
  status: 'pending' | 'failed' | 'indexed'
  username: string | null
  error: string | null
  media: MediaSummary | null
}

export const addDirectUrls = (urls: string[]) =>
  call<{ added: string[]; invalid: string[] }>('/api/urls', {
    method: 'POST',
    body: JSON.stringify({ urls }),
  })
export const listDirectUrls = () => call<{ items: DirectUrlItem[] }>('/api/urls')
export const removeDirectUrl = (shortcode: string) =>
  call<{ removed: number }>(`/api/urls/${encodeURIComponent(shortcode)}`, {
    method: 'DELETE',
  })

export type TrendWindow = 'day' | 'week'

export type TrendingTag = {
  /** Without the leading '#'. The UI adds it. */
  tag: string
  /** likes + comments + views, nulls counted as zero. */
  score: number
  like_count: number
  comments_count: number
  view_count: number
  post_count: number
}

export type TrendingPage = {
  window: TrendWindow
  /** The cutoff the server used, so the page can say what it covered. */
  since: string
  total: number
  items: TrendingTag[]
}

export type TagPostsPage = {
  tag: string
  window: TrendWindow
  total: number
  items: MediaSummary[]
}

export const getTrending = (window: TrendWindow, limit = 25, offset = 0) =>
  call<TrendingPage>(`/api/hashtags/trending?window=${window}&limit=${limit}&offset=${offset}`)

export const getTagPosts = (tag: string, window: TrendWindow, limit = 24, offset = 0) =>
  call<TagPostsPage>(
    `/api/hashtags/${encodeURIComponent(tag)}/posts?window=${window}&limit=${limit}&offset=${offset}`,
  )
