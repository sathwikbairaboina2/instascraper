'use client'

import { Tooltip, Typography } from 'antd'

import { useThemePref } from './ThemeProvider'

const { Text } = Typography

export default function UsageMeter({ usage }: { usage: number | null | undefined }) {
  const { tokens } = useThemePref()

  // Null means the live adapter never calls Meta. Rendering 0% there would
  // read as a measurement rather than an absence.
  if (usage === null || usage === undefined) return null

  // Meta backs the app off at 90%, so the colour tracks distance from that
  // rather than from 100.
  const colour =
    usage >= 75 ? tokens.destructive : usage >= 50 ? '#fcb045' : tokens.textSecondary

  // No countdown and no estimated reset: Meta sends no reset timestamp on
  // Business Discovery calls, and a clock we invented would be read as one
  // Meta gave us.
  return (
    <Tooltip title="Share of Meta's hourly API quota spent. Requests stop at 90%.">
      <Text data-testid="usage-meter" style={{ fontSize: 12, color: colour }}>
        API {Math.round(usage)}%
      </Text>
    </Tooltip>
  )
}
