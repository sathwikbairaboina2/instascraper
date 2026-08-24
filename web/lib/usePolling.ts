'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Poll `fn` on an interval, with two limits that matter for a tool that sits
 * open all day:
 *
 *  - a hidden tab polls at a reduced rate, and refreshes at once on return
 *  - identical payloads do not replace state, so an unchanged grid does not
 *    re-render every tick
 *
 * Hidden tabs are slowed rather than stopped. Stopping outright froze the
 * screen for any tab that was hidden at mount and never uncovered: work the
 * user had already asked for finished on the server and the UI never showed
 * it, because the only thing that restarted the timer was a visibilitychange
 * that never fired.
 */
const HIDDEN_FACTOR = 4
const HIDDEN_MAX = 30_000

export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const lastJson = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const next = await fnRef.current()
      const json = JSON.stringify(next)
      if (json !== lastJson.current) {
        lastJson.current = json
        setData(next)
      }
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let id: ReturnType<typeof setInterval> | null = null

    const tick = async () => {
      if (!cancelled) await refresh()
    }

    const stop = () => {
      if (id === null) return
      clearInterval(id)
      id = null
    }

    const rateFor = (hidden: boolean) =>
      hidden ? Math.min(intervalMs * HIDDEN_FACTOR, HIDDEN_MAX) : intervalMs

    let current = 0
    const start = (hidden: boolean) => {
      const rate = rateFor(hidden)
      if (id !== null && rate === current) return
      stop()
      current = rate
      id = setInterval(tick, rate)
    }

    const onVisibility = () => {
      if (typeof document === 'undefined') return
      if (!document.hidden) void tick()
      start(document.hidden)
    }

    // Always fetch once, even if the tab starts hidden: otherwise a screen
    // opened in a background tab renders empty forever and only fills in if a
    // visibilitychange happens to fire.
    void tick()
    start(typeof document !== 'undefined' && document.hidden)
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibility)
    }

    return () => {
      cancelled = true
      stop()
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility)
      }
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, refresh }
}
