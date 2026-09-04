/** Instagram's own shortening: 999, 1.2K, 72.7K, 123K, 3.3M.
 *
 *  One decimal until the mantissa reaches a hundred, none after. Dropping it
 *  earlier rounds 72,692 to "73K" and throws away seven hundred likes to
 *  save one character. Exact numbers live in the inspector, where there is
 *  room to read them.
 */
function scale(n: number, unit: number, suffix: string): string {
  const value = n / unit
  const text = value >= 100 ? value.toFixed(0) : value.toFixed(1)
  // 2.0K reads worse than 2K, and means the same thing.
  return `${text.endsWith('.0') ? text.slice(0, -2) : text}${suffix}`
}

export function compactCount(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null
  if (n >= 1_000_000) return scale(n, 1_000_000, 'M')
  if (n >= 1_000) return scale(n, 1_000, 'K')
  return String(n)
}

/** "1 file", "3 files". The log used to read "1 files". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

// Letters, numbers and marks, plus underscore. Mirrors paths.sanitize_base on
// the server, including keeping non-Latin names: this is what the filename
// preview has to show, and showing the raw text promised files the server was
// never going to write.
const KEEP = /[\p{L}\p{N}\p{M}\p{Pc}]/u

/** The name the server will actually use. Keep in step with app/paths.py. */
export function sanitizeBase(base: string, maxLength = 120): string {
  let out = ''
  for (const ch of base.trim()) {
    if (KEEP.test(ch)) out += ch
    else if (out && !out.endsWith('_')) out += '_'
  }
  return out.replace(/^_+|_+$/g, '').slice(0, maxLength).replace(/_+$/g, '') || 'download'
}
