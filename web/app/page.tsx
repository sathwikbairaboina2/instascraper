'use client'

import { Empty, Layout, Typography } from 'antd'

import AppShell from '@/components/AppShell'

const { Content } = Layout
const { Text } = Typography

export default function HomePage() {
  return (
    <AppShell>
      <Content style={{ display: 'grid', placeItems: 'center', padding: 40 }}>
        <div style={{ textAlign: 'center' }}>
          <Empty description="Pick a profile, or look one up on the left" />
          <Text type="secondary" style={{ fontSize: 12 }}>
            Public profiles only. Media is fetched one request at a time.
          </Text>
        </div>
      </Content>
    </AppShell>
  )
}
