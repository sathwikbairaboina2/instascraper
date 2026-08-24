'use client'

import { useMemo, useState } from 'react'

import type { MediaSummary } from '@/lib/api'

export type KindFilter = 'posts' | 'reels' | 'saved'

export type Filters = {
  kind: KindFilter
  cachedOnly: boolean
  query: string
}

export const EMPTY_FILTERS: Filters = { kind: 'posts', cachedOnly: false, query: '' }

/** Instagram splits a profile by the surface a post was published to, not by
 *  file type. Saved is ours rather than Instagram's: what this app has
 *  actually pulled down. */
export function matchesKind(item: MediaSummary, kind: KindFilter): boolean {
  if (kind === 'reels') return item.kind === 'reel'
  if (kind === 'saved') return item.full_status === 'ready'
  return item.kind !== 'reel'
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
    filters.kind !== 'posts' || filters.cachedOnly || filters.query.trim() !== ''

  return {
    filters,
    visible,
    active,
    set: <K extends keyof Filters>(key: K, value: Filters[K]) =>
      setFilters((prev) => ({ ...prev, [key]: value })),
    reset: () => setFilters(EMPTY_FILTERS),
  }
}
