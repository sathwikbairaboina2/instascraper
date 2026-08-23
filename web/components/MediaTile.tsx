'use client'

import type { MediaSummary } from '@/lib/api'

const BADGE: Record<MediaSummary['kind'], string | null> = {
  image: null,
  video: 'video',
  reel: 'reel',
  carousel: null,
}

export default function MediaTile({
  item,
  selected,
  onToggle,
}: {
  item: MediaSummary
  selected: boolean
  onToggle: (shiftKey: boolean) => void
}) {
  const badge = item.kind === 'carousel' ? String(item.child_count) : BADGE[item.kind]

  return (
    <button
      type="button"
      className="tile"
      data-testid={`tile-${item.shortcode}`}
      aria-pressed={selected}
      aria-label={item.shortcode}
      onClick={(e) => onToggle(e.shiftKey)}
    >
      <img src={item.thumb_url} alt="" loading="lazy" />
      {badge && <span className="badge">{badge}</span>}
      {item.full_status === 'ready' && (
        <span className="badge" style={{ top: 'auto', bottom: 6, right: 6 }}>
          cached
        </span>
      )}
    </button>
  )
}
