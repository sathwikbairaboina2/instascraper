'use client'

import {
  CloseOutlined,
  LinkOutlined,
  ReloadOutlined,
  SearchOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Empty,
  Flex,
  Input,
  Layout,
  Space,
  Spin,
  Tooltip,
  Typography,
  theme,
} from 'antd'
import { useCallback, useMemo, useState } from 'react'

import AppShell from '@/components/AppShell'
import Lightbox from '@/components/Lightbox'
import MediaTile from '@/components/MediaTile'
import SelectionBar from '@/components/SelectionBar'
import SidePanel from '@/components/SidePanel'
import {
  addDirectUrls,
  ensureMedia,
  listDirectUrls,
  mediaFullPath,
  removeDirectUrl,
  type DirectUrlItem,
  type MediaSummary,
} from '@/lib/api'
import { matchesKind, type KindFilter } from '@/lib/useFilters'
import { usePolling } from '@/lib/usePolling'
import { useRecreateShared } from '@/components/RecreateProvider'
import { useSelection } from '@/lib/useSelection'

const { Content } = Layout
const { Text, Paragraph } = Typography

const TABS = ['all', 'posts', 'reels', 'recreate'] as const
type Tab = (typeof TABS)[number]

export default function DirectUrlsPage() {
  const { token } = theme.useToken()

  const [input, setInput] = useState('')
  const [invalid, setInvalid] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const [preview, setPreview] = useState<MediaSummary | null>(null)
  const [base, setBase] = useState('direct')
  // Phones show the inspector as a sheet; see SidePanel.
  const [sheet, setSheet] = useState(false)
  const closeSheet = useCallback(() => setSheet(false), [])

  const { data, refresh } = usePolling(listDirectUrls, 4000)
  const recreate = useRecreateShared()

  const items = useMemo(() => data?.items ?? [], [data])
  const indexed = useMemo(
    () => items.filter((i): i is DirectUrlItem & { media: MediaSummary } => i.media !== null),
    [items],
  )
  const waiting = useMemo(() => items.filter((i) => i.media === null), [items])
  const owners = useMemo(
    () => new Map(indexed.map((i) => [i.shortcode, i.username ?? ''])),
    [indexed],
  )

  const visible = useMemo(
    () =>
      tab === 'all'
        ? indexed
        : indexed.filter((i) => matchesKind(i.media, tab as KindFilter, recreate.marked)),
    [indexed, tab, recreate.marked],
  )
  const ids = useMemo(() => visible.map((i) => i.shortcode), [visible])
  const selection = useSelection(ids)

  const selectedItems = useMemo(
    () =>
      selection.selected
        .map((c) => indexed.find((i) => i.shortcode === c)?.media)
        .filter(Boolean) as MediaSummary[],
    [selection.selected, indexed],
  )
  const one = selectedItems.length === 1 ? selectedItems[0] : undefined
  const readyCount = selectedItems.filter((i) => i.full_status === 'ready').length
  const fileCount = selectedItems.reduce((n, i) => n + (i.child_count || 1), 0)
  const pending = selectedItems.length - readyCount

  const counts = useMemo(
    () => ({
      fetched: indexed.length,
      fetching: waiting.filter((i) => i.status === 'pending').length,
      failed: waiting.filter((i) => i.status === 'failed').length,
    }),
    [indexed, waiting],
  )

  const submit = async () => {
    // Commas separate too: share sheets hand out comma-joined lists, and a
    // whitespace-only split turned one of those into a single string whose
    // trailing links were swallowed by the query-string part of the pattern.
    const urls = input
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (urls.length === 0) return
    setBusy(true)
    try {
      const result = await addDirectUrls(urls)
      setInvalid(result.invalid)
      if (result.invalid.length === 0) setInput('')
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const onRetry = async (item: DirectUrlItem) => {
    await addDirectUrls([item.url])
    await refresh()
  }

  const onRemove = async (item: DirectUrlItem) => {
    await removeDirectUrl(item.shortcode)
    await refresh()
  }

  const previewLive = useMemo(
    () =>
      preview
        ? indexed.find((i) => i.shortcode === preview.shortcode)?.media ?? preview
        : null,
    [preview, indexed],
  )

  return (
    <AppShell>
      {/* The paste bar sits where a profile page puts its header: the input
          is the identity of this page the way the avatar is of that one. */}
      <div
        className="direct-head"
        style={{
          flex: 'none',
          padding: '24px 32px 18px',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Text strong style={{ fontSize: 19, letterSpacing: '-0.02em', display: 'block' }}>
          Direct URLs
        </Text>
        <Text type="secondary" style={{ fontSize: 12.5 }}>
          Paste a post or reel link. It is fetched, cached and treated like any profile
          post — download it or queue it for recreation.
        </Text>
        <Space.Compact style={{ width: '100%', maxWidth: 700, marginTop: 14, display: 'flex' }}>
          <Input
            data-testid="url-input"
            placeholder="https://www.instagram.com/reel/…"
            prefix={<LinkOutlined style={{ color: token.colorTextQuaternary }} />}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={() => void submit()}
          />
          <Button
            type="primary"
            data-testid="url-submit"
            icon={<SearchOutlined />}
            loading={busy}
            onClick={() => void submit()}
          >
            Fetch
          </Button>
        </Space.Compact>
        <Text type="secondary" style={{ fontSize: 11.5, display: 'block', marginTop: 7 }}>
          Accepts instagram.com/p/&lt;code&gt; and instagram.com/reel/&lt;code&gt;. Paste
          several links at once to queue them all. Pasting a failed link again retries it.
        </Text>
        {invalid.length > 0 && (
          <Alert
            type="warning"
            showIcon
            closable
            data-testid="url-invalid"
            onClose={() => setInvalid([])}
            style={{ marginTop: 10, maxWidth: 700 }}
            title={`Not Instagram post links: ${invalid.join(', ')}`}
          />
        )}
      </div>

      {/* Same underline-from-above tab bar as the profile page. */}
      <Flex
        className="kind-tabs"
        justify="center"
        gap={44}
        data-testid="direct-tabs"
        style={{ flex: 'none', borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        {TABS.map((key) => {
          const on = tab === key
          return (
            <div
              key={key}
              role="tab"
              className="kind-tab"
              aria-selected={on}
              onClick={() => setTab(key)}
              style={{
                cursor: 'pointer',
                padding: '11px 0 9px',
                marginTop: -1,
                borderTop: `1px solid ${on ? token.colorText : 'transparent'}`,
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: '.1em',
                color: on ? token.colorText : token.colorTextSecondary,
              }}
            >
              {key.toUpperCase()}
            </div>
          )
        })}
      </Flex>

      <Flex
        className="filter-bar"
        align="center"
        gap={10}
        wrap
        style={{
          padding: '10px 16px',
          flex: 'none',
          background: token.colorBgLayout,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Text type="secondary" style={{ fontSize: 12 }} data-testid="direct-counts">
          {counts.fetched} fetched
          {counts.fetching > 0 && ` · ${counts.fetching} fetching`}
          {counts.failed > 0 && ` · ${counts.failed} failed`}
        </Text>
        <div className="filter-gap" style={{ flex: 1 }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {visible.length} of {indexed.length} shown
        </Text>
        <Button size="small" data-testid="select-all" disabled={visible.length === 0} onClick={selection.selectAll}>
          Select all shown
        </Button>
      </Flex>

      <Layout className="page-body" style={{ overflow: 'hidden', flex: 1, minHeight: 0 }}>
        <Content
          className={selectedItems.length > 0 ? 'has-bar' : undefined}
          style={{ overflowY: 'auto', padding: 16, background: token.colorBgLayout }}
        >
          {items.length === 0 ? (
            <Empty
              description="Nothing fetched yet — paste a link above"
              style={{ marginTop: 90 }}
              data-testid="direct-empty"
            />
          ) : (
            <div
              className="media-grid"
              data-testid="media-grid"
              style={{
                display: 'grid',
                gap: 10,
                gridTemplateColumns: 'repeat(auto-fill, minmax(232px, 1fr))',
                gridAutoRows: '232px',
              }}
            >
              {tab === 'all' &&
                waiting.map((item) => (
                  <div
                    key={item.shortcode}
                    className="direct-wait"
                    data-testid={`direct-${item.status}-${item.shortcode}`}
                    style={{
                      borderRadius: token.borderRadiusLG,
                      background: token.colorBgContainer,
                      boxShadow: `0 0 0 1px ${token.colorBorderSecondary}`,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 10,
                      padding: 14,
                      textAlign: 'center',
                    }}
                  >
                    {item.status === 'pending' ? (
                      <>
                        <Spin />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          Fetching…
                        </Text>
                      </>
                    ) : (
                      <>
                        <WarningOutlined style={{ fontSize: 20, color: token.colorError }} />
                        <Tooltip title={item.error}>
                          <Text type="danger" style={{ fontSize: 12 }} ellipsis>
                            {item.error ?? 'Fetch failed'}
                          </Text>
                        </Tooltip>
                        <Space size={4}>
                          <Button
                            size="small"
                            data-testid={`direct-retry-${item.shortcode}`}
                            icon={<ReloadOutlined />}
                            onClick={() => void onRetry(item)}
                          >
                            Retry
                          </Button>
                          <Button
                            size="small"
                            type="text"
                            data-testid={`direct-dismiss-${item.shortcode}`}
                            icon={<CloseOutlined />}
                            onClick={() => void onRemove(item)}
                          />
                        </Space>
                      </>
                    )}
                    <Text type="secondary" style={{ fontSize: 10.5 }} code>
                      {item.shortcode}
                    </Text>
                  </div>
                ))}
              {visible.map((item) => (
                <MediaTile
                  key={item.shortcode}
                  item={item.media}
                  marked={recreate.marked.has(item.shortcode)}
                  onRecreate={() => void recreate.toggle(item.shortcode)}
                  selected={selection.isSelected(item.shortcode)}
                  onToggle={(shift) => selection.toggle(item.shortcode, shift)}
                  onRetry={async () => {
                    await ensureMedia([item.shortcode], true)
                    await refresh()
                  }}
                  onPreview={() => setPreview(item.media)}
                />
              ))}
            </div>
          )}
        </Content>

        <SidePanel
          count={selectedItems.length}
          open={sheet}
          onOpen={() => setSheet(true)}
          onClose={closeSheet}
        >
          {selectedItems.length === 0 && (
            <Flex vertical align="center" justify="center" gap={10} style={{ padding: 28, height: '100%' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Nothing selected" />
              <Text type="secondary" style={{ fontSize: 12, textAlign: 'center' }}>
                Click a tile to inspect it. Shift click to take a range.
              </Text>
            </Flex>
          )}

          {one && (
            <div style={{ padding: 16 }}>
              <img
                src={
                  one.full_status === 'ready'
                    ? mediaFullPath(one.shortcode, one.child_count > 1 ? 1 : 0)
                    : one.thumb_url
                }
                alt=""
                style={{ width: '100%', borderRadius: token.borderRadiusLG, display: 'block' }}
              />
              <Paragraph style={{ margin: '14px 0 12px', fontSize: 13 }} ellipsis={{ rows: 3 }}>
                {one.caption || 'No caption'}
              </Paragraph>
              <div style={{ fontSize: 12 }}>
                <Flex gap={8} style={{ marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 11, width: 78, flex: 'none' }}>Shortcode</Text>
                  <Text code copyable style={{ fontSize: 11 }}>{one.shortcode}</Text>
                </Flex>
                {owners.get(one.shortcode) && (
                  <Flex gap={8} style={{ marginBottom: 6 }}>
                    <Text type="secondary" style={{ fontSize: 11, width: 78, flex: 'none' }}>Owner</Text>
                    <Text style={{ fontSize: 12 }}>@{owners.get(one.shortcode)}</Text>
                  </Flex>
                )}
                <Flex gap={8} style={{ marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 11, width: 78, flex: 'none' }}>Kind</Text>
                  <Text style={{ fontSize: 12 }}>
                    {one.child_count > 1 ? `carousel, ${one.child_count} slides` : one.kind}
                  </Text>
                </Flex>
                <Flex gap={8} style={{ marginBottom: 6 }}>
                  <Text type="secondary" style={{ fontSize: 11, width: 78, flex: 'none' }}>Cached</Text>
                  {one.full_status === 'ready' ? (
                    <Text type="success" style={{ fontSize: 12 }}>yes</Text>
                  ) : one.full_status === 'failed' ? (
                    <Text type="danger" style={{ fontSize: 12 }}>{one.full_error}</Text>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {one.full_status === 'none' ? 'not yet' : one.full_status}
                    </Text>
                  )}
                </Flex>
              </div>
              <Space style={{ marginTop: 12 }} size={8}>
                <Button icon={<LinkOutlined />} href={one.ig_url} target="_blank">
                  Instagram
                </Button>
              </Space>
            </div>
          )}

          {selectedItems.length >= 1 && (
            <div
              style={{
                padding: 16,
                borderTop: one ? `1px solid ${token.colorBorderSecondary}` : undefined,
              }}
            >
              <Text
                data-testid="selection-count"
                style={{
                  display: 'block',
                  fontSize: 34,
                  fontWeight: 700,
                  letterSpacing: '-0.035em',
                  lineHeight: 1.05,
                }}
              >
                {selectedItems.length} selected
              </Text>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                {fileCount} files · {readyCount} already cached
              </Text>

              <div style={{ height: 16 }} />

              <SelectionBar
                shortcodes={selection.selected}
                base={base}
                onBase={setBase}
                fileCount={fileCount}
                onClear={selection.clear}
                onDone={refresh}
                onRecreate={() => recreate.mark(selection.selected)}
                markedCount={selection.selected.filter((sc) => recreate.marked.has(sc)).length}
              />

              {pending > 0 && (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 16 }}
                  title={`${pending} still to fetch`}
                  description="Uncached posts are queued one at a time, paced to stay under Instagram's limits."
                />
              )}
            </div>
          )}
        </SidePanel>
      </Layout>

      {previewLive && (
        <Lightbox
          item={previewLive}
          onClose={() => setPreview(null)}
          onFetch={async (shortcode) => {
            await ensureMedia([shortcode])
            await refresh()
          }}
        />
      )}
    </AppShell>
  )
}
