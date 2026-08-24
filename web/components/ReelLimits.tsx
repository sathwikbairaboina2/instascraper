'use client'

import { Flex, Tooltip, Typography } from 'antd'

import type { StatusBody } from '@/lib/api'
import { useThemePref } from './ThemeProvider'

const { Text } = Typography

type Window = { used: number; max: number; resets_at: string | null }

/** Green while there is room, orange past half, red as it runs out.
 *
 *  Flat per state, never a gradient: a fill whose colour changes along its
 *  own length cannot also encode how full it is. The story gradient stays on
 *  the avatar ring, where it means something else. */
function fillFor(ratio: number): string {
  if (ratio >= 0.85) return '#ed4956'
  if (ratio >= 0.5) return '#fcb045'
  return '#2ecc71'
}

function clock(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function Bar({ label, window: w, testId }: { label: string; window: Window; testId: string }) {
  const { tokens } = useThemePref()
  const ratio = w.max > 0 ? Math.min(w.used / w.max, 1) : 0
  const spent = w.used >= w.max
  const fill = fillFor(ratio)

  return (
    <Tooltip
      title={
        spent
          ? `Reel cap spent. Headroom returns at ${clock(w.resets_at)}.`
          : `${w.used} of ${w.max} reels downloaded this ${label.toLowerCase()}.`
      }
    >
      <Flex vertical gap={2} data-testid={testId} style={{ width: 54 }}>
        <Text
          style={{
            fontSize: 9,
            letterSpacing: '.05em',
            color: spent ? fill : tokens.textSecondary,
            lineHeight: 1.1,
          }}
        >
          {/* Once spent, the count says nothing you can act on and the time
              says everything. */}
          {spent ? `${label} · ${clock(w.resets_at)}` : `${label} ${w.used}/${w.max}`}
        </Text>
        <div style={{ height: 3, borderRadius: 999, background: tokens.hairline }}>
          <div
            data-testid={`${testId}-fill`}
            style={{
              width: `${ratio * 100}%`,
              height: '100%',
              borderRadius: 999,
              background: fill,
            }}
          />
        </div>
      </Flex>
    </Tooltip>
  )
}

export default function ReelLimits({ limits }: { limits: StatusBody['reel_limits'] }) {
  // Null means this adapter never scrapes. Showing 0/20 would advertise a
  // budget that does not apply.
  if (!limits) return null

  return (
    <Flex gap={9} align="center" data-testid="reel-limits">
      <Bar label="HOUR" window={limits.hour} testId="reel-limit-hour" />
      <Bar label="DAY" window={limits.day} testId="reel-limit-day" />
    </Flex>
  )
}
