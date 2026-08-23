'use client'

import { Layout, Table, Typography } from 'antd'

import AppShell from '@/components/AppShell'
import { getActivity, type ActivityItem } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

const { Content } = Layout
const { Text } = Typography

function detailOf(item: ActivityItem): string {
  const d = item.detail
  if (!d) return ''
  if (item.action === 'download') return `${d.count} files as "${d.base}" to ${d.out}`
  return JSON.stringify(d)
}

export default function ActivityPage() {
  const { data } = usePolling(() => getActivity(200), 5000)

  return (
    <AppShell>
      <Content style={{ padding: 16, overflowY: 'auto' }}>
        <Table
          data-testid="activity-table"
          size="small"
          rowKey="id"
          loading={!data}
          dataSource={data?.items ?? []}
          pagination={{ pageSize: 25, hideOnSinglePage: true }}
          columns={[
            {
              title: 'When',
              dataIndex: 'ts',
              width: 170,
              render: (ts: string) => (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {ts.slice(0, 19).replace('T', ' ')}
                </Text>
              ),
            },
            { title: 'Action', dataIndex: 'action', width: 110 },
            { title: 'Target', dataIndex: 'target', width: 160 },
            {
              title: 'Detail',
              render: (_: unknown, row: ActivityItem) => (
                <Text type="secondary" style={{ fontSize: 12 }}>{detailOf(row)}</Text>
              ),
            },
          ]}
        />
      </Content>
    </AppShell>
  )
}
