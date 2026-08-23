'use client'

import type { MediaSummary } from '@/lib/api'

const BADGE: Record<MediaSummary['kind'], string | null> = {
  image: null,
  video: 'video',
  reel: 'reel',
  carousel: null,
}

function shortReason(message: string | null): string {
  if (!message) return 'Fetch failed'
  const firstLine = message.split('\n')[0]
  return firstLine.length > 60 ? `${firstLine.slice(0, 59)}…` : firstLine
}

export default function MediaTile({
  item,
  selected,
  onToggle,
  onRetry,
}: {
  item: MediaSummary
  selected: boolean
  onToggle: (shiftKey: boolean) => void
  onRetry: () => void
}) {
  const badge = item.kind === 'carousel' ? String(item.child_count) : BADGE[item.kind]
  const failed = item.full_status === 'failed'

  // The retry control is a sibling of the tile button, not a child: a button
  // cannot nest a button, and nesting one would also swallow selection clicks.
  return (
    <div className="tile-wrap">
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
          <span className="badge badge-br">cached</span>
        )}
        {item.full_status === 'queued' && <span className="badge badge-br">queued</span>}
        {item.full_status === 'fetching' && <span className="badge badge-br">fetching</span>}
      </button>

      {failed && (
        <div className="tile-failed" data-testid={`failed-${item.shortcode}`}>
          <span className="tile-failed-msg" title={item.full_error ?? 'Fetch failed'}>
            {shortReason(item.full_error)}
          </span>
          <button
            type="button"
            className="tile-retry"
            data-testid={`retry-${item.shortcode}`}
            onClick={onRetry}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
