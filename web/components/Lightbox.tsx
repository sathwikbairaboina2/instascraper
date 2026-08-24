'use client'

import { CloudDownloadOutlined, LeftOutlined, LinkOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Flex, Modal, Spin, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import type { MediaSummary } from '@/lib/api'

const { Text } = Typography

export default function Lightbox({
  item,
  onClose,
  onFetch,
}: {
  item: MediaSummary
  onClose: () => void
  onFetch: (shortcode: string) => Promise<void>
}) {
  const isCarousel = item.child_count > 1
  const first = isCarousel ? 1 : 0
  const [child, setChild] = useState(first)
  // Optimistic: the button reflects the click straight away rather than
  // waiting for the next poll to report the queued state.
  const [asked, setAsked] = useState(false)

  const ready = item.full_status === 'ready'
  const working = !ready && (asked || item.full_status === 'queued' || item.full_status === 'fetching')

  const step = useCallback(
    (delta: number) => {
      if (!isCarousel) return
      setChild((c) => {
        const next = c + delta
        if (next < 1) return item.child_count
        if (next > item.child_count) return 1
        return next
      })
    },
    [isCarousel, item.child_count],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') step(1)
      if (e.key === 'ArrowLeft') step(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step])

  const src = `/api/media/${item.shortcode}/full?child=${child}`
  // A carousel is never is_video, but a slide inside it can be. Asking the
  // post rendered every slide as an image and broke the video ones.
  const childIsVideo = isCarousel
    ? (item.video_children ?? []).includes(child)
    : item.is_video

  return (
    <Modal
      open
      onCancel={onClose}
      footer={null}
      width="min(1100px, 92vw)"
      centered
      title={
        <Flex align="center" gap={10}>
          <Text code style={{ fontSize: 12 }}>{item.shortcode}</Text>
          {isCarousel && (
            <Text type="secondary" style={{ fontSize: 12 }}>{child} of {item.child_count}</Text>
          )}
          <div style={{ flex: 1 }} />
          <Button size="small" icon={<LinkOutlined />} href={item.ig_url} target="_blank">
            Instagram
          </Button>
        </Flex>
      }
    >
      <Flex vertical align="center" gap={12} data-testid="lightbox">
        {ready ? (
          childIsVideo ? (
            <video data-testid="lightbox-video" src={src} controls autoPlay style={{ maxWidth: '100%', maxHeight: '72vh' }} />
          ) : (
            <img data-testid="lightbox-image" src={src} alt={item.shortcode} style={{ maxWidth: '100%', maxHeight: '72vh' }} />
          )
        ) : (
          <Flex vertical align="center" gap={12} data-testid="lightbox-placeholder">
            <div style={{ position: 'relative' }}>
              <img
                src={item.thumb_url}
                alt=""
                style={{ maxHeight: '50vh', maxWidth: '100%', opacity: working ? 0.35 : 0.6, filter: 'blur(1px)' }}
              />
              {working && (
                <Spin
                  size="large"
                  style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}
                />
              )}
            </div>
            <Text type="secondary">
              {working ? 'Fetching full quality' : 'Not downloaded yet. This is the thumbnail.'}
            </Text>
            {!working && (
              <Button
                type="primary"
                data-testid="lightbox-fetch"
                icon={<CloudDownloadOutlined />}
                onClick={async () => {
                  setAsked(true)
                  await onFetch(item.shortcode)
                }}
              >
                Fetch full quality
              </Button>
            )}
          </Flex>
        )}

        {isCarousel && ready && (
          <Flex gap={10}>
            <Button data-testid="lightbox-prev" icon={<LeftOutlined />} onClick={() => step(-1)}>Prev</Button>
            <Button data-testid="lightbox-next" onClick={() => step(1)}>
              Next <RightOutlined />
            </Button>
          </Flex>
        )}
      </Flex>
    </Modal>
  )
}
