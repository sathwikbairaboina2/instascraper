'use client'

import {
  AppstoreOutlined,
  BorderOuterOutlined,
  ClearOutlined,
  CloudDownloadOutlined,
  ExpandOutlined,
  LinkOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Avatar,
  Button,
  Checkbox,
  Descriptions,
  Divider,
  Empty,
  Flex,
  Input,
  Layout,
  Progress,
  Segmented,
  Skeleton,
  Spin,
  Space,
  Tag,
  Tooltip,
  Typography,
  theme,
} from 'antd'
import { useRouter } from 'next/navigation'
import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import AppShell from '@/components/AppShell'
import ProfileHeader from '@/components/ProfileHeader'
import Lightbox from '@/components/Lightbox'
import MediaTile from '@/components/MediaTile'
import SelectionBar from '@/components/SelectionBar'
import {
  ApiError,
  clearCache,
  createDownload,
  ensureMedia,
  getMedia,
  getProfile,
  loadMore,
  setTracked,
  syncProfile,
  type MediaSummary,
} from '@/lib/api'
import {
  deleteSelection,
  loadSelections,
  saveSelection,
  type SavedSelection,
} from '@/lib/savedSelections'
import {
  applyFilters,
  EMPTY_FILTERS,
  matchesKind,
  type Filters,
  type KindFilter,
} from '@/lib/useFilters'
import { usePolling } from '@/lib/usePolling'
import { useRecreateShared } from '@/components/RecreateProvider'
import { useSelection } from '@/lib/useSelection'

const { Content, Sider } = Layout
const { Text, Paragraph } = Typography

const PAGE = 120

export default function ProfilePage({ params }: { params: Promise<{ username: string }> }) {
  const { username } = use(params)
  const { token } = theme.useToken()

  const [busy, setBusy] = useState(false)
  const [windowSize, setWindowSize] = useState(PAGE)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [density, setDensity] = useState('Comfortable')
  const [preview, setPreview] = useState<MediaSummary | null>(null)
  const [base, setBase] = useState('')
  const [saved, setSaved] = useState<SavedSelection[]>([])
  const [saveName, setSaveName] = useState('')

  const { data: profile, error, cause, refresh: refreshProfile } = usePolling(
    () => getProfile(username),
    10000,
  )

  // A 404 with no recorded error is not a failure: the profile has simply
  // never been fetched, or is being fetched right now. The api draws that
  // distinction and the screen has to honour it, or every new lookup opens
  // on a red alert that disappears by itself a few seconds later.
  const detail =
    cause instanceof ApiError && cause.status === 404
      ? ((cause.body as { detail?: { last_error?: string | null } } | null)?.detail ?? null)
      : null
  const syncing = detail !== null && !detail.last_error

  // Reached by url rather than through the search box, nothing has queued the
  // work, so the screen would wait on a fetch that was never asked for.
  // enqueue_unique makes asking twice harmless.
  const asked = useRef<string | null>(null)
  useEffect(() => {
    if (!syncing || asked.current === username) return
    asked.current = username
    void syncProfile(username).catch(() => {})
  }, [syncing, username])
  const { data: media, refresh: refreshMedia } = usePolling(
    () => getMedia(username, windowSize, 0),
    4000,
  )

  const recreate = useRecreateShared()
  const router = useRouter()

  useEffect(() => setSaved(loadSelections(username)), [username])


  const total = media?.total ?? 0
  useEffect(() => {
    if (total > windowSize) setWindowSize(total)
  }, [total, windowSize])
  useEffect(() => {
    refreshMedia()
  }, [windowSize, refreshMedia])

  const items = useMemo(() => media?.items ?? [], [media])
  const visible = useMemo(
    () => applyFilters(items, filters, recreate.marked),
    [items, filters, recreate.marked],
  )
  // The tab is the partition, not a filter within one. "2 of 10" on the
  // reels tab counts posts the tab was never going to show; the honest
  // denominator is what the tab holds before search and cached-only
  // narrow it further.
  const inTab = useMemo(
    () => items.filter((item) => matchesKind(item, filters.kind, recreate.marked)),
    [items, filters.kind, recreate.marked],
  )
  const ids = useMemo(() => visible.map((i) => i.shortcode), [visible])
  const selection = useSelection(ids)

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    setFilters((prev) => ({ ...prev, [key]: value }))

  // Some accounts post almost nothing but reels, and POSTS opening on one
  // tile out of twelve is a poor first impression. Open on whichever tab
  // holds more.
  //
  // Re-decided on every payload rather than latched on the first: the page
  // arrives a thumbnail at a time, newest first, so an early list can be all
  // reels for an account that mostly posts photos. Waiting for the count to
  // settle does not work here -- usePolling deliberately skips re-rendering
  // an unchanged payload, so "the same list twice" is a render that never
  // comes. Deciding again each time data actually changes converges on the
  // right answer and stops when the data does.
  //
  // Stops entirely once a tab is chosen: an empty grid you asked for is an
  // answer, not a mistake to correct.
  const tabPicked = useRef(false)
  useEffect(() => {
    tabPicked.current = false
  }, [username])
  useEffect(() => {
    if (tabPicked.current || items.length === 0) return
    const posts = items.filter((item) => matchesKind(item, 'posts')).length
    const reels = items.filter((item) => matchesKind(item, 'reels')).length
    const want: KindFilter = reels > posts ? 'reels' : 'posts'
    if (want !== filters.kind) setFilters((prev) => ({ ...prev, kind: want }))
  }, [items, filters.kind])
  const filtersActive =
    filters.kind !== 'posts' || filters.cachedOnly || filters.query.trim() !== ''

  const onRetry = useCallback(
    async (shortcode: string) => {
      await ensureMedia([shortcode], true)
      await refreshMedia()
    },
    [refreshMedia],
  )

  const onLoadMore = useCallback(async () => {
    setBusy(true)
    try {
      await loadMore(username)
      await refreshMedia()
    } finally {
      setBusy(false)
    }
  }, [username, refreshMedia])

  const previewLive = useMemo(
    () => (preview ? items.find((i) => i.shortcode === preview.shortcode) ?? preview : null),
    [preview, items],
  )

  const selectedItems = useMemo(
    () => selection.selected.map((c) => items.find((i) => i.shortcode === c)).filter(Boolean) as MediaSummary[],
    [selection.selected, items],
  )
  const one = selectedItems.length === 1 ? selectedItems[0] : undefined
  const readyCount = selectedItems.filter((i) => i.full_status === 'ready').length
  const fileCount = selectedItems.reduce((n, i) => n + (i.child_count || 1), 0)
  const pending = selectedItems.length - readyCount

  const tile = density === 'Compact' ? 158 : 232

  if (syncing) {
    return (
      <AppShell active={username}>
        <Content style={{ padding: 32 }}>
          <Flex vertical align="center" gap={14} style={{ marginTop: 120 }} data-testid="profile-loading">
            <Spin size="large" />
            <Text strong>Fetching {username}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Reading the profile and its first posts. One request at a time.
            </Text>
          </Flex>
        </Content>
      </AppShell>
    )
  }

  if (error) {
    return (
      <AppShell active={username}>
        <Content style={{ padding: 32 }}>
          <Alert type="error" showIcon title="Cannot load this profile" description={error} data-testid="profile-error" />
        </Content>
      </AppShell>
    )
  }

  if (profile?.is_private) {
    return (
      <AppShell active={username}>
        <Content style={{ padding: 32 }}>
          <Alert
            type="warning"
            showIcon
            data-testid="profile-private"
            title={`${username} is private`}
            description="This tool only supports public profiles."
          />
        </Content>
      </AppShell>
    )
  }

  return (
    <AppShell active={username}>
      <ProfileHeader
        profile={profile}
        indexed={media?.total ?? 0}
        actions={
          <>
          <Button
            type="text"
            data-testid="track-toggle"
            icon={profile?.tracked ? <StarFilled /> : <StarOutlined />}
            style={{ color: profile?.tracked ? token.colorWarning : undefined }}
            onClick={async () => {
              await setTracked(username, !profile?.tracked)
              refreshProfile()
            }}
          >
            {profile?.tracked ? 'Tracked' : 'Track'}
          </Button>
          <Tooltip title="Refresh now">
            <Button
              shape="circle"
              data-testid="refresh"
              icon={<ReloadOutlined />}
              onClick={() => {
                refreshProfile()
                refreshMedia()
              }}
            />
          </Tooltip>
          <Button
            type="text"
            data-testid="clear-cache"
            icon={<ClearOutlined />}
            onClick={async () => {
              await clearCache(username)
              selection.clear()
              refreshMedia()
              refreshProfile()
            }}
          >
            Clear cache
          </Button>
          </>
        }
      />

      {/* Instagram's centred bar with the active item underlined from above.
          A Segmented chip read as one more filter; this reads as a section. */}
      <Flex
        justify="center"
        gap={44}
        data-testid="profile-tabs"
        style={{
          flex: 'none',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        {(['posts', 'reels', 'saved', 'recreate'] as KindFilter[]).map((kind) => {
          const on = filters.kind === kind
          return (
            <div
              key={kind}
              role="tab"
              aria-selected={on}
              onClick={() => {
                tabPicked.current = true
                set('kind', kind)
              }}
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
              {kind.toUpperCase()}
            </div>
          )
        })}
      </Flex>

      <Flex
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
        <Input
          size="small"
          data-testid="filter-query"
          placeholder="Search captions"
          value={filters.query}
          onChange={(e) => set('query', e.target.value)}
          prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
          style={{ width: 200 }}
          allowClear
        />
        <Checkbox
          data-testid="filter-cached"
          checked={filters.cachedOnly}
          onChange={(e) => set('cachedOnly', e.target.checked)}
        >
          Cached only
        </Checkbox>
        <div style={{ flex: 1 }} />
        <Text type="secondary" style={{ fontSize: 12 }} data-testid="filter-count">
          {visible.length} of {inTab.length} shown
        </Text>
        {filtersActive && (
          <Button size="small" data-testid="filter-reset" onClick={() => setFilters(EMPTY_FILTERS)}>
            Reset
          </Button>
        )}
        <Segmented
          size="small"
          value={density}
          onChange={(v) => setDensity(v as string)}
          options={[
            { value: 'Comfortable', icon: <BorderOuterOutlined /> },
            { value: 'Compact', icon: <AppstoreOutlined /> },
          ]}
        />
        <Button size="small" data-testid="select-all" disabled={visible.length === 0} onClick={selection.selectAll}>
          Select all shown
        </Button>
        <Button size="small" data-testid="load-more" disabled={media?.exhausted || busy} loading={busy} onClick={onLoadMore}>
          {media?.exhausted ? 'All loaded' : 'Load more'}
        </Button>
      </Flex>

      <Layout style={{ overflow: 'hidden', flex: 1, minHeight: 0 }}>
        <Content style={{ overflowY: 'auto', padding: 16, background: token.colorBgLayout }}>
          {!media ? (
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: `repeat(auto-fill, minmax(${tile}px, 1fr))` }}>
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton.Node key={i} active style={{ width: '100%', height: tile }}>
                  <span />
                </Skeleton.Node>
              ))}
            </div>
          ) : visible.length === 0 ? (
            <Empty description="No posts match these filters" style={{ marginTop: 90 }}>
              {filtersActive && (
                <Button size="small" onClick={() => setFilters(EMPTY_FILTERS)}>Reset filters</Button>
              )}
            </Empty>
          ) : (
            <div
              data-testid="media-grid"
              style={{
                display: 'grid',
                gap: 10,
                gridTemplateColumns: `repeat(auto-fill, minmax(${tile}px, 1fr))`,
                gridAutoRows: `${tile}px`,
              }}
            >
              {visible.map((item, idx) => (
                <div key={item.shortcode} style={idx === 0 ? { gridColumn: 'span 2', gridRow: 'span 2' } : undefined}>
                  <MediaTile
                    item={item}
                    marked={recreate.marked.has(item.shortcode)}
                    onRecreate={() => void recreate.toggle(item.shortcode)}
                    selected={selection.isSelected(item.shortcode)}
                    openHref={
                      filters.kind === 'recreate'
                        ? `/recreate/${encodeURIComponent(item.shortcode)}`
                        : undefined
                    }
                    onOpen={() =>
                      router.push(`/recreate/${encodeURIComponent(item.shortcode)}`)
                    }
                    onToggle={(shift) => selection.toggle(item.shortcode, shift)}
                    onRetry={() => onRetry(item.shortcode)}
                    onPreview={() => setPreview(item)}
                  />
                </div>
              ))}
            </div>
          )}
        </Content>

        <Sider
          width={300}
          style={{
            background: token.colorBgContainer,
            borderLeft: `1px solid ${token.colorBorderSecondary}`,
            overflowY: 'auto',
          }}
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
                src={one.full_status === 'ready' ? `/api/media/${one.shortcode}/full?child=${one.child_count > 1 ? 1 : 0}` : one.thumb_url}
                alt=""
                style={{ width: '100%', borderRadius: token.borderRadiusLG, display: 'block' }}
              />
              <Paragraph style={{ margin: '14px 0 12px', fontSize: 13 }} ellipsis={{ rows: 3 }}>
                {one.caption || 'No caption'}
              </Paragraph>
              <Descriptions
                size="small"
                column={1}
                colon={false}
                labelStyle={{ fontSize: 11, color: token.colorTextTertiary, width: 78 }}
                contentStyle={{ fontSize: 12 }}
                items={[
                  { key: 'c', label: 'Shortcode', children: <Text code copyable style={{ fontSize: 11 }}>{one.shortcode}</Text> },
                  { key: 'k', label: 'Kind', children: one.child_count > 1 ? `carousel, ${one.child_count} slides` : one.kind },
                  { key: 't', label: 'Posted', children: one.taken_at.slice(0, 10) },
                  {
                    key: 's',
                    label: 'Cached',
                    children:
                      one.full_status === 'ready' ? <Text type="success">yes</Text>
                      : one.full_status === 'failed' ? <Text type="danger">{one.full_error}</Text>
                      : <Text type="secondary">{one.full_status === 'none' ? 'not yet' : one.full_status}</Text>,
                  },
                ]}
              />
              <Space style={{ marginTop: 16 }} size={8}>
                <Button icon={<ExpandOutlined />} onClick={() => setPreview(one)}>Preview</Button>
                <Button icon={<LinkOutlined />} href={one.ig_url} target="_blank">Instagram</Button>
              </Space>
            </div>
          )}

          {selectedItems.length >= 1 && (
            <div style={{ padding: 16, borderTop: one ? `1px solid ${token.colorBorderSecondary}` : undefined }}>
              <Text
                data-testid="selection-count"
                style={{ display: 'block', fontSize: 34, fontWeight: 700, letterSpacing: '-0.035em', lineHeight: 1.05 }}
              >
                {selectedItems.length} selected
              </Text>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                {fileCount} files · {readyCount} already cached
              </Text>

              <Divider style={{ margin: '16px 0' }} />

              <SelectionBar
                shortcodes={selection.selected}
                base={base}
                onBase={setBase}
                fileCount={fileCount}
                onClear={selection.clear}
                onDone={refreshMedia}
                onRecreate={() => recreate.mark(selection.selected)}
                markedCount={selection.selected.filter((sc) => recreate.marked.has(sc)).length}
              />

              {pending > 0 && (
                <>
                  <Divider style={{ margin: '16px 0' }} />
                  <Alert
                    type="info"
                    showIcon
                    title={`${pending} still to fetch`}
                    description="Uncached posts are queued one at a time, paced to stay under Instagram's limits."
                  />
                </>
              )}

            </div>
          )}

          {(saved.length > 0 || selectedItems.length > 0) && (
            <div style={{ padding: 16, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
              <Divider style={{ margin: '16px 0' }} />
            <Text style={{ fontSize: 12, display: 'block', marginBottom: 7 }}>Save this selection</Text>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                data-testid="save-name"
                placeholder="name it"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
              />
              <Button
                data-testid="save-selection"
                disabled={!saveName.trim()}
                onClick={() => {
                  setSaved(saveSelection(username, saveName, selection.selected))
                  setSaveName('')
                }}
              >
                Save
              </Button>
            </Space.Compact>
            {saved.length > 0 && (
              <Flex wrap gap={6} style={{ marginTop: 10 }}>
                {saved.map((sel) => (
                  <Tag
                    key={sel.name}
                    closable
                    data-testid={`load-selection-${sel.name}`}
                    onClose={(e) => {
                      e.preventDefault()
                      setSaved(deleteSelection(username, sel.name))
                    }}
                    closeIcon={<span data-testid={`delete-selection-${sel.name}`}>x</span>}
                    onClick={() => {
                      selection.clear()
                      sel.shortcodes.forEach((sc) => selection.toggle(sc))
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {sel.name} ({sel.shortcodes.length})
                  </Tag>
                ))}
              </Flex>
            )}
            </div>
          )}
        </Sider>
      </Layout>

      {previewLive && (
        <Lightbox
          item={previewLive}
          onClose={() => setPreview(null)}
          onFetch={async (shortcode) => {
            await ensureMedia([shortcode])
            await refreshMedia()
          }}
        />
      )}
    </AppShell>
  )
}
