'use client'

import { getActivity, type ActivityItem } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

function summarise(item: ActivityItem): string {
  const detail = item.detail
  if (!detail) return ''
  if (item.action === 'download') {
    return `${detail.count} files as "${detail.base}" → ${detail.out}`
  }
  return JSON.stringify(detail)
}

export default function ActivityPage() {
  const { data } = usePolling(() => getActivity(200), 5000)

  return (
    <section>
      <h1>Activity</h1>
      <table data-testid="activity-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Action</th>
            <th>Target</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {(data?.items ?? []).map((item) => (
            <tr key={item.id}>
              <td className="muted">{item.ts.slice(0, 19).replace('T', ' ')}</td>
              <td>{item.action}</td>
              <td>{item.target ?? ''}</td>
              <td className="muted">{summarise(item)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
