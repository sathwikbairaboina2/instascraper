'use client'

import { DeleteOutlined, LinkOutlined, PictureOutlined } from '@ant-design/icons'
import { Button, Empty, Flex, Layout, Tag, Tooltip, Typography } from 'antd'
import Link from 'next/link'

import AppShell from '@/components/AppShell'
import { useThemePref } from '@/components/ThemeProvider'
import type { RecreateItem } from '@/lib/api'
import { useRecreateShared } from '@/components/RecreateProvider'
import { useState } from 'react'

const { Content } = Layout
const { Text } = Typography

/** Statuses are thin on purpose: the generator that will move an item
 *  through them does not exist yet. */
const STATUS: Record<RecreateItem['status'], { label: string; colour: string }> = {
  selected: { label: 'Selected', colour: 'default' },
  submitted: { label: 'Submitted', colour: 'processing' },
  done: { label: 'Done', colour: 'success' },
  failed: { label: 'Failed', colour: 'error' },
}

/** The row outlives the cache its picture comes from, so a 404 here is a
 *  normal state rather than a fault: clearing a profile is allowed to take
 *  the thumbnail without taking the work. */
function Thumb({ shortcode, src }: { shortcode: string; src: string }) {
  const { tokens } = useThemePref()
  const [gone, setGone] = useState(false)

  const box = {
    width: 56,
    height: 56,
    borderRadius: 8,
    display: 'block',
    background: tokens.surface,
    flex: 'none',
  } as const

  if (gone) {
    return (
      <div
        data-testid={`recreate-thumb-fallback-${shortcode}`}
        title="Thumbnail no longer cached"
        style={{ ...box, display: 'grid', placeItems: 'center', color: tokens.textSecondary }}
      >
        <PictureOutlined />
      </div>
    )
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" onError={() => setGone(true)} style={{ ...box, objectFit: 'cover' }} />
  )
}

export default function RecreatePage() {
  const { tokens } = useThemePref()
  const { items, unmark } = useRecreateShared()

  return (
    <AppShell>
      <Content style={{ padding: '20px 24px', overflowY: 'auto' }}>
        <Flex vertical gap={4} style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 18, letterSpacing: '-.02em' }}>Recreate</Text>
          <Text style={{ fontSize: 12, color: tokens.textSecondary }}>
            Posts lined up to be remade as your own. Open one to work on it.
          </Text>
        </Flex>

        {items.length === 0 ? (
          <Empty
            data-testid="recreate-empty"
            description="Nothing lined up yet. Mark a post on any profile to add it here."
            style={{ marginTop: 90 }}
          />
        ) : (
          <Flex vertical gap={8} data-testid="recreate-list">
            {items.map((item) => (
              <Flex
                key={item.shortcode}
                align="center"
                gap={12}
                data-testid={`recreate-row-${item.shortcode}`}
                style={{
                  border: `1px solid ${tokens.hairline}`,
                  borderRadius: 10,
                  padding: 10,
                }}
              >
                <Link
                  href={`/recreate/${encodeURIComponent(item.shortcode)}`}
                  data-testid={`recreate-open-${item.shortcode}`}
                >
                  <Thumb shortcode={item.shortcode} src={item.thumb_url} />
                </Link>

                <Flex vertical gap={2} style={{ flex: 1, minWidth: 0 }}>
                  <Link href={`/recreate/${encodeURIComponent(item.shortcode)}`}>
                    <Text strong style={{ fontSize: 13 }}>{item.username}</Text>
                  </Link>
                  <Text
                    style={{ fontSize: 11.5, color: tokens.textSecondary }}
                    ellipsis={{ tooltip: item.caption ?? '' }}
                  >
                    {item.caption || 'No caption'}
                  </Text>
                </Flex>

                <Tag color={STATUS[item.status].colour} data-testid={`recreate-status-${item.shortcode}`}>
                  {STATUS[item.status].label}
                </Tag>

                <Tooltip title="Open on Instagram">
                  <Button size="small" type="text" icon={<LinkOutlined />} href={item.ig_url} target="_blank" />
                </Tooltip>

                <Tooltip title="Remove from Recreate">
                  <Button
                    size="small"
                    type="text"
                    data-testid={`recreate-remove-${item.shortcode}`}
                    aria-label={`Remove ${item.shortcode} from Recreate`}
                    icon={<DeleteOutlined />}
                    onClick={() => void unmark(item.shortcode)}
                  />
                </Tooltip>
              </Flex>
            ))}
          </Flex>
        )}
      </Content>
    </AppShell>
  )
}
