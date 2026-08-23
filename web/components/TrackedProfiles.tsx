'use client'

import Link from 'next/link'

import { getProfiles } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

export default function TrackedProfiles() {
  const { data } = usePolling(getProfiles, 10000)
  const items = data?.items ?? []

  return (
    <section data-testid="tracked-profiles">
      <h2>Tracked profiles</h2>
      {items.length === 0 && <p className="muted">Nothing tracked yet.</p>}
      <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: '0.5rem' }}>
        {items.map((p) => (
          <li key={p.username}>
            <Link href={`/p/${p.username}`}>
              <strong>{p.username}</strong>{' '}
              <span className="muted">
                {p.post_count ?? 0} posts
                {p.last_synced_at ? ` · synced ${p.last_synced_at.slice(0, 10)}` : ''}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
