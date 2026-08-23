'use client'

import { useCallback, useRef, useState } from 'react'

export function useSelection(orderedIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const anchor = useRef<string | null>(null)

  const toggle = useCallback(
    (id: string, shiftKey = false) => {
      setSelected((prev) => {
        const next = new Set(prev)
        if (shiftKey && anchor.current) {
          const from = orderedIds.indexOf(anchor.current)
          const to = orderedIds.indexOf(id)
          if (from !== -1 && to !== -1) {
            const [lo, hi] = from <= to ? [from, to] : [to, from]
            for (const item of orderedIds.slice(lo, hi + 1)) next.add(item)
            return next
          }
        }
        if (next.has(id)) next.delete(id)
        else next.add(id)
        anchor.current = id
        return next
      })
    },
    [orderedIds],
  )

  const selectAll = useCallback(() => setSelected(new Set(orderedIds)), [orderedIds])
  const clear = useCallback(() => {
    anchor.current = null
    setSelected(new Set())
  }, [])

  return {
    selected: orderedIds.filter((id) => selected.has(id)),
    isSelected: (id: string) => selected.has(id),
    toggle,
    selectAll,
    clear,
  }
}
