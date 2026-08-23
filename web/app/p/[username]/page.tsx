'use client'

import { use, useCallback, useMemo, useState } from 'react'

import MediaGrid from '@/components/MediaGrid'
import SelectionBar from '@/components/SelectionBar'
import { clearCache, getMedia, getProfile, loadMore, setTracked } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'
import { useSelection } from '@/lib/useSelection'

const PAGE = 120

export default function ProfilePage({ params }: { params: Promise<{ username: string }> }) {
  const { username } = use(params)
  const [busy, setBusy] = useState(false)

  const {
    data: profile,
    error,
    refresh: refreshProfile,
  } = usePolling(() => getProfile(username), 4000)
  const { data: media, refresh: refreshMedia } = usePolling(
    () => getMedia(username, PAGE, 0),
    4000,
  )

  const items = useMemo(() => media?.items ?? [], [media])
  const ids = useMemo(() => items.map((i) => i.shortcode), [items])
  const selection = useSelection(ids)

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

      <p>
        <button data-testid="select-all" onClick={selection.selectAll}>
          Select all loaded
        </button>
      </p>

      <MediaGrid
        items={items}
        isSelected={selection.isSelected}
        onToggle={selection.toggle}
        exhausted={media?.exhausted ?? false}
        loading={busy}
        onLoadMore={onLoadMore}
      />

      <SelectionBar
        shortcodes={selection.selected}
        onClear={selection.clear}
        onDone={refreshMedia}
      />
    </div>
  )
}
