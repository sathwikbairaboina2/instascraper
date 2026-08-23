'use client'

/** Named selections, kept per profile in this browser only.
 *
 *  localStorage rather than a table: single user, no schema change, and it is
 *  honestly a per-browser convenience rather than shared state. Every access
 *  is guarded -- a private window or blocked site data makes these throw.
 */

export type SavedSelection = { name: string; shortcodes: string[] }

const key = (username: string) => `instascraper:selections:${username}`

export function loadSelections(username: string): SavedSelection[] {
  try {
    const raw = localStorage.getItem(key(username))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (s): s is SavedSelection =>
        s && typeof s.name === 'string' && Array.isArray(s.shortcodes),
    )
  } catch {
    return []
  }
}

export function saveSelection(
  username: string,
  name: string,
  shortcodes: string[],
): SavedSelection[] {
  const clean = name.trim()
  if (!clean || shortcodes.length === 0) return loadSelections(username)
  const others = loadSelections(username).filter((s) => s.name !== clean)
  const next = [...others, { name: clean, shortcodes }].sort((a, b) =>
    a.name.localeCompare(b.name),
  )
  try {
    localStorage.setItem(key(username), JSON.stringify(next))
  } catch {
    // Storage unavailable or full: the selection just isn't remembered.
  }
  return next
}

export function deleteSelection(username: string, name: string): SavedSelection[] {
  const next = loadSelections(username).filter((s) => s.name !== name)
  try {
    localStorage.setItem(key(username), JSON.stringify(next))
  } catch {
    // ignore
  }
  return next
}
