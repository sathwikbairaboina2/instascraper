'use client'

import { use, useCallback, useEffect, useMemo, useState } from 'react'

import Lightbox from '@/components/Lightbox'
import MediaGrid from '@/components/MediaGrid'
import SelectionBar from '@/components/SelectionBar'
import {
  clearCache,
  ensureMedia,
  getMedia,
  getProfile,
  loadMore,
  setTracked,
  type MediaSummary,
} from '@/lib/api'
import { useFilters } from '@/lib/useFilters'
import { usePolling } from '@/lib/usePolling'
import {
  deleteSelection,
  loadSelections,
  saveSelection,
  type SavedSelection,
} from '@/lib/savedSelections'
import { useSelection } from '@/lib/useSelection'

const PAGE = 120

export default function ProfilePage({ params }: { params: Promise<{ username: string }> }) {
  const { username } = use(params)
  const [busy, setBusy] = useState(false)
  // The window grows to cover everything indexed. A fixed limit silently hid
  // every post past the first 120, however many times you pressed Load more.
  const [windowSize, setWindowSize] = useState(PAGE)

  const {
    data: profile,
    error,
    refresh: refreshProfile,
  } = usePolling(() => getProfile(username), 4000)
  const { data: media, refresh: refreshMedia } = usePolling(
    () => getMedia(username, windowSize, 0),
    4000,
  )

  const total = media?.total ?? 0
  useEffect(() => {
    if (total > windowSize) setWindowSize(total)
  }, [total, windowSize])

  useEffect(() => {
    refreshMedia()
  }, [windowSize, refreshMedia])

  const items = useMemo(() => media?.items ?? [], [media])
  const filters = useFilters(items)
  // Selection follows what is actually on screen, so "Select all loaded" and
  // shift-click ranges mean the visible grid, not the hidden remainder.
  const ids = useMemo(() => filters.visible.map((i) => i.shortcode), [filters.visible])
  const selection = useSelection(ids)

  const [preview, setPreview] = useState<MediaSummary | null>(null)
  const [saved, setSaved] = useState<SavedSelection[]>([])
  const [saveName, setSaveName] = useState('')

  useEffect(() => setSaved(loadSelections(username)), [username])

  // Keep the open lightbox in step with polling, so "Fetch full quality"
  // swaps the placeholder for the real media without reopening.
  const previewLive = useMemo(
    () => (preview ? items.find((i) => i.shortcode === preview.shortcode) ?? preview : null),
    [preview, items],
  )

  const onRetry = useCallback(
    async (shortcode: string) => {
      await ensureMedia([shortcode], true)
      await refreshMedia()
    },
    [refreshMedia],
  )

  const onLoadMore = useCallback(async () => {
    setBusy(true)
    try {
      await loadMore(username)
      await refreshMedia()
    } finally {
      setBusy(false)
    }
  }, [username, refreshMedia])

  if (error) {
    return (
      <p role="alert" data-testid="profile-error">
        {error}
      </p>
    )
  }
  if (!profile) return <p className="muted">Loading…</p>
  if (profile.is_private) {
    return (
      <p role="alert" data-testid="profile-private">
        {username} is private. This tool only supports public profiles.
      </p>
    )
  }

  return (
    <div style={{ display: 'grid', gap: '1rem' }}>
      <header style={{ display: 'flex', gap: '1rem', alignItems: 'center', border: 0 }}>
        <img
          src={profile.avatar_url}
          alt=""
          width={64}
          height={64}
          style={{ borderRadius: '50%' }}
        />
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0 }}>{profile.username}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {profile.post_count ?? 0} posts · {items.length} loaded · {profile.cached_count} cached
          </p>
        </div>
        <button
          data-testid="track-toggle"
          onClick={async () => {
            await setTracked(username, !profile.tracked)
            refreshProfile()
          }}
        >
          {profile.tracked ? 'Untrack' : 'Track'}
        </button>
        <button
          data-testid="clear-cache"
          onClick={async () => {
            await clearCache(username)
            selection.clear()
            refreshMedia()
            refreshProfile()
          }}
        >
          Clear cache
        </button>
      </header>

      <div className="filters" data-testid="filters">
        <select
          data-testid="filter-kind"
          aria-label="Filter by kind"
          value={filters.filters.kind}
          onChange={(e) => filters.set('kind', e.target.value as typeof filters.filters.kind)}
        >
          <option value="all">All kinds</option>
          <option value="image">Photos</option>
          <option value="video">Video &amp; Reels</option>
          <option value="carousel">Carousels</option>
        </select>

        <label className="check">
          <input
            type="checkbox"
            data-testid="filter-cached"
            checked={filters.filters.cachedOnly}
            onChange={(e) => filters.set('cachedOnly', e.target.checked)}
          />
          Cached only
        </label>

        <input
          data-testid="filter-query"
          placeholder="search captions"
          value={filters.filters.query}
          onChange={(e) => filters.set('query', e.target.value)}
        />

        <span className="muted" data-testid="filter-count">
          {filters.visible.length} of {items.length} shown
        </span>

        {filters.active && (
          <button data-testid="filter-reset" onClick={filters.reset}>
            Reset
          </button>
        )}

        <button
          data-testid="select-all"
          disabled={filters.visible.length === 0}
          onClick={selection.selectAll}
        >
          Select all shown
        </button>
      </div>

      <div className="filters" data-testid="saved-selections">
        <input
          data-testid="save-name"
          placeholder="name this selection"
          value={saveName}
          onChange={(e) => setSaveName(e.target.value)}
        />
        <button
          data-testid="save-selection"
          disabled={!saveName.trim() || selection.selected.length === 0}
          onClick={() => {
            setSaved(saveSelection(username, saveName, selection.selected))
            setSaveName('')
          }}
        >
          Save selection
        </button>
        {saved.map((s) => (
          <span key={s.name} className="saved-chip">
            <button
              data-testid={`load-selection-${s.name}`}
              onClick={() => {
                selection.clear()
                s.shortcodes.forEach((sc) => selection.toggle(sc))
              }}
            >
              {s.name} ({s.shortcodes.length})
            </button>
            <button
              aria-label={`Delete ${s.name}`}
              data-testid={`delete-selection-${s.name}`}
              onClick={() => setSaved(deleteSelection(username, s.name))}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      <MediaGrid
        items={filters.visible}
        isSelected={selection.isSelected}
        onToggle={selection.toggle}
        onRetry={onRetry}
        onPreview={setPreview}
        exhausted={media?.exhausted ?? false}
        loading={busy}
        onLoadMore={onLoadMore}
      />

      {previewLive && (
        <Lightbox
          item={previewLive}
          onClose={() => setPreview(null)}
          onFetch={async (shortcode) => {
            await ensureMedia([shortcode])
            await refreshMedia()
          }}
        />
      )}

      <SelectionBar
        shortcodes={selection.selected}
        onClear={selection.clear}
        onDone={refreshMedia}
      />
    </div>
  )
}
