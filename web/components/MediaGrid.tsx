'use client'

import MediaTile from '@/components/MediaTile'
import type { MediaSummary } from '@/lib/api'

export default function MediaGrid({
  items,
  isSelected,
  onToggle,
  exhausted,
  loading,
  onLoadMore,
}: {
  items: MediaSummary[]
  isSelected: (shortcode: string) => boolean
  onToggle: (shortcode: string, shiftKey: boolean) => void
  exhausted: boolean
  loading: boolean
  onLoadMore: () => void
}) {
  return (
    <>
      <div className="grid" data-testid="media-grid">
        {items.map((item) => (
          <MediaTile
            key={item.shortcode}
            item={item}
            selected={isSelected(item.shortcode)}
            onToggle={(shiftKey) => onToggle(item.shortcode, shiftKey)}
          />
        ))}
      </div>
      <p style={{ marginTop: '1rem' }}>
        <button data-testid="load-more" disabled={exhausted || loading} onClick={onLoadMore}>
          {exhausted ? 'All posts loaded' : loading ? 'Loading…' : 'Load more'}
        </button>
      </p>
    </>
  )
}
