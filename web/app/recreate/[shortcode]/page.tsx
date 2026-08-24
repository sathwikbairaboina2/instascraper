'use client'

import { ArrowLeftOutlined, CheckOutlined, LinkOutlined } from '@ant-design/icons'
import { Alert, Button, Flex, Layout, Spin, Tag, Typography } from 'antd'
import Link from 'next/link'
import { use, useEffect, useState } from 'react'

import AppShell from '@/components/AppShell'
import { useThemePref } from '@/components/ThemeProvider'
import {
  ensureMedia,
  getMedia,
  getRecreateItem,
  prepareRecreate,
  type MediaSummary,
  type RecreatePayload,
} from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

const { Content } = Layout
const { Text, Title } = Typography

type Phase = 'idle' | 'fetching' | 'preparing' | 'done' | 'error'

const POLL_MS = 1500

function SlideImage({
  shortcode,
  child,
  cached,
  dim,
}: {
  shortcode: string
  child: number
  cached: boolean
  dim: boolean
}) {
  const [failed, setFailed] = useState(false)
  if (failed) return null

  const src = cached
    ? `/api/media/${shortcode}/full?child=${child}`
    : `/api/media/${shortcode}/preview?child=${child}`

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      data-testid={`slide-image-${child}`}
      onError={() => setFailed(true)}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        opacity: dim ? 0.45 : 1,
      }}
    />
  )
}

/** The slide you are looking at, big enough to judge before committing to
 *  it. Falls back to the post's cover when a slide cannot be shown -- an
 *  expired source url, or a video child with no still. */
function BigSlide({
  shortcode,
  child,
  cached,
  fallback,
}: {
  shortcode: string
  child: number | null
  cached: boolean
  fallback?: string
}) {
  const { tokens } = useThemePref()
  const [failed, setFailed] = useState<number | null>(null)

  const usable = child !== null && failed !== child
  const src = !usable
    ? fallback
    : cached
      ? `/api/media/${shortcode}/full?child=${child}`
      : `/api/media/${shortcode}/preview?child=${child}`

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      data-testid="big-slide"
      onError={() => setFailed(child)}
      style={{
        width: '100%',
        borderRadius: 10,
        display: 'block',
        background: tokens.surface,
      }}
    />
  )
}

export default function RecreateItemPage({
  params,
}: {
  params: Promise<{ shortcode: string }>
}) {
  const { shortcode } = use(params)
  const { tokens } = useThemePref()
  const { data: item, error, refresh } = usePolling(() => getRecreateItem(shortcode), 15000)

  const [source, setSource] = useState<MediaSummary | null>(null)
  const [slides, setSlides] = useState<number[] | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [failure, setFailure] = useState<string | null>(null)
  const [payload, setPayload] = useState<RecreatePayload | null>(null)
  // Which slide the big picture is showing. Picking one should let you look
  // at it, not just tick a box you cannot check.
  const [focus, setFocus] = useState<number | null>(null)

  // The post itself is what says how many slides there are and whether the
  // files are already on disk. The recreate row is a snapshot and cannot.
  useEffect(() => {
    if (!item) return
    let cancelled = false
    void getMedia(item.username, 500, 0)
      .then((page) => {
        if (cancelled) return
        const found = page.items.find((i) => i.shortcode === shortcode) ?? null
        setSource(found)
        if (found && slides === null) {
          setSlides(
            found.child_count > 1
              ? Array.from({ length: found.child_count }, (_, n) => n + 1)
              : [0],
          )
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [item, shortcode, slides])

  useEffect(() => {
    if (item?.payload) setPayload(item.payload)
  }, [item])

  const isCarousel = (source?.child_count ?? 1) > 1
  const cached = source?.full_status === 'ready'

  async function submit() {
    setFailure(null)
    try {
      if (!cached) {
        setPhase('fetching')
        const first = await ensureMedia([shortcode])
        const why = first.errors?.[shortcode]
        if (why || first.statuses[shortcode] === 'quota') {
          // A payload naming files that were never fetched would be worse
          // than refusing outright.
          setFailure(why ?? 'the reel cap is spent, so this cannot be fetched right now')
          setPhase('error')
          return
        }
        await new Promise<void>((resolve, reject) => {
          const tick = async () => {
            try {
              const state = await ensureMedia([shortcode])
              if (state.errors?.[shortcode]) return reject(new Error(state.errors[shortcode]))
              if (state.statuses[shortcode] === 'ready') return resolve()
              setTimeout(() => void tick(), POLL_MS)
            } catch (e) {
              reject(e)
            }
          }
          void tick()
        })
      }

      setPhase('preparing')
      const built = await prepareRecreate(shortcode, isCarousel ? slides : null)
      setPayload(built)
      setPhase('done')
      await refresh()
    } catch (e) {
      setFailure(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  if (error) {
    return (
      <AppShell>
        <Content style={{ padding: 32 }}>
          <Alert type="error" showIcon title="Not lined up for recreation" description={error} />
        </Content>
      </AppShell>
    )
  }

  const busy = phase === 'fetching' || phase === 'preparing'
  const chosen = isCarousel ? (slides ?? []) : [0]

  return (
    <AppShell>
      <Content style={{ padding: '20px 24px', overflowY: 'auto' }}>
        <Link href="/recreate">
          <Button size="small" type="text" icon={<ArrowLeftOutlined />} style={{ marginBottom: 14 }}>
            Recreate
          </Button>
        </Link>

        <Flex gap={20} align="flex-start" wrap>
          <Flex vertical gap={7} style={{ width: 300, flex: 'none' }}>
            <BigSlide
              shortcode={shortcode}
              child={focus}
              cached={cached}
              fallback={item?.thumb_url}
            />
            {isCarousel && focus !== null && (
              <Text
                data-testid="focus-label"
                style={{ fontSize: 11.5, color: tokens.textSecondary }}
              >
                Slide {focus} of {source?.child_count ?? 0} ·{' '}
                {chosen.includes(focus) ? 'included' : 'not included'}
              </Text>
            )}
          </Flex>

          <Flex vertical gap={12} style={{ flex: 1, minWidth: 300 }}>
            <Flex align="center" gap={10}>
              <Title level={5} style={{ margin: 0 }}>{item?.username}</Title>
              {item && <Tag data-testid="item-status">{item.status}</Tag>}
              <Button size="small" type="text" icon={<LinkOutlined />} href={item?.ig_url} target="_blank">
                Source
              </Button>
            </Flex>

            <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap', color: tokens.textSecondary }}>
              {item?.caption || 'No caption'}
            </Text>

            {isCarousel && (
              <Flex vertical gap={6} data-testid="slide-picker">
                <Text style={{ fontSize: 11, letterSpacing: '.1em', color: tokens.textSecondary }}>
                  SLIDES
                </Text>
                {/* Slides can be looked at before anything is downloaded:
                    the urls are recorded when the post is indexed. They
                    expire, so a dead one falls back to the number rather
                    than a broken frame. */}
                <Flex gap={7} wrap>
                  {Array.from({ length: source?.child_count ?? 0 }, (_, n) => n + 1).map((n) => {
                    const on = chosen.includes(n)
                    return (
                      <div
                        key={n}
                        role="checkbox"
                        aria-checked={on}
                        data-testid={`slide-${n}`}
                        onClick={() => {
                          setFocus(n)
                          setSlides((prev) => {
                            const cur = prev ?? []
                            return cur.includes(n)
                              ? cur.filter((x) => x !== n)
                              : [...cur, n].sort((a, b) => a - b)
                          })
                        }}
                        style={{
                          cursor: 'pointer',
                          minWidth: 72,
                          height: 72,
                          borderRadius: 8,
                          display: 'grid',
                          placeItems: 'center',
                          fontSize: 13,
                          fontWeight: 600,
                          color: on ? '#fff' : tokens.textSecondary,
                          background: on ? tokens.action : tokens.surface,
                          border: `1px solid ${on ? tokens.action : tokens.hairline}`,
                          position: 'relative',
                          overflow: 'hidden',
                        }}
                      >
                        {/* Downloaded slides come from disk; the rest from
                            the urls recorded at index time, so a carousel can
                            be looked at before it is fetched. Either can be
                            missing, and then the number is what is left to
                            show. */}
                        <SlideImage
                          shortcode={shortcode}
                          child={n}
                          cached={cached}
                          dim={!on}
                        />
                        <span style={{ position: 'relative', textShadow: '0 1px 3px rgba(0,0,0,.8)' }}>
                          {on ? <CheckOutlined /> : n}
                        </span>
                      </div>
                    )
                  })}
                </Flex>
                <Text style={{ fontSize: 11, color: tokens.textSecondary }}>
                  {chosen.length} of {source?.child_count ?? 0} selected
                </Text>
              </Flex>
            )}

            <Flex gap={10} align="center">
              <Button
                type="primary"
                data-testid="prepare"
                loading={busy}
                disabled={busy || (isCarousel && chosen.length === 0)}
                onClick={() => void submit()}
              >
                {payload ? 'Prepare again' : 'Submit'}
              </Button>
              {busy && (
                <Text style={{ fontSize: 12, color: tokens.textSecondary }}>
                  {phase === 'fetching' ? 'Downloading the post first' : 'Building the payload'}
                </Text>
              )}
              {!cached && !busy && (
                <Text style={{ fontSize: 12, color: tokens.textSecondary }}>
                  Not downloaded yet — submitting will fetch it.
                </Text>
              )}
            </Flex>

            {failure && (
              <Alert type="error" showIcon data-testid="prepare-error" title="Could not prepare" description={failure} />
            )}

            {payload ? (
              <Flex vertical gap={6}>
                <Text style={{ fontSize: 11, letterSpacing: '.1em', color: tokens.textSecondary }}>
                  PAYLOAD
                </Text>
                {/* Read only: this is what a creator would be handed, not a
                    form. Editing it here would describe files that are not
                    what is on disk. */}
                <pre
                  data-testid="payload-preview"
                  style={{
                    margin: 0,
                    padding: 12,
                    borderRadius: 8,
                    background: tokens.surface,
                    border: `1px solid ${tokens.hairline}`,
                    fontSize: 11.5,
                    lineHeight: 1.5,
                    maxHeight: 340,
                    overflow: 'auto',
                  }}
                >
                  {JSON.stringify(payload, null, 2)}
                </pre>
                <Alert
                  type="info"
                  showIcon
                  data-testid="not-submitted"
                  title="Prepared, not submitted"
                  description="The files are on disk and this is the payload a creator would receive. Nothing has been put on a queue yet."
                />
              </Flex>
            ) : (
              phase !== 'error' && (
                <Alert
                  type="info"
                  showIcon
                  data-testid="no-generator"
                  title="No generator connected yet"
                  description="Submitting downloads the post and builds the payload a creator would receive. The service that consumes it is not built."
                />
              )
            )}

            {busy && <Spin size="small" />}
          </Flex>
        </Flex>
      </Content>
    </AppShell>
  )
}
