'use client'

import { createContext, useContext } from 'react'

import { useRecreate } from '@/lib/useRecreate'

type Ctx = ReturnType<typeof useRecreate>

const RecreateCtx = createContext<Ctx | null>(null)

/**
 * One copy of the recreate list for the whole screen.
 *
 * The sidebar count and the grid both care about it, and giving each its own
 * poller meant marking a tile updated the grid while the count kept a stale
 * list until its next tick -- up to thirty seconds of the header disagreeing
 * with the thing you just clicked. Sharing one instance means a write
 * refreshes every reader at once.
 */
export function RecreateProvider({ children }: { children: React.ReactNode }) {
  const value = useRecreate(30000)
  return <RecreateCtx.Provider value={value}>{children}</RecreateCtx.Provider>
}

export function useRecreateShared(): Ctx {
  const ctx = useContext(RecreateCtx)
  if (ctx === null) {
    throw new Error('useRecreateShared must be used inside RecreateProvider')
  }
  return ctx
}
