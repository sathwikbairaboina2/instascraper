'use client'

import { useMemo, useState } from 'react'

import type { MediaSummary } from '@/lib/api'

export type KindFilter = 'all' | 'image' | 'video' | 'carousel'

export type Filters = {
  kind: KindFilter
  cachedOnly: boolean
  query: string
}

export const EMPTY_FILTERS: Filters = { kind: 'all', cachedOnly: false, query: '' }

/** Reels count as video -- the distinction matters to Instagram, not to someone
 *  scanning a grid for moving pictures. */
export function matchesKind(item: MediaSummary, kind: KindFilter): boolean {
  if (kind === 'all') return true
  if (kind === 'video') return item.kind === 'video' || item.kind === 'reel'
  return item.kind === kind
}

export function applyFilters(items: MediaSummary[], filters: Filters): MediaSummary[] {
  const needle = filters.query.trim().toLowerCase()
  return items.filter((item) => {
    if (!matchesKind(item, filters.kind)) return false
    if (filters.cachedOnly && item.full_status !== 'ready') return false
    if (needle && !(item.caption ?? '').toLowerCase().includes(needle)) return false
    return true
  })
}

export function useFilters(items: MediaSummary[]) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const visible = useMemo(() => applyFilters(items, filters), [items, filters])
  const active =
    filters.kind !== 'all' || filters.cachedOnly || filters.query.trim() !== ''

  return {
    filters,
    visible,
    active,
    set: <K extends keyof Filters>(key: K, value: Filters[K]) =>
      setFilters((prev) => ({ ...prev, [key]: value })),
    reset: () => setFilters(EMPTY_FILTERS),
  }
}
