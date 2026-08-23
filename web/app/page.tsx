'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import TrackedProfiles from '@/components/TrackedProfiles'
import { getActivity, syncProfile } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

export default function HomePage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { data: activity } = usePolling(() => getActivity(5), 10000)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const clean = username.trim().replace(/^@/, '')
    if (!clean) return
    try {
      await syncProfile(clean)
      router.push(`/p/${encodeURIComponent(clean)}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div style={{ display: 'grid', gap: '2rem', maxWidth: 720 }}>
      <form onSubmit={submit} style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          data-testid="username-input"
          placeholder="instagram username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ flex: 1, padding: '0.5rem' }}
        />
        <button data-testid="lookup-submit" type="submit">
          Look up
        </button>
      </form>
      {error && <p role="alert">{error}</p>}

      <TrackedProfiles />

      <section>
        <h2>Recent activity</h2>
        <ul className="muted" style={{ paddingLeft: '1rem' }}>
          {(activity?.items ?? []).map((item) => (
            <li key={item.id}>
              {item.ts.slice(0, 19).replace('T', ' ')} — {item.action}
              {item.target ? ` ${item.target}` : ''}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
