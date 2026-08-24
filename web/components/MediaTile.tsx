'use client'

import {
  CheckCircleFilled,
  CommentOutlined,
  ExpandOutlined,
  HeartFilled,
  PlayCircleFilled,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Button, Checkbox, Flex, Progress, Space, Tooltip, Typography, theme } from 'antd'
import { useState } from 'react'

import type { MediaSummary } from '@/lib/api'
import { compactCount } from '@/lib/format'
import { GRADIENT_LINEAR } from '@/lib/themes'

const { Text } = Typography

function pill(children: React.ReactNode) {
  return (
    <span
      style={{
        fontSize: 10.5,
        fontWeight: 600,
        padding: '1px 7px',
        borderRadius: 999,
        background: 'rgba(6,8,12,.62)',
        color: '#fff',
      }}
    >
      {children}
    </span>
  )
}

export default function MediaTile({
  item,
  selected,
  onToggle,
  onRetry,
  onPreview,
  marked = false,
  onRecreate,
  openHref,
  onOpen,
}: {
  item: MediaSummary
  selected: boolean
  onToggle: (shiftKey: boolean) => void
  onRetry: () => void
  onPreview: () => void
  marked?: boolean
  onRecreate?: () => void
  /** Set on tabs where a tile is a way into something rather than something
   *  to select. Selection, and therefore shift-click ranges and the download
   *  flow, are unavailable while this is set. */
  openHref?: string
  onOpen?: () => void
}) {
  const { token } = theme.useToken()
  const [hover, setHover] = useState(false)
  const busy = item.full_status === 'fetching' || item.full_status === 'queued'
  const show = hover || selected

  return (
    <div
      className="tile-wrap"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ position: 'relative', height: '100%' }}
    >
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={item.shortcode}
        data-testid={`tile-${item.shortcode}`}
        className="tile"
        onClick={(e) => (openHref ? onOpen?.() : onToggle(e.shiftKey))}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            if (openHref) onOpen?.()
            else onToggle(e.shiftKey)
          }
        }}
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          aspectRatio: '1',
          borderRadius: token.borderRadiusLG,
          overflow: 'hidden',
          cursor: 'pointer',
          background: token.colorFillQuaternary,
          transform: hover ? 'translateY(-2px)' : 'none',
          transition: 'transform .16s ease, box-shadow .16s ease',
          boxShadow: selected
            ? `0 0 0 2.5px ${token.colorPrimary}`
            : hover
              ? `0 10px 26px rgba(0,0,0,.45), 0 0 0 1px ${token.colorBorder}`
              : `0 0 0 1px ${token.colorBorderSecondary}`,
        }}
      >
        <img
          src={item.thumb_url}
          alt=""
          loading="lazy"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
            filter: item.full_status === 'none' && !show ? 'saturate(.72) brightness(.92)' : 'none',
            transition: 'filter .18s ease',
          }}
        />

        <div
          style={{
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            transition: 'opacity .18s ease',
            opacity: show || busy || item.full_status === 'failed' ? 1 : 0.45,
            background: 'linear-gradient(180deg, rgba(4,6,10,.5), rgba(4,6,10,0) 34%, rgba(4,6,10,.66))',
          }}
        />

        <Space size={4} style={{ position: 'absolute', top: 8, left: 38 }}>
          {item.kind === 'carousel' && pill(item.child_count)}
          {(item.kind === 'reel' || item.kind === 'video') && pill(item.kind)}
        </Space>

        {item.full_status === 'ready' && !busy && (
          <CheckCircleFilled
            style={{ position: 'absolute', left: 10, bottom: 9, color: token.colorSuccess, fontSize: 14 }}
          />
        )}

        {show && !busy && item.full_status !== 'failed' && (
          <Flex
            gap={9}
            align="center"
            data-testid={`engagement-${item.shortcode}`}
            style={{
              position: 'absolute',
              left: 9,
              right: 9,
              bottom: 8,
              fontSize: 11,
              fontWeight: 600,
              color: '#fff',
              textShadow: '0 1px 4px rgba(0,0,0,.9)',
              pointerEvents: 'none',
            }}
          >
            {item.like_count !== null && (
              <span><HeartFilled /> {compactCount(item.like_count)}</span>
            )}
            {item.comments_count !== null && (
              <span><CommentOutlined /> {compactCount(item.comments_count)}</span>
            )}
            {/* Reels only. A photo has no view count, and a zero here would
                say nobody watched something that was never watchable. */}
            {item.view_count !== null && (
              <span><PlayCircleFilled /> {compactCount(item.view_count)}</span>
            )}
          </Flex>
        )}

        {marked && (
          <div
            data-testid={`recreate-flag-${item.shortcode}`}
            aria-hidden
            style={{
              position: 'absolute',
              right: 0,
              bottom: 0,
              width: 0,
              height: 0,
              borderBottom: `26px solid transparent`,
              borderRight: `26px solid #fd1d1d`,
            }}
          />
        )}

        {busy && (
          <div style={{ position: 'absolute', left: 9, right: 9, bottom: 8 }}>
            <Text style={{ fontSize: 10.5, color: '#eef2f8', display: 'block', marginBottom: 3 }}>
              {item.full_status}
            </Text>
            <Progress
              percent={item.full_status === 'queued' ? 8 : 60}
              showInfo={false}
              size="small"
              status="active"
              style={{ margin: 0, lineHeight: 1 }}
            />
          </div>
        )}
      </div>

      {/* Controls sit outside the tile button: a button cannot nest a button,
          and nesting would swallow the selection click. */}
      {!openHref && (
        <div style={{ position: 'absolute', top: 8, left: 8, opacity: show ? 1 : 0.55, transition: 'opacity .15s ease' }}>
          <Checkbox checked={selected} onChange={() => onToggle(false)} />
        </div>
      )}

      {/* Always rendered, never hover gated. A control that only exists on
          hover cannot be reached by keyboard or touch. */}
      <Tooltip title="Preview">
        <Button
          size="small"
          type="text"
          shape="circle"
          data-testid={`preview-${item.shortcode}`}
          aria-label={`Preview ${item.shortcode}`}
          icon={<ExpandOutlined />}
          onClick={onPreview}
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            color: '#fff',
            background: 'rgba(6,8,12,.55)',
            opacity: show ? 1 : 0.5,
            transition: 'opacity .15s ease',
          }}
        />
      </Tooltip>

      {/* Marking is a button; being marked is the ribbon. Same reason the
          preview control is always rendered rather than hover gated: a
          control that exists only on hover cannot be reached by keyboard or
          touch. */}
      {onRecreate && (
        <Tooltip title={marked ? 'Remove from Recreate' : 'Send to Recreate'}>
          <Button
            size="small"
            type="text"
            shape="circle"
            data-testid={`recreate-${item.shortcode}`}
            aria-label={`${marked ? 'Remove' : 'Send'} ${item.shortcode} ${marked ? 'from' : 'to'} Recreate`}
            aria-pressed={marked}
            icon={<ThunderboltOutlined />}
            onClick={onRecreate}
            style={{
              position: 'absolute',
              top: 8,
              right: 40,
              color: '#fff',
              background: marked ? GRADIENT_LINEAR : 'rgba(6,8,12,.55)',
              opacity: show || marked ? 1 : 0.5,
              transition: 'opacity .15s ease',
            }}
          />
        </Tooltip>
      )}

      {item.full_status === 'failed' && (
        <Flex
          align="center"
          gap={6}
          data-testid={`failed-${item.shortcode}`}
          style={{ position: 'absolute', left: 9, right: 9, bottom: 8 }}
        >
          <Tooltip title={item.full_error ?? 'Fetch failed'}>
            <Text style={{ flex: 1, fontSize: 10.5, color: token.colorErrorText }} ellipsis>
              {item.full_error ?? 'Fetch failed'}
            </Text>
          </Tooltip>
          <Button
            size="small"
            type="text"
            danger
            shape="circle"
            data-testid={`retry-${item.shortcode}`}
            aria-label={`Retry ${item.shortcode}`}
            icon={<ReloadOutlined />}
            onClick={onRetry}
          />
        </Flex>
      )}
    </div>
  )
}
