'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const lastJson = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const next = await fnRef.current()
      // Only swap state when the payload actually changed. Replacing an
      // identical object every 4s re-renders the whole grid and churns the
      // identities selection and filtering are derived from.
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
    const tick = async () => {
      if (!cancelled) await refresh()
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, refresh }
}
