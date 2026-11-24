'use client'

import { CloseOutlined } from '@ant-design/icons'
import { Button, Layout, Typography, theme } from 'antd'
import { useEffect, useRef } from 'react'

import { SHEET_QUERY, useMedia } from '@/lib/useMedia'

const { Sider } = Layout
const { Text } = Typography

/** The inspector rail on a profile or direct-links page.
 *
 *  At desktop widths this is the 300 px sider it always was. Below that
 *  (mobile.css) it is a sheet that slides up from the bottom, opened from a
 *  bar that appears once something is selected, so the grid keeps the whole
 *  width. */
export default function SidePanel({
  count,
  label,
  open,
  onOpen,
  onClose,
  children,
}: {
  /** How many items are selected. */
  count: number
  /** What the bar says when nothing is selected but the panel has content. */
  label?: string
  open: boolean
  onOpen: () => void
  onClose: () => void
  children: React.ReactNode
}) {
  const { token } = theme.useToken()
  const compact = useMedia(SHEET_QUERY)
  const sheet = compact && open
  const closeRef = useRef<HTMLButtonElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)
  const showBar = count > 0 || Boolean(label)

  // The sheet covers the page, so focus goes into it and comes back to the
  // bar that opened it.
  useEffect(() => {
    if (sheet) closeRef.current?.focus()
    else if (wasOpen.current) openerRef.current?.focus()
    wasOpen.current = sheet
  }, [sheet])

  // Nothing left to act on.
  useEffect(() => {
    if (open && !showBar) onClose()
  }, [open, showBar, onClose])

  useEffect(() => {
    if (!sheet) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sheet, onClose])

  return (
    <>
      {showBar && (
        <div
          className="sel-bar"
          style={{
            background: token.colorBgElevated,
            borderTop: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Text strong data-testid="selection-bar-count" style={{ flex: 1, minWidth: 0 }} ellipsis>
            {count > 0 ? `${count} selected` : label}
          </Text>
          <Button
            ref={openerRef}
            type="primary"
            data-testid="selection-open"
            aria-expanded={sheet}
            onClick={onOpen}
          >
            {count > 0 ? 'Actions' : 'Open'}
          </Button>
        </div>
      )}
      <div className="sheet-mask" data-open={sheet} onClick={onClose} aria-hidden />
      <Sider
        className="side-panel"
        data-open={open}
        role={sheet ? 'dialog' : undefined}
        aria-label="Selection"
        width={300}
        style={{
          background: token.colorBgContainer,
          borderLeft: `1px solid ${token.colorBorderSecondary}`,
          overflowY: 'auto',
        }}
      >
        <div
          className="sheet-head"
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Text strong style={{ flex: 1 }}>Selection</Text>
          <Button
            ref={closeRef}
            type="text"
            aria-label="Close selection"
            icon={<CloseOutlined />}
            onClick={onClose}
          />
        </div>
        {children}
      </Sider>
    </>
  )
}
