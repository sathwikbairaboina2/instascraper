'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Poll `fn` on an interval, with two limits that matter for a tool that sits
 * open all day:
 *
 *  - a hidden tab does not poll at all, and refreshes once on return
 *  - identical payloads do not replace state, so an unchanged grid does not
 *    re-render every tick
 */
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

    const start = () => {
      if (id !== null) return
      void tick()
      id = setInterval(tick, intervalMs)
    }

    const stop = () => {
      if (id === null) return
      clearInterval(id)
      id = null
    }

    const onVisibility = () => {
      if (typeof document === 'undefined') return
      if (document.hidden) stop()
      else start()
    }

    if (typeof document !== 'undefined' && document.hidden) {
      // Do not start a timer for a tab nobody is looking at.
      document.addEventListener('visibilitychange', onVisibility)
    } else {
      start()
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibility)
      }
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
