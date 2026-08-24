'use client'

import { useCallback, useMemo } from 'react'

import { listRecreate, markRecreate, unmarkRecreate } from '@/lib/api'
import { usePolling } from '@/lib/usePolling'

/**
 * Which posts are lined up to be remade, and the two ways to change that.
 *
 * Marking is a round trip, and a tile that only lights up on the next poll
 * feels broken, so `refresh` is awaited straight after the write rather than
 * waiting for the interval. The list is small -- it is a queue you curate by
 * hand, not a feed.
 */
export function useRecreate(intervalMs = 15000) {
  const { data, refresh } = usePolling(listRecreate, intervalMs)

  const items = useMemo(() => data?.items ?? [], [data])
  const marked = useMemo(() => new Set(items.map((i) => i.shortcode)), [items])

  const mark = useCallback(
    async (shortcodes: string[]) => {
      if (shortcodes.length === 0) return
      await markRecreate(shortcodes)
      await refresh()
    },
    [refresh],
  )

  const unmark = useCallback(
    async (shortcode: string) => {
      await unmarkRecreate(shortcode)
      await refresh()
    },
    [refresh],
  )

  const toggle = useCallback(
    async (shortcode: string) => {
      if (marked.has(shortcode)) await unmark(shortcode)
      else await mark([shortcode])
    },
    [marked, mark, unmark],
  )

  return { items, marked, mark, unmark, toggle, refresh }
}
