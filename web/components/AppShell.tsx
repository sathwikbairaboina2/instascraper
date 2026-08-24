'use client'

import {
  BulbOutlined,
  FieldTimeOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  SearchOutlined,
  ThunderboltFilled,
} from '@ant-design/icons'
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Drawer,
  Flex,
  Input,
  Layout,
  List,
  Modal,
  Segmented,
  Space,
  Typography,
  theme,
} from 'antd'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { clearBreaker, getProfiles, getStatus, setAdapter, syncProfile } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'
import { useThemePref } from './ThemeProvider'

const { Sider } = Layout
const { Text } = Typography

export default function AppShell({
  active,
  children,
}: {
  active?: string
  children: React.ReactNode
}) {
  const { token } = theme.useToken()
  const { dark, setDark } = useThemePref()
  const router = useRouter()
  const [lookup, setLookup] = useState('')

  const switchAdapter = (next: string) => {
    if (next === status?.adapter) return
    Modal.confirm({
      title: next === 'fake' ? 'Switch to fake data?' : 'Switch to Graph data?',
      content:
        'The app will reload and show the other dataset. Nothing is deleted — ' +
        'the dataset you are leaving is kept exactly as it is.',
      okText: 'Switch',
      onOk: async () => {
        await setAdapter(next as 'graph' | 'fake')
        // Everything on screen came from a database that is no longer live,
        // and the profile being viewed may not exist in the other dataset.
        window.location.assign('/')
      },
    })
  }
  const [queueOpen, setQueueOpen] = useState(false)

  const { data: profiles } = usePolling(getProfiles, 30000)
  const { data: status, refresh: refreshStatus } = usePolling(getStatus, 5000)

  const breaker = status?.breaker
  const items = profiles?.items ?? []

  async function submitLookup() {
    const clean = lookup.trim().replace(/^@/, '')
    if (!clean) return
    await syncProfile(clean)
    setLookup('')
    router.push(`/p/${encodeURIComponent(clean)}`)
  }

  return (
    <Layout style={{ height: '100dvh', overflow: 'hidden' }}>
      <Sider
        width={230}
        style={{ background: token.colorBgContainer, borderRight: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Flex vertical style={{ height: '100%' }}>
          <Link href="/" style={{ color: 'inherit' }}>
            <Flex align="center" gap={9} style={{ height: 52, padding: '0 16px', flex: 'none' }}>
              <ThunderboltFilled style={{ color: token.colorPrimary, fontSize: 15 }} />
              <Text strong style={{ letterSpacing: '-0.02em' }}>instascraper</Text>
            </Flex>
          </Link>

          <div style={{ padding: '0 12px 12px', flex: 'none' }}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                data-testid="username-input"
                placeholder="Look up a profile"
                value={lookup}
                onChange={(e) => setLookup(e.target.value)}
                onPressEnter={submitLookup}
              />
              <Button
                type="primary"
                data-testid="lookup-submit"
                aria-label="Look up profile"
                icon={<SearchOutlined />}
                onClick={submitLookup}
              />
            </Space.Compact>
          </div>

          <Text type="secondary" style={{ fontSize: 11, letterSpacing: '.08em', padding: '0 16px 8px' }}>
            TRACKED
          </Text>

          <div data-testid="tracked-profiles" style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
            {items.length === 0 && (
              <Text type="secondary" style={{ fontSize: 12, padding: '0 8px' }}>
                Nothing tracked yet.
              </Text>
            )}
            {items.map((p) => {
              const on = p.username === active
              return (
                <Link key={p.username} href={`/p/${p.username}`} style={{ color: 'inherit' }}>
                  <Flex
                    align="center"
                    gap={10}
                    style={{
                      padding: '8px 10px',
                      marginBottom: 2,
                      borderRadius: token.borderRadius,
                      background: on ? token.colorFillSecondary : 'transparent',
                    }}
                  >
                    <Avatar size={24} src={p.avatar_url} />
                    <Text style={{ flex: 1, fontSize: 13, fontWeight: on ? 600 : 400 }} ellipsis>
                      {p.username}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>{p.post_count ?? 0}</Text>
                  </Flex>
                </Link>
              )
            })}
          </div>

          <div style={{ padding: 10, flex: 'none', borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            <Link href="/activity">
              <Button block type="text" icon={<FieldTimeOutlined />} style={{ justifyContent: 'flex-start' }}>
                Activity
              </Button>
            </Link>
            <Button block type="text" icon={<FolderOpenOutlined />} style={{ justifyContent: 'flex-start' }} disabled>
              Output folder
            </Button>
          </div>
        </Flex>
      </Sider>

      <Layout>
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
          <Text type="secondary" style={{ fontSize: 11, letterSpacing: '.06em' }}>
            DATA
          </Text>
          <Segmented
            size="small"
            // Switching is off for now: Graph is the only source in use. The
            // control stays visible because naming the live dataset is the
            // half that still earns its place. Re-enable by dropping
            // `disabled` and restoring onChange.
            disabled
            // No fallback: a control whose job is naming the live dataset
            // must not claim one before status has arrived.
            value={status?.adapter}
            onChange={(v) => switchAdapter(v as string)}
            options={[
              { value: 'graph', label: 'Graph' },
              { value: 'fake', label: 'Fake' },
            ]}
          />
          <div style={{ flex: 1 }} />
          <Badge status={status?.worker === 'running' ? 'processing' : 'default'} />
          <Button size="small" type="text" onClick={() => setQueueOpen(true)}>
            Queue {status?.queue_depth ?? 0}
          </Button>
          <Button size="small" type="text" icon={<BulbOutlined />} onClick={() => setDark(!dark)}>
            {dark ? 'Dark' : 'Light'}
          </Button>
        </Flex>

        {breaker?.tripped && (
          <Alert
            data-testid="breaker-banner"
            type={breaker.permanent ? 'error' : 'warning'}
            showIcon
            banner
            title={
              status?.token_configured === false
                ? 'Graph API token not configured'
                : breaker.permanent
                  ? breaker.reason ?? 'Instagram token invalid'
                  : `${breaker.reason ?? 'Rate limited'}, resuming in about ${Math.ceil((breaker.seconds_remaining ?? 0) / 60)} min`
            }
            description={
              status?.token_configured === false
                ? 'Reading public Business and Creator accounts needs a Meta Graph token. Set IG_GRAPH_TOKEN, IG_GRAPH_USER_ID and IG_GRAPH_VERSION in .env, then restart.'
                : undefined
            }
            action={
              breaker.permanent ? (
                <Button
                  size="small"
                  onClick={async () => {
                    await clearBreaker()
                    refreshStatus()
                  }}
                >
                  Clear breaker
                </Button>
              ) : undefined
            }
          />
        )}

        {children}
      </Layout>

      <Drawer title="Fetch queue" placement="right" size={380} open={queueOpen} onClose={() => setQueueOpen(false)}>
        <Alert
          type="info"
          showIcon
          icon={<InboxOutlined />}
          title="One request at a time"
          description="Every Instagram call goes through a single worker with an enforced gap between requests."
          style={{ marginBottom: 18 }}
        />
        <List
          size="small"
          locale={{ emptyText: 'Nothing queued' }}
          dataSource={
            status && status.queue_depth > 0
              ? Array.from({ length: status.queue_depth }, (_, i) => i)
              : []
          }
          renderItem={(i) => (
            <List.Item>
              <List.Item.Meta
                title={<Text style={{ fontSize: 13 }}>{i === 0 ? 'Running now' : `Waiting`}</Text>}
                description={<Text type="secondary" style={{ fontSize: 12 }}>position {i + 1}</Text>}
              />
              {i === 0 ? <Badge status="processing" /> : <Text type="secondary" style={{ fontSize: 11 }}>#{i}</Text>}
            </List.Item>
          )}
        />
      </Drawer>
    </Layout>
  )
}
