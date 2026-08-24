'use client'

import { ArrowLeftOutlined, LinkOutlined } from '@ant-design/icons'
import { Alert, Button, Flex, Layout, Tag, Typography } from 'antd'
import Link from 'next/link'
import { use } from 'react'

import AppShell from '@/components/AppShell'
import { useThemePref } from '@/components/ThemeProvider'
import { getRecreateItem } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

const { Content } = Layout
const { Text, Title } = Typography

export default function RecreateItemPage({
  params,
}: {
  params: Promise<{ shortcode: string }>
}) {
  const { shortcode } = use(params)
  const { tokens } = useThemePref()
  const { data: item, error } = usePolling(() => getRecreateItem(shortcode), 10000)

  if (error) {
    return (
      <AppShell>
        <Content style={{ padding: 32 }}>
          <Alert type="error" showIcon title="Not lined up for recreation" description={error} />
        </Content>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <Content style={{ padding: '20px 24px', overflowY: 'auto' }}>
        <Link href="/recreate">
          <Button size="small" type="text" icon={<ArrowLeftOutlined />} style={{ marginBottom: 14 }}>
            Recreate
          </Button>
        </Link>

        <Flex gap={20} align="flex-start" wrap>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={item?.thumb_url}
            alt=""
            style={{
              width: 260,
              borderRadius: 10,
              display: 'block',
              background: tokens.surface,
            }}
          />

          <Flex vertical gap={10} style={{ flex: 1, minWidth: 260 }}>
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

            {/* An honest empty state rather than a workflow that does nothing.
                A disabled Generate button would imply the machinery exists
                and is merely switched off. */}
            <Alert
              type="info"
              showIcon
              data-testid="no-generator"
              title="No generator connected yet"
              description="This is where the source post gets turned into your own version. The service that does that is not built, so nothing is submitted from here."
              style={{ marginTop: 6 }}
            />
          </Flex>
        </Flex>
      </Content>
    </AppShell>
  )
}
