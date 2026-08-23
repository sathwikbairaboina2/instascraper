'use client'

import {
  AppstoreOutlined,
  BorderOuterOutlined,
  BulbOutlined,
  CheckCircleFilled,
  ClearOutlined,
  CloudDownloadOutlined,
  ExpandOutlined,
  FieldTimeOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  LinkOutlined,
  ReloadOutlined,
  SearchOutlined,
  StarFilled,
  ThunderboltFilled,
} from '@ant-design/icons'
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Checkbox,
  ConfigProvider,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Flex,
  Input,
  Layout,
  List,
  Progress,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
  theme,
} from 'antd'
import { useMemo, useState } from 'react'

import { mono, sans } from './fonts'

const { Sider, Content } = Layout
const { Text, Paragraph } = Typography

/* ---------------------------------------------------------------- themes */
/* One accent each, picked so it survives sitting next to photography.
   `onAccent` is the text colour that rides on top of the accent: antd puts
   white there by default, which fails contrast on the lighter accents. */
type Themed = {
  name: string
  accent: string
  onAccent: string
  darkBg: string
  lightBg: string
  note: string
}

const THEMES: Themed[] = [
  { name: 'Graphite', accent: '#5b8cff', onAccent: '#ffffff', darkBg: '#0a0c10', lightBg: '#f5f6f8', note: 'Neutral and quiet. The photography carries the colour.' },
  { name: 'Coral',    accent: '#ff6b57', onAccent: '#1b0d09', darkBg: '#0d0a0a', lightBg: '#fbf6f4', note: 'Warm and energetic without competing with the images.' },
  { name: 'Lime',     accent: '#ccff42', onAccent: '#12160a', darkBg: '#0a0b0d', lightBg: '#f7f9f0', note: 'Loudest option. Reads current, fights busy thumbnails.' },
  { name: 'Iris',     accent: '#8b7bff', onAccent: '#12102a', darkBg: '#0b0a10', lightBg: '#f7f5fc', note: 'Soft and social. Familiar to anyone who uses Linear or Arc.' },
  { name: 'Sea',      accent: '#2fd6b0', onAccent: '#04201a', darkBg: '#080d0c', lightBg: '#f2faf7', note: 'Cool and calm. Good contrast on dark, easy for long sessions.' },
]

/* ------------------------------------------------------------------ data */
type Status = 'none' | 'queued' | 'fetching' | 'ready' | 'failed'
type Kind = 'photo' | 'reel' | 'carousel'

type Item = {
  code: string
  kind: Kind
  children: number
  status: Status
  done?: number
  error?: string
  taken: string
  caption: string
  bytes?: string
}

const ITEMS: Item[] = [
  { code: 'C8xR2mQpLtA', kind: 'carousel', children: 3, status: 'ready', taken: '2026-08-14', caption: 'Pegasus 41 lookbook, shot on location in Hokkaido', bytes: '14.2 MB' },
  { code: 'C8vNq1KdWzE', kind: 'carousel', children: 3, status: 'fetching', done: 2, taken: '2026-08-12', caption: 'Three colourways, one silhouette' },
  { code: 'C8tHy7BcXnR', kind: 'reel', children: 1, status: 'queued', taken: '2026-08-11', caption: 'Track session, 400m repeats' },
  { code: 'C8qLd4VfMks', kind: 'photo', children: 1, status: 'failed', error: 'connection reset by peer', taken: '2026-08-09', caption: 'Studio detail, midsole stitching' },
  { code: 'C8nGb9TrPwY', kind: 'photo', children: 1, status: 'ready', taken: '2026-08-07', caption: 'Morning run, Shibuya crossing', bytes: '3.1 MB' },
  { code: 'C8kFa2NsQvD', kind: 'carousel', children: 3, status: 'none', taken: '2026-08-05', caption: 'Archive series, 1987 to 2026' },
  { code: 'C8hEz5MpLbC', kind: 'photo', children: 1, status: 'none', taken: '2026-08-03', caption: 'Team kit reveal' },
  { code: 'C8fDx8JnKra', kind: 'reel', children: 1, status: 'none', taken: '2026-08-01', caption: 'Sixty seconds with the design team' },
  { code: 'C8cCw3HmJqZ', kind: 'photo', children: 1, status: 'none', taken: '2026-07-29', caption: 'Outsole geometry' },
  { code: 'C8aBv6GlHpX', kind: 'photo', children: 1, status: 'ready', taken: '2026-07-27', caption: 'Coastal trail, first light', bytes: '4.8 MB' },
  { code: 'C89Au1FkGoW', kind: 'carousel', children: 4, status: 'none', taken: '2026-07-24', caption: 'Materials study' },
  { code: 'C87zT4EjFnV', kind: 'photo', children: 1, status: 'none', taken: '2026-07-22', caption: 'Warehouse, before opening' },
]

const PROFILES = [
  { name: 'nike', posts: 248, cached: 31 },
  { name: 'apple', posts: 112, cached: 0 },
  { name: 'patagonia', posts: 403, cached: 76 },
  { name: 'teenageengineering', posts: 88, cached: 12 },
]

const thumb = (code: string, size: number) => `https://picsum.photos/seed/${code}/${size}/${size}`

/* ------------------------------------------------------------------ tile */
function Tile({
  item,
  size,
  selected,
  onToggle,
}: {
  item: Item
  size: number
  selected: boolean
  onToggle: () => void
}) {
  const { token } = theme.useToken()
  const [hover, setHover] = useState(false)
  const busy = item.status === 'fetching' || item.status === 'queued'
  const show = hover || selected

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onToggle}
      style={{
        position: 'relative',
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
        src={thumb(item.code, size)}
        alt=""
        loading="lazy"
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          display: 'block',
          filter: item.status === 'none' && !show ? 'saturate(.72) brightness(.92)' : 'none',
          transition: 'filter .18s ease',
        }}
      />

      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          transition: 'opacity .18s ease',
          opacity: show || busy || item.status === 'failed' ? 1 : 0.45,
          background:
            'linear-gradient(180deg, rgba(4,6,10,.5), rgba(4,6,10,0) 34%, rgba(4,6,10,.66))',
        }}
      />

      <div style={{ position: 'absolute', top: 8, left: 8, opacity: show ? 1 : 0, transition: 'opacity .15s ease' }}>
        <Checkbox checked={selected} onChange={onToggle} onClick={(e) => e.stopPropagation()} />
      </div>

      <Space size={4} style={{ position: 'absolute', top: 8, right: 8 }}>
        {item.kind === 'carousel' && (
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
            {item.children}
          </span>
        )}
        {item.kind === 'reel' && (
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
            reel
          </span>
        )}
        {show && (
          <Tooltip title="Preview">
            <Button
              size="small"
              type="text"
              shape="circle"
              icon={<ExpandOutlined />}
              onClick={(e) => e.stopPropagation()}
              style={{ color: '#fff', background: 'rgba(6,8,12,.55)' }}
            />
          </Tooltip>
        )}
      </Space>

      {item.status === 'ready' && !busy && (
        <CheckCircleFilled
          style={{ position: 'absolute', left: 10, bottom: 9, color: token.colorSuccess, fontSize: 14 }}
        />
      )}

      {busy && (
        <div style={{ position: 'absolute', left: 9, right: 9, bottom: 8 }}>
          <Text style={{ fontSize: 10.5, color: '#eef2f8', display: 'block', marginBottom: 3 }}>
            {item.status === 'queued' ? 'queued' : `fetching ${item.done} of ${item.children}`}
          </Text>
          <Progress
            percent={item.status === 'queued' ? 8 : ((item.done ?? 0) / item.children) * 100}
            showInfo={false}
            size="small"
            status="active"
            style={{ margin: 0, lineHeight: 1 }}
          />
        </div>
      )}

      {item.status === 'failed' && (
        <Flex align="center" gap={6} style={{ position: 'absolute', left: 9, right: 9, bottom: 8 }}>
          <Text style={{ flex: 1, fontSize: 10.5, color: token.colorErrorText }} ellipsis>
            {item.error}
          </Text>
          <Button size="small" type="text" danger shape="circle" icon={<ReloadOutlined />} />
        </Flex>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- screen */
function Screen({
  themed,
  dark,
  onTheme,
  onMode,
}: {
  themed: Themed
  dark: boolean
  onTheme: (t: Themed) => void
  onMode: (d: boolean) => void
}) {
  const { token } = theme.useToken()
  const [selected, setSelected] = useState<string[]>([ITEMS[0].code, ITEMS[4].code])
  const [kind, setKind] = useState<string>('All')
  const [density, setDensity] = useState<string>('Comfortable')
  const [queueOpen, setQueueOpen] = useState(false)
  const [active, setActive] = useState('nike')
  const [base, setBase] = useState('nike_ss26')

  const tileSize = density === 'Compact' ? 112 : 158
  const visible = useMemo(
    () =>
      ITEMS.filter((i) =>
        kind === 'All' ? true
        : kind === 'Photos' ? i.kind === 'photo'
        : kind === 'Video' ? i.kind === 'reel'
        : i.kind === 'carousel',
      ),
    [kind],
  )

  const toggle = (code: string) =>
    setSelected((p) => (p.includes(code) ? p.filter((c) => c !== code) : [...p, code]))

  const one = selected.length === 1 ? ITEMS.find((i) => i.code === selected[0]) : undefined
  const readyCount = selected.filter((c) => ITEMS.find((i) => i.code === c)?.status === 'ready').length
  const fileCount = selected.reduce((n, c) => n + (ITEMS.find((i) => i.code === c)?.children ?? 1), 0)
  const pending = selected.length - readyCount

  const railBg = token.colorBgContainer

  return (
    <Layout style={{ height: '100dvh', overflow: 'hidden' }}>
      <Sider width={230} style={{ background: railBg, borderRight: `1px solid ${token.colorBorderSecondary}` }}>
        <Flex vertical style={{ height: '100%' }}>
          <Flex align="center" gap={9} style={{ height: 52, padding: '0 16px', flex: 'none' }}>
            <ThunderboltFilled style={{ color: token.colorPrimary, fontSize: 15 }} />
            <Text strong style={{ letterSpacing: '-0.02em' }}>instascraper</Text>
          </Flex>

          <div style={{ padding: '0 12px 12px', flex: 'none' }}>
            <Input
              placeholder="Look up a profile"
              prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
            />
          </div>

          <Text type="secondary" style={{ fontSize: 11, letterSpacing: '.08em', padding: '0 16px 8px' }}>
            TRACKED
          </Text>

          <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
            {PROFILES.map((p) => {
              const on = p.name === active
              return (
                <Flex
                  key={p.name}
                  align="center"
                  gap={10}
                  onClick={() => setActive(p.name)}
                  style={{
                    padding: '8px 10px',
                    marginBottom: 2,
                    borderRadius: token.borderRadius,
                    cursor: 'pointer',
                    background: on ? token.colorFillSecondary : 'transparent',
                  }}
                >
                  <Avatar size={24} src={thumb(p.name, 48)} />
                  <Text style={{ flex: 1, fontSize: 13, fontWeight: on ? 600 : 400 }} ellipsis>
                    {p.name}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>{p.cached}/{p.posts}</Text>
                </Flex>
              )
            })}
          </div>

          <div style={{ padding: 10, flex: 'none', borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            <Button block type="text" icon={<FieldTimeOutlined />} style={{ justifyContent: 'flex-start' }}>
              Activity
            </Button>
            <Button block type="text" icon={<FolderOpenOutlined />} style={{ justifyContent: 'flex-start' }}>
              Output folder
            </Button>
          </div>
        </Flex>
      </Sider>

      <Layout>
        {/* theme switcher, part of the proposal rather than the product */}
        <Flex
          align="center"
          gap={8}
          style={{
            flex: 'none',
            padding: '7px 16px',
            background: token.colorFillQuaternary,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Text type="secondary" style={{ fontSize: 11, letterSpacing: '.06em' }}>THEME</Text>
          <Segmented
            size="small"
            value={themed.name}
            onChange={(v) => onTheme(THEMES.find((t) => t.name === v)!)}
            options={THEMES.map((t) => ({
              value: t.name,
              label: (
                <Flex align="center" gap={6} style={{ padding: '0 2px' }}>
                  <span style={{ width: 9, height: 9, borderRadius: 999, background: t.accent }} />
                  {t.name}
                </Flex>
              ),
            }))}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>{themed.note}</Text>
          <div style={{ flex: 1 }} />
          <Button size="small" type="text" icon={<BulbOutlined />} onClick={() => onMode(!dark)}>
            {dark ? 'Dark' : 'Light'}
          </Button>
        </Flex>

        <Flex
          align="center"
          gap={12}
          style={{
            height: 56,
            padding: '0 16px',
            flex: 'none',
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Avatar size={32} src={thumb(active, 72)} />
          <Text strong style={{ fontSize: 18, letterSpacing: '-0.02em' }}>{active}</Text>
          <Tag variant="filled" style={{ background: token.colorFillSecondary }}>248 posts</Tag>
          <Tag variant="filled" color={token.colorPrimary}>
            <span style={{ color: themed.onAccent, fontWeight: 600 }}>31 cached</span>
          </Tag>
          <div style={{ flex: 1 }} />
          <Button type="text" icon={<StarFilled />} style={{ color: token.colorWarning }}>Tracked</Button>
          <Tooltip title="Refresh now">
            <Button shape="circle" icon={<ReloadOutlined />} />
          </Tooltip>
          <Text type="secondary" style={{ fontSize: 11 }}>updated 12s ago</Text>
          <Divider orientation="vertical" style={{ height: 20 }} />
          <Badge status="processing" />
          <Button type="text" onClick={() => setQueueOpen(true)}>Queue 3</Button>
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
          <Segmented
            size="small"
            value={kind}
            onChange={(v) => setKind(v as string)}
            options={['All', 'Photos', 'Video', 'Carousels']}
          />
          <Input
            size="small"
            placeholder="Search captions"
            prefix={<SearchOutlined style={{ color: token.colorTextQuaternary }} />}
            style={{ width: 200 }}
            allowClear
          />
          <Checkbox>Cached only</Checkbox>
          <div style={{ flex: 1 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>{visible.length} of {ITEMS.length}</Text>
          <Segmented
            size="small"
            value={density}
            onChange={(v) => setDensity(v as string)}
            options={[
              { value: 'Comfortable', icon: <BorderOuterOutlined /> },
              { value: 'Compact', icon: <AppstoreOutlined /> },
            ]}
          />
          <Button size="small" onClick={() => setSelected(visible.map((i) => i.code))}>Select all</Button>
        </Flex>

        <Layout style={{ overflow: 'hidden', flex: 1, minHeight: 0 }}>
          <Content style={{ overflowY: 'auto', padding: 16, background: token.colorBgLayout }}>
            {visible.length === 0 ? (
              <Empty description="No posts match these filters" style={{ marginTop: 90 }}>
                <Button size="small" onClick={() => setKind('All')}>Reset filters</Button>
              </Empty>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gap: 10,
                  gridTemplateColumns: `repeat(auto-fill, minmax(${tileSize}px, 1fr))`,
                  gridAutoRows: `${tileSize}px`,
                }}
              >
                {visible.map((item, idx) => (
                  <div key={item.code} style={idx === 0 ? { gridColumn: 'span 2', gridRow: 'span 2' } : undefined}>
                    <Tile
                      item={item}
                      size={tileSize * (idx === 0 ? 3 : 2)}
                      selected={selected.includes(item.code)}
                      onToggle={() => toggle(item.code)}
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
            {selected.length === 0 && (
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
                  src={thumb(one.code, 600)}
                  alt=""
                  style={{ width: '100%', borderRadius: token.borderRadiusLG, display: 'block' }}
                />
                <Paragraph style={{ margin: '14px 0 12px', fontSize: 13 }} ellipsis={{ rows: 3 }}>
                  {one.caption}
                </Paragraph>
                <Descriptions
                  size="small"
                  column={1}
                  colon={false}
                  labelStyle={{ fontSize: 11, color: token.colorTextTertiary, width: 78 }}
                  contentStyle={{ fontSize: 12 }}
                  items={[
                    { key: 'c', label: 'Shortcode', children: <Text code copyable style={{ fontSize: 11 }}>{one.code}</Text> },
                    { key: 'k', label: 'Kind', children: one.kind === 'carousel' ? `carousel, ${one.children} slides` : one.kind },
                    { key: 't', label: 'Posted', children: one.taken },
                    {
                      key: 's',
                      label: 'Cached',
                      children:
                        one.status === 'ready' ? <Text type="success">yes, {one.bytes}</Text>
                        : one.status === 'failed' ? <Text type="danger">{one.error}</Text>
                        : <Text type="secondary">not yet</Text>,
                    },
                  ]}
                />
                <Space style={{ marginTop: 16 }} size={8}>
                  <Button icon={<ExpandOutlined />}>Preview</Button>
                  <Button icon={<LinkOutlined />}>Instagram</Button>
                </Space>
              </div>
            )}

            {selected.length > 1 && (
              <div style={{ padding: 16 }}>
                <Text style={{ display: 'block', fontSize: 34, fontWeight: 700, letterSpacing: '-0.035em', lineHeight: 1.05 }}>
                  {selected.length}
                </Text>
                <Text type="secondary" style={{ fontSize: 13 }}>posts selected</Text>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                  {fileCount} files · {readyCount} already cached
                </Text>

                <Divider style={{ margin: '16px 0' }} />

                <Text style={{ fontSize: 12, display: 'block', marginBottom: 7 }}>Base filename</Text>
                <Input value={base} onChange={(e) => setBase(e.target.value)} />
                <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 7 }}>
                  {base || 'download'}_01 through {base || 'download'}_{String(fileCount).padStart(2, '0')}
                </Text>

                <Button type="primary" block size="large" icon={<CloudDownloadOutlined />} style={{ marginTop: 16 }}>
                  Download {fileCount} files
                </Button>
                <Button block type="text" style={{ marginTop: 8 }} onClick={() => setSelected([])}>
                  Clear selection
                </Button>

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
          </Sider>
        </Layout>

        <Flex
          align="center"
          gap={12}
          style={{
            flex: 'none',
            padding: '10px 16px',
            background: token.colorBgContainer,
            borderTop: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <CloudDownloadOutlined style={{ color: token.colorPrimary }} />
          <Text style={{ fontSize: 12 }}>Fetching 3 of 12</Text>
          <Progress percent={25} size="small" status="active" style={{ flex: 1, margin: 0, maxWidth: 440 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>next request in 2s</Text>
          <div style={{ flex: 1 }} />
          <Button size="small" type="text" icon={<ClearOutlined />}>Cancel queue</Button>
        </Flex>
      </Layout>

      <Drawer title="Fetch queue" placement="right" size={380} open={queueOpen} onClose={() => setQueueOpen(false)}>
        <Alert
          type="info"
          showIcon
          icon={<InboxOutlined />}
          title="One request at a time"
          description="Every Instagram call goes through a single worker with a 3 second floor between requests."
          style={{ marginBottom: 18 }}
        />
        <List
          size="small"
          dataSource={[
            { code: 'C8vNq1KdWzE', state: 'fetching 2 of 3' },
            { code: 'C8tHy7BcXnR', state: 'queued' },
            { code: 'C8kFa2NsQvD', state: 'queued' },
          ]}
          renderItem={(j, i) => (
            <List.Item>
              <List.Item.Meta
                avatar={<Avatar shape="square" size={38} src={thumb(j.code, 76)} />}
                title={<Text code style={{ fontSize: 11 }}>{j.code}</Text>}
                description={<Text type="secondary" style={{ fontSize: 12 }}>{j.state}</Text>}
              />
              {i === 0 ? <Badge status="processing" /> : <Text type="secondary" style={{ fontSize: 11 }}>#{i}</Text>}
            </List.Item>
          )}
        />
        <Divider style={{ fontSize: 12 }}>Recently done</Divider>
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      </Drawer>
    </Layout>
  )
}

export default function Preview() {
  const [themed, setThemed] = useState<Themed>(THEMES[0])
  const [dark, setDark] = useState(true)

  return (
    <ConfigProvider
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: themed.accent,
          colorInfo: themed.accent,
          colorTextLightSolid: themed.onAccent,
          colorBgBase: dark ? themed.darkBg : themed.lightBg,
          borderRadius: 10,
          fontFamily: sans.style.fontFamily,
          fontFamilyCode: mono.style.fontFamily,
          fontSize: 14,
          controlHeight: 34,
          wireframe: false,
        },
        components: {
          Button: { borderRadius: 999, fontWeight: 600 },
          Input: { borderRadius: 999 },
          Segmented: { borderRadius: 999, itemSelectedColor: themed.onAccent, itemSelectedBg: themed.accent },
          Tag: { borderRadiusSM: 999 },
        },
      }}
    >
      <Screen themed={themed} dark={dark} onTheme={setThemed} onMode={setDark} />
    </ConfigProvider>
  )
}
