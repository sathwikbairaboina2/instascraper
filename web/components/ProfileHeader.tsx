'use client'

import { Avatar, Flex, Typography } from 'antd'

import type { ProfileDetail } from '@/lib/api'
import { compactCount } from '@/lib/format'
import { GRADIENT } from '@/lib/themes'
import { useThemePref } from './ThemeProvider'

const { Text, Title } = Typography


function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  const { tokens } = useThemePref()
  return (
    <Flex vertical gap={1} data-testid={testId}>
      <Text strong style={{ fontSize: 14 }}>{value}</Text>
      <Text style={{ fontSize: 11, color: tokens.textSecondary }}>{label}</Text>
    </Flex>
  )
}

export default function ProfileHeader({
  profile,
  indexed,
  actions,
}: {
  profile: ProfileDetail | null | undefined
  indexed: number
  actions: React.ReactNode
}) {
  const { tokens } = useThemePref()

  return (
    <Flex
      align="flex-start"
      gap={20}
      style={{
        padding: '16px 20px 12px',
        flex: 'none',
        borderBottom: `1px solid ${tokens.hairline}`,
      }}
    >
      {/* The story ring is the one place the gradient appears. */}
      <div style={{ background: GRADIENT, padding: 2.5, borderRadius: '50%', flex: 'none' }}>
        <Avatar
          size={60}
          src={profile?.avatar_url}
          style={{ border: `2px solid ${tokens.ground}`, display: 'block' }}
        />
      </div>

      <Flex vertical gap={7} style={{ flex: 1, minWidth: 0 }}>
        <Title level={5} data-testid="profile-username" style={{ margin: 0 }}>
          {profile?.username}
        </Title>

        <Flex gap={22}>
          <Stat testId="profile-stat-posts" label="posts" value={compactCount(profile?.post_count) ?? '—'} />
          <Stat
            testId="profile-stat-followers"
            label="followers"
            value={compactCount(profile?.followers_count) ?? '—'}
          />
          <Stat testId="profile-stat-indexed" label="indexed" value={String(indexed)} />
        </Flex>

        {profile?.biography && (
          <Text style={{ fontSize: 12, color: tokens.textSecondary }}>{profile.biography}</Text>
        )}
      </Flex>

      {/* Track, sync and cache are things this app does, not things the
          profile is. They sit apart from Instagram's own furniture. */}
      <Flex gap={6} align="center" style={{ flex: 'none' }}>
        {actions}
      </Flex>
    </Flex>
  )
}
