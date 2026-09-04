'use client'

import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { mediaFullPath } from '@/lib/api'

/** Copies the absolute local url(s) a downloaded file is served from.
 *
 *  Rendered next to media that is cached (`full_status === 'ready'`); the
 *  origin is read at click time so the copied url matches whatever host the
 *  page is actually being viewed from. Given several child indices — a whole
 *  carousel — every slide's url goes on the clipboard, comma separated.
 */
export default function CopyUrlButton({
  shortcode,
  childIdxs = [0],
  testId,
  style,
}: {
  shortcode: string
  childIdxs?: number[]
  /** Override when several copies of the same shortcode share a page, e.g.
   *  the lightbox floating over the tile it was opened from. */
  testId?: string
  style?: React.CSSProperties
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const plural = childIdxs.length > 1

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  return (
    <Tooltip title={copied ? 'Copied' : plural ? 'Copy local URLs' : 'Copy local URL'}>
      <Button
        size="small"
        type="text"
        shape="circle"
        data-testid={testId ?? `copy-url-${shortcode}`}
        aria-label={`Copy local URL${plural ? 's' : ''} of ${shortcode}`}
        icon={copied ? <CheckOutlined /> : <CopyOutlined />}
        onClick={async (e) => {
          e.stopPropagation()
          const text = childIdxs
            .map((c) => new URL(mediaFullPath(shortcode, c), window.location.origin).toString())
            .join(', ')
          await navigator.clipboard.writeText(text)
          setCopied(true)
          if (timer.current) clearTimeout(timer.current)
          timer.current = setTimeout(() => setCopied(false), 1500)
        }}
        style={style}
      />
    </Tooltip>
  )
}
