'use client'

import { clearBreaker, getStatus, type StatusBody } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

function describe(breaker: StatusBody['breaker']): string {
  if (breaker.permanent) return breaker.reason ?? 'Instagram session invalid'
  const mins = Math.ceil((breaker.seconds_remaining ?? 0) / 60)
  return `${breaker.reason ?? 'Rate limited'} — resuming in about ${mins} min`
}

export default function Banner() {
  const { data, refresh } = usePolling(getStatus, 5000)
  if (!data || !data.breaker.tripped) return null

  return (
    <div role="alert" data-testid="breaker-banner" className="banner">
      <span>{describe(data.breaker)}</span>
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
