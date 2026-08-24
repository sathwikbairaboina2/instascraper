'use client'

import { SearchOutlined } from '@ant-design/icons'
import { Button, Flex, Input, Layout, Space, Typography } from 'antd'

import AppShell from '@/components/AppShell'
import ProfileSuggestions from '@/components/ProfileSuggestions'
import { useThemePref } from '@/components/ThemeProvider'
import { GRADIENT_LINEAR } from '@/lib/themes'
import { useLookup } from '@/lib/useLookup'

const { Content } = Layout
const { Text } = Typography

export default function HomePage() {
  const { tokens } = useThemePref()
  const { value, setValue, submit } = useLookup()

  return (
    <AppShell>
      <Content style={{ display: 'grid', placeItems: 'center', padding: 40 }}>
        <Flex vertical align="center" gap={16} style={{ width: '100%', maxWidth: 560 }}>
          <Text
            strong
            style={{
              fontSize: 40,
              letterSpacing: '-0.03em',
              lineHeight: 1.05,
              // The wordmark is the banner; nothing else on this screen needs
              // to shout, least of all the thing you came here to type into.
              background: GRADIENT_LINEAR,
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              color: 'transparent',
            }}
          >
            instascraper
          </Text>

          <Text style={{ fontSize: 13, color: tokens.textSecondary, marginTop: -8 }}>
            Index a public profile. Keep what is worth keeping.
          </Text>

          <Space.Compact style={{ width: '100%', maxWidth: 420 }}>
            <Input
              size="large"
              data-testid="username-input"
              placeholder="Look up a profile"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onPressEnter={() => void submit()}
            />
            <Button
              size="large"
              type="primary"
              data-testid="lookup-submit"
              aria-label="Look up profile"
              icon={<SearchOutlined />}
              onClick={() => void submit()}
            />
          </Space.Compact>

          <ProfileSuggestions onPick={(username) => void submit(username)} />
        </Flex>
      </Content>
    </AppShell>
  )
}
