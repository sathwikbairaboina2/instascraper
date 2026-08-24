'use client'

import { Button, Empty, Flex, Layout, Segmented, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import AppShell from '@/components/AppShell'
import { useRecreateShared } from '@/components/RecreateProvider'
import { useThemePref } from '@/components/ThemeProvider'
import {
  getTagPosts,
  getTrending,
  type MediaSummary,
  type TrendWindow,
  type TrendingTag,
} from '@/lib/api'
import { compactCount } from '@/lib/format'

const { Content } = Layout
const { Text, Title } = Typography

const PAGE = 25

/** What a window looks like when nothing was published in it.
 *
 *  Worth spelling out rather than showing a generic "no results": on real
 *  Graph data the cached posts are usually older than a day, and an empty
 *  feed that does not say why is indistinguishable from a broken query.
 */
function EmptyWindow({ window }: { window: TrendWindow }) {
  return (
    <div data-testid="trending-empty">
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Text type="secondary">
            {window === 'day'
              ? 'No cached posts were published in the last 24 hours.'
              : 'No cached posts were published in the last 7 days.'}
          </Text>
        }
      />
    </div>
  )
}

/** The posts behind one tag, and a way to send them to the recreate queue.
 *
 *  Selection is local to the expanded row and thrown away when it closes:
 *  it is a scratch list on the way to the queue, and the queue is the thing
 *  that persists.
 */
function TagPosts({ tag, window }: { tag: string; window: TrendWindow }) {
  const { tokens } = useThemePref()
  const { marked, mark } = useRecreateShared()
  const [posts, setPosts] = useState<MediaSummary[] | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    void getTagPosts(tag, window, 24, 0).then((page) => {
      if (live) setPosts(page.items)
    })
    // A row closed, or its window switched, while its request was in flight
    // would otherwise write the old tag's posts into the new one.
    return () => {
      live = false
    }
  }, [tag, window])

  if (posts === null) return <Text type="secondary">Loading…</Text>

  const toggle = (shortcode: string) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(shortcode)) next.delete(shortcode)
      else next.add(shortcode)
      return next
    })

  return (
    <div data-testid={`trending-posts-${tag}`} style={{ padding: '10px 0 14px 36px' }}>
      <Flex wrap gap={8}>
        {posts.map((p) => (
          <button
            key={p.shortcode}
            data-testid={`trending-post-${p.shortcode}`}
            onClick={() => toggle(p.shortcode)}
            style={{
              padding: 0,
              border: `2px solid ${picked.has(p.shortcode) ? tokens.action : 'transparent'}`,
              borderRadius: 6,
              background: 'none',
              cursor: 'pointer',
              lineHeight: 0,
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={p.thumb_url}
              alt=""
              width={72}
              height={72}
              style={{ objectFit: 'cover', borderRadius: 4, display: 'block' }}
            />
            {marked.has(p.shortcode) && (
              <span
                data-testid={`trending-marked-${p.shortcode}`}
                style={{
                  display: 'block',
                  fontSize: 10,
                  // The button zeroes its line-height so the thumbnail has no
                  // gap under it. Inherited here that collapses this label to
                  // nothing: rendered, occupying no space, invisible.
                  lineHeight: '14px',
                  color: tokens.textSecondary,
                }}
              >
                queued
              </span>
            )}
          </button>
        ))}
      </Flex>
      <Button
        data-testid={`trending-mark-${tag}`}
        size="small"
        type="primary"
        disabled={picked.size === 0 || busy}
        loading={busy}
        style={{ marginTop: 10 }}
        onClick={async () => {
          setBusy(true)
          try {
            await mark([...picked])
            setPicked(new Set())
          } finally {
            setBusy(false)
          }
        }}
      >
        Mark for recreate{picked.size > 0 ? ` (${picked.size})` : ''}
      </Button>
    </div>
  )
}

export default function TrendingPage() {
  const { tokens } = useThemePref()
  const [window, setWindow] = useState<TrendWindow>('day')
  const [items, setItems] = useState<TrendingTag[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(async (next: TrendWindow, offset: number) => {
    setLoading(true)
    try {
      const page = await getTrending(next, PAGE, offset)
      setError(null)
      setTotal(page.total)
      // Replace at offset 0, append after it. Appending on a window switch
      // would show day and week rows in one list.
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(window, 0)
  }, [window, load])

  const more = items.length < total

  return (
    <AppShell>
      <Content style={{ padding: 24, overflowY: 'auto' }}>
        <Flex align="center" justify="space-between" style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0 }}>
            Trending hashtags
          </Title>
          <Segmented
            data-testid="trending-window"
            value={window}
            onChange={(v) => {
              setItems([])
              setTotal(0)
              setOpen(null)
              setWindow(v as TrendWindow)
            }}
            options={[
              { label: 'Day', value: 'day' },
              { label: 'Week', value: 'week' },
            ]}
          />
        </Flex>

        <Text type="secondary" style={{ fontSize: 12 }}>
          Ranked by likes, comments and views on the posts carrying each tag.
        </Text>

        {error && (
          <div style={{ marginTop: 16 }}>
            <Text type="danger" data-testid="trending-error">
              {error}
            </Text>
          </div>
        )}

        {!error && items.length === 0 && !loading && (
          <div style={{ marginTop: 24 }}>
            <EmptyWindow window={window} />
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          {items.map((row, i) => (
            <div key={row.tag}>
              <Flex
                data-testid={`trending-row-${row.tag}`}
                align="center"
                gap={12}
                onClick={() => setOpen((cur) => (cur === row.tag ? null : row.tag))}
                style={{
                  padding: '10px 12px',
                  borderBottom: `1px solid ${tokens.hairline}`,
                  cursor: 'pointer',
                }}
              >
                <Text type="secondary" style={{ width: 24, textAlign: 'right' }}>
                  {i + 1}
                </Text>
                <Text strong style={{ flex: 1 }} data-testid={`trending-expand-${row.tag}`}>
                  #{row.tag}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {row.post_count} {row.post_count === 1 ? 'post' : 'posts'}
                </Text>
                <Text
                  data-testid={`trending-score-${row.tag}`}
                  style={{ width: 72, textAlign: 'right' }}
                >
                  {compactCount(row.score)}
                </Text>
              </Flex>
              {open === row.tag && <TagPosts tag={row.tag} window={window} />}
            </div>
          ))}
        </div>

        {more && (
          <Button
            data-testid="trending-load-more"
            block
            loading={loading}
            style={{ marginTop: 16 }}
            onClick={() => void load(window, items.length)}
          >
            Load more
          </Button>
        )}
      </Content>
    </AppShell>
  )
}
