'use client'

import { useCallback, useEffect, useState } from 'react'

import type { MediaSummary } from '@/lib/api'

export default function Lightbox({
  item,
  onClose,
  onFetch,
}: {
  item: MediaSummary
  onClose: () => void
  onFetch: (shortcode: string) => void
}) {
  const isCarousel = item.child_count > 1
  const first = isCarousel ? 1 : 0
  const [child, setChild] = useState(first)
  const ready = item.full_status === 'ready'

  const step = useCallback(
    (delta: number) => {
      if (!isCarousel) return
      setChild((c) => {
        const next = c + delta
        if (next < 1) return item.child_count
        if (next > item.child_count) return 1
        return next
      })
    },
    [isCarousel, item.child_count],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') step(1)
      if (e.key === 'ArrowLeft') step(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, step])

  const src = `/api/media/${item.shortcode}/full?child=${child}`

  return (
    <div
      className="lightbox"
      data-testid="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={item.shortcode}
      onClick={onClose}
    >
      <div className="lightbox-inner" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-bar">
          <span className="lightbox-title">
            {item.shortcode}
            {isCarousel && (
              <span className="muted">
                {' '}
                · {child}/{item.child_count}
              </span>
            )}
          </span>
          <a href={item.ig_url} target="_blank" rel="noreferrer">
            Open on Instagram
          </a>
          <button type="button" data-testid="lightbox-close" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="lightbox-stage">
          {ready ? (
            item.is_video ? (
              <video data-testid="lightbox-video" src={src} controls autoPlay />
            ) : (
              <img data-testid="lightbox-image" src={src} alt={item.shortcode} />
            )
          ) : (
            <div className="lightbox-placeholder" data-testid="lightbox-placeholder">
              <img src={item.thumb_url} alt="" />
              <p>Not downloaded yet — this is the thumbnail.</p>
              <button
                type="button"
                data-testid="lightbox-fetch"
                onClick={() => onFetch(item.shortcode)}
              >
                Fetch full quality
              </button>
            </div>
          )}
        </div>

        {isCarousel && ready && (
          <div className="lightbox-nav">
            <button type="button" data-testid="lightbox-prev" onClick={() => step(-1)}>
              ‹ Prev
            </button>
            <button type="button" data-testid="lightbox-next" onClick={() => step(1)}>
              Next ›
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
