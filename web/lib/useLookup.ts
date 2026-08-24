'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { syncProfile } from '@/lib/api'

/**
 * Looking a profile up is two steps, not one: ask the server to fetch it,
 * then go and look. Both the sidebar and the home screen offer the box, and
 * a copy of this in each is a copy that can drift -- one of them ending up
 * navigating without ever queueing the fetch, which is a screen that waits
 * forever on work nobody asked for.
 */
export function useLookup() {
  const router = useRouter()
  const [value, setValue] = useState('')

  const submit = async (raw?: string) => {
    const clean = (raw ?? value).trim().replace(/^@/, '')
    if (!clean) return
    await syncProfile(clean)
    setValue('')
    router.push(`/p/${encodeURIComponent(clean)}`)
  }

  return { value, setValue, submit }
}
