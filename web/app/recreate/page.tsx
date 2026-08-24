'use client'

import { DeleteOutlined, LinkOutlined, PictureOutlined } from '@ant-design/icons'
import { Button, Empty, Flex, Layout, Segmented, Tooltip, Typography } from 'antd'
import Link from 'next/link'
import { useMemo, useState } from 'react'

import AppShell from '@/components/AppShell'
import { useRecreateShared } from '@/components/RecreateProvider'
import { useThemePref } from '@/components/ThemeProvider'
import type { RecreateItem } from '@/lib/api'

const { Content } = Layout
const { Text } = Typography

type Status = RecreateItem['status']

/** Thin on purpose: the generator that will move an item through these does
 *  not exist yet, so there is nothing to invent states for. */
const TABS: { key: Status; label: string }[] = [
  { key: 'selected', label: 'Selected' },
  { key: 'submitted', label: 'Submitted' },
  { key: 'done', label: 'Done' },
  { key: 'failed', label: 'Failed' },
]

/** The card outlives the cache its picture comes from, so a 404 here is a
 *  normal state rather than a fault: clearing a profile is allowed to take
 *  the thumbnail without taking the work. */
function Thumb({ shortcode, src }: { shortcode: string; src: string }) {
  const { tokens } = useThemePref()
  const [gone, setGone] = useState(false)

  if (gone) {
    return (
      <div
        data-testid={`recreate-thumb-fallback-${shortcode}`}
        title="Thumbnail no longer cached"
        style={{
          aspectRatio: '1',
          display: 'grid',
          placeItems: 'center',
          background: tokens.surface,
          color: tokens.textSecondary,
        }}
      >
        <PictureOutlined style={{ fontSize: 20 }} />
      </div>
    )
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      onError={() => setGone(true)}
      style={{
        width: '100%',
        aspectRatio: '1',
        objectFit: 'cover',
        display: 'block',
        background: tokens.surface,
      }}
    />
  )
}

export default function RecreatePage() {
  const { tokens } = useThemePref()
  const { items, unmark } = useRecreateShared()
  const [tab, setTab] = useState<Status>('selected')

  const counts = useMemo(() => {
    const out: Record<Status, number> = { selected: 0, submitted: 0, done: 0, failed: 0 }
    for (const item of items) out[item.status] += 1
    return out
  }, [items])

  const shown = items.filter((item) => item.status === tab)

  return (
    <AppShell>
      <Content style={{ padding: '20px 24px', overflowY: 'auto' }}>
        <Flex vertical gap={4} style={{ marginBottom: 14 }}>
          <Text strong style={{ fontSize: 18, letterSpacing: '-.02em' }}>Recreate</Text>
          <Text style={{ fontSize: 12, color: tokens.textSecondary }}>
            Posts lined up to be remade as your own. Open one to work on it.
          </Text>
        </Flex>

        {/* Status is the structure rather than a chip to hunt for. Tabs and
            not columns: a tab reading zero is still a tab, where the same
            grouping laid out as columns is three empty ones until the
            generator exists. */}
        <Segmented
          data-testid="recreate-tabs"
          value={tab}
          onChange={(v) => setTab(v as Status)}
          style={{ marginBottom: 14 }}
          options={TABS.map((t) => ({ value: t.key, label: `${t.label} ${counts[t.key]}` }))}
        />

        {shown.length === 0 ? (
          <Empty
            data-testid="recreate-empty"
            description={
              items.length === 0
                ? 'Nothing lined up yet. Mark a post on any profile to add it here.'
                : `Nothing ${tab} right now.`
            }
            style={{ marginTop: 70 }}
          />
        ) : (
          <div
            data-testid="recreate-list"
            style={{
              display: 'grid',
              gap: 12,
              gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            }}
          >
            {shown.map((item) => (
              <Flex
                key={item.shortcode}
                vertical
                data-testid={`recreate-row-${item.shortcode}`}
                style={{
                  border: `1px solid ${tokens.hairline}`,
                  borderRadius: 10,
                  overflow: 'hidden',
                }}
              >
                <Link
                  href={`/recreate/${encodeURIComponent(item.shortcode)}`}
                  data-testid={`recreate-open-${item.shortcode}`}
                >
                  <Thumb shortcode={item.shortcode} src={item.thumb_url} />
                </Link>

                <Flex vertical gap={4} style={{ padding: 9 }}>
                  <Flex align="center" gap={6}>
                    <Text strong style={{ fontSize: 12, flex: 1 }} ellipsis>
                      {item.username}
                    </Text>
                    <Tooltip title="Open on Instagram">
                      <Button
                        size="small"
                        type="text"
                        icon={<LinkOutlined />}
                        href={item.ig_url}
                        target="_blank"
                      />
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

                  <Text
                    style={{ fontSize: 11, color: tokens.textSecondary }}
                    ellipsis={{ tooltip: item.caption ?? '' }}
                  >
                    {item.caption || 'No caption'}
                  </Text>

                  {item.error && (
                    <Text style={{ fontSize: 10.5, color: tokens.destructive }} ellipsis>
                      {item.error}
                    </Text>
                  )}
                </Flex>
              </Flex>
            ))}
          </div>
        )}
      </Content>
    </AppShell>
  )
}
