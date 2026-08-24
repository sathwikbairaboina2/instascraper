'use client'

import { Avatar, Flex, Typography } from 'antd'

import { getProfiles } from '@/lib/api'
import { GRADIENT } from '@/lib/themes'
import { usePolling } from '@/lib/usePolling'
import { useThemePref } from './ThemeProvider'

const { Text } = Typography

/** Somewhere to start on a fresh install, when there is nothing tracked and
 *  an empty search box is not an invitation.
 *
 *  Hardcoded, and therefore a dependency on four accounts staying public and
 *  professional. If one stops being either, its card fails like any other
 *  lookup rather than explaining itself. */
const STARTERS = ['nike', 'natgeo', 'nasa', 'bbcnews']

export default function ProfileSuggestions({
  onPick,
}: {
  onPick: (username: string) => void
}) {
  const { tokens } = useThemePref()
  const { data } = usePolling(getProfiles, 30000)
  const tracked = data?.items ?? []
  const showTracked = tracked.length > 0

  const cards = showTracked
    ? tracked.slice(0, 4).map((p) => ({
        username: p.username,
        detail: p.post_count == null ? '' : `${p.post_count.toLocaleString()} posts`,
        avatar: p.avatar_url,
      }))
    : STARTERS.map((username) => ({ username, detail: '', avatar: undefined }))

  return (
    <Flex vertical gap={8} style={{ width: '100%', maxWidth: 520 }} data-testid="suggestions">
      <Text
        style={{ fontSize: 10, letterSpacing: '.12em', color: tokens.textSecondary }}
      >
        {showTracked ? 'YOUR PROFILES' : 'START WITH'}
      </Text>

      <Flex gap={10} wrap>
        {cards.map((card) => (
          <Flex
            key={card.username}
            vertical
            gap={7}
            align="center"
            data-testid={`suggestion-${card.username}`}
            onClick={() => onPick(card.username)}
            style={{
              cursor: 'pointer',
              flex: '1 1 100px',
              minWidth: 100,
              padding: '12px 10px',
              borderRadius: 10,
              border: `1px solid ${tokens.hairline}`,
            }}
          >
            <div style={{ background: GRADIENT, padding: 2, borderRadius: '50%', lineHeight: 0 }}>
              <Avatar
                size={30}
                src={card.avatar}
                style={{ border: `2px solid ${tokens.ground}`, display: 'block' }}
              />
            </div>
            <Text strong style={{ fontSize: 12 }}>{card.username}</Text>
            {card.detail && (
              <Text style={{ fontSize: 10, color: tokens.textSecondary }}>{card.detail}</Text>
            )}
          </Flex>
        ))}
      </Flex>
    </Flex>
  )
}
