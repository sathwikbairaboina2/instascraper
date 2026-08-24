'use client'

import { CloudDownloadOutlined, ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Input, Progress, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { createDownload, ensureMedia, type DownloadResult, type EnsureResult } from '@/lib/api'

const { Text } = Typography

type Phase = 'idle' | 'waiting' | 'copying' | 'done' | 'error'

const POLL_MS = 1500

export default function SelectionBar({
  shortcodes,
  base,
  onBase,
  fileCount,
  onClear,
  onDone,
  onRecreate,
  markedCount = 0,
}: {
  shortcodes: string[]
  base: string
  onBase: (v: string) => void
  fileCount: number
  onClear: () => void
  onDone: () => void
  onRecreate?: () => Promise<void> | void
  markedCount?: number
}) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<EnsureResult | null>(null)
  const [result, setResult] = useState<DownloadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const key = shortcodes.join(',')

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

      const refused = Object.entries(state.statuses)
        .filter(([, s]) => s === 'quota')
        .map(([sc]) => sc)
      if (refused.length > 0) {
        const why = state.errors?.[refused[0]] ?? 'reel cap spent'
        // Not a failure: the app declined to start. Saying "failed" here
        // sends you looking for a bug that is not there.
        setError(`${refused.length} not fetched — ${why}.`)
        setPhase('error')
        return
      }

      const failed = Object.entries(state.errors ?? {}).filter(
        ([sc]) => state.statuses[sc] !== 'quota',
      )
      if (failed.length > 0) {
        const shown = failed.slice(0, 2).map(([sc, why]) => `${sc}: ${why}`).join(' · ')
        setError(`${failed.length} failed. ${shown}${failed.length > 2 ? ` (+${failed.length - 2} more)` : ''}`)
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
    if (!base.trim()) {
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

  const running = phase === 'waiting' || phase === 'copying'
  const pct = progress && progress.total ? Math.round((progress.ready / progress.total) * 100) : 0

  return (
    <>
      <Text style={{ fontSize: 12, display: 'block', marginBottom: 7 }}>Base filename</Text>
      <Input
        data-testid="base-filename"
        value={base}
        onChange={(e) => onBase(e.target.value)}
        placeholder="nike_ss26"
        disabled={running}
      />
      {onRecreate && (
        <Button
          block
          data-testid="send-to-recreate"
          icon={<ThunderboltOutlined />}
          onClick={() => void onRecreate()}
          style={{ marginBottom: 8 }}
        >
          {markedCount === shortcodes.length && shortcodes.length > 0
            ? 'All in Recreate'
            : `Send ${shortcodes.length} to Recreate`}
        </Button>
      )}

      {base.trim() && (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 7 }}>
          {base.trim()}_01 through {base.trim()}_{String(fileCount).padStart(2, '0')}
        </Text>
      )}

      <Button
        type="primary"
        block
        size="large"
        data-testid="download-submit"
        icon={<CloudDownloadOutlined />}
        loading={running}
        onClick={start}
        style={{ marginTop: 16 }}
      >
        {running ? 'Downloading' : `Download ${fileCount} files`}
      </Button>

      <Button block type="text" data-testid="clear-selection" style={{ marginTop: 8 }} onClick={onClear}>
        Clear selection
      </Button>

      {running && progress && (
        <div style={{ marginTop: 14 }} data-testid="download-progress">
          <Progress percent={pct} size="small" status="active" />
          <Text type="secondary" style={{ fontSize: 11 }}>
            {phase === 'copying' ? 'Copying files' : `${progress.ready} of ${progress.total} ready`}
          </Text>
        </div>
      )}

      {phase === 'done' && result && (
        <Alert
          style={{ marginTop: 14 }}
          type="success"
          showIcon
          data-testid="download-result"
          title={`${result.count} files`}
          description={result.out_dir}
        />
      )}

      {phase === 'error' && error && (
        <Alert
          style={{ marginTop: 14 }}
          type="error"
          showIcon
          data-testid="download-error"
          title={error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={retry}>Retry</Button>}
        />
      )}
    </>
  )
}
