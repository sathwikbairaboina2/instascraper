'use client'

import { clearBreaker, getStatus, type StatusBody } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

function describe(status: StatusBody): string {
  const { breaker, anonymous } = status
  if (breaker.permanent) return breaker.reason ?? 'Instagram session invalid'
  // Anonymous browsing is refused outright by Instagram, so a rate limit here
  // is not something waiting will fix -- say what actually needs to change.
  if (anonymous) {
    return 'Instagram is refusing anonymous access. Browsing public profiles still needs a dedicated account — set IG_USERNAME and IG_PASSWORD, then run the login command.'
  }
  const mins = Math.ceil((breaker.seconds_remaining ?? 0) / 60)
  return `${breaker.reason ?? 'Rate limited'} — resuming in about ${mins} min`
}

export default function Banner() {
  const { data, refresh } = usePolling(getStatus, 5000)
  if (!data || !data.breaker.tripped) return null

  return (
    <div role="alert" data-testid="breaker-banner" className="banner">
      <span>{describe(data)}</span>
      {data.breaker.permanent && (
        <>
          <code>docker compose run --rm api python -m app.ig.login</code>
          <button
            onClick={async () => {
              await clearBreaker()
              refresh()
            }}
          >
            I have fixed it
          </button>
        </>
      )}
    </div>
  )
}
