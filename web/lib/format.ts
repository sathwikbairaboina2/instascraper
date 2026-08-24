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
