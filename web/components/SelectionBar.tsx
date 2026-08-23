'use client'

import { useEffect, useRef, useState } from 'react'

import { createDownload, ensureMedia, type DownloadResult, type EnsureResult } from '@/lib/api'

type Phase = 'idle' | 'waiting' | 'copying' | 'done' | 'error'

const POLL_MS = 1500

export default function SelectionBar({
  shortcodes,
  onClear,
  onDone,
}: {
  shortcodes: string[]
  onClear: () => void
  onDone: () => void
}) {
  const [base, setBase] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<EnsureResult | null>(null)
  const [result, setResult] = useState<DownloadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const key = shortcodes.join(',')

  // Changing the selection abandons any in-flight flow.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    setPhase('idle')
    setProgress(null)
    setResult(null)
    setError(null)
  }, [key])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  if (shortcodes.length === 0) return null

  const counts = (statuses: Record<string, string>) => {
    const tally: Record<string, number> = {}
    for (const value of Object.values(statuses)) tally[value] = (tally[value] ?? 0) + 1
    return Object.entries(tally)
      .map(([k, v]) => `${v} ${k}`)
      .join(' · ')
  }

  async function copyNow() {
    setPhase('copying')
    try {
      const done = await createDownload(shortcodes, base.trim())
      setResult(done)
      setPhase('done')
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  async function step() {
    try {
      const state = await ensureMedia(shortcodes)
      setProgress(state)

      if (Object.values(state.statuses).includes('failed')) {
        setError('Some items failed to download from Instagram.')
        setPhase('error')
        return
      }
      if (Object.values(state.statuses).includes('unknown')) {
        setError('Some selected items are no longer in the index. Reload the profile.')
        setPhase('error')
        return
      }
      if (state.ready === state.total) {
        await copyNow()
        return
      }
      timer.current = setTimeout(step, POLL_MS)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  async function start() {
    const clean = base.trim()
    if (!clean) {
      setError('Enter a base filename first.')
      setPhase('error')
      return
    }
    setError(null)
    setResult(null)
    setPhase('waiting')
    await step()
  }

  async function retry() {
    setError(null)
    setPhase('waiting')
    await ensureMedia(shortcodes, true)
    await step()
  }

  return (
    <div className="selection-bar" data-testid="selection-bar">
      <strong data-testid="selection-count">{shortcodes.length} selected</strong>

      <input
        data-testid="base-filename"
        placeholder="base filename"
        value={base}
        onChange={(e) => setBase(e.target.value)}
        disabled={phase === 'waiting' || phase === 'copying'}
      />

      <button
        data-testid="download-submit"
        onClick={start}
        disabled={phase === 'waiting' || phase === 'copying'}
      >
        Download
      </button>

      <button data-testid="clear-selection" onClick={onClear}>
        Clear
      </button>

      {(phase === 'waiting' || phase === 'copying') && progress && (
        <span className="muted" data-testid="download-progress">
          {phase === 'copying' ? 'Copying files…' : counts(progress.statuses)}
        </span>
      )}

      {phase === 'done' && result && (
        <span data-testid="download-result">
          {result.count} files → {result.out_dir}
        </span>
      )}

      {phase === 'error' && error && (
        <span role="alert" data-testid="download-error">
          {error} <button onClick={retry}>Retry</button>
        </span>
      )}
    </div>
  )
}
