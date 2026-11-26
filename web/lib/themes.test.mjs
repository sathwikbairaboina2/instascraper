import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { IG, layoutTokens } from './themes.ts'

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const luminance = (rgb) => {
  const [r, g, b] = rgb.map((c) => c / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const over = (fg, alpha, bg) => fg.map((c, i) => Math.round(c * alpha + bg[i] * (1 - alpha)))

test('the content area uses the shared ground and surfaces sit on #fafafa, not antd derived greys', () => {
  assert.deepEqual(layoutTokens(IG.light), { colorBgLayout: '#ffffff', colorBgContainer: '#fafafa' })
  assert.deepEqual(layoutTokens(IG.dark), { colorBgLayout: '#000000', colorBgContainer: '#121212' })
})

test('the layout ground is never the derived near white (#f4f4f4 / #f5f5f5)', () => {
  for (const t of [IG.light, IG.dark]) {
    const { colorBgLayout } = layoutTokens(t)
    assert.ok(!['#f4f4f4', '#f5f5f5'].includes(colorBgLayout.toLowerCase()))
  }
})

test('the Graph / Fake readout takes the muted text token and the fill token in both modes', () => {
  const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8')
  const rule = css.match(/\.adapter-switch[^{]*\{[^}]*\}/g)?.join('\n') ?? ''
  assert.match(rule, /--ant-color-text-secondary/)
  assert.match(rule, /--ant-color-fill-secondary/)
})

test('muted text reads at 4.5:1 on the track fill in both modes', () => {
  // antd's colorFillSecondary: the text colour at 6% (light) or white at 12% (dark), over the ground.
  const cases = [
    { t: IG.light, fill: over(hex(IG.light.text), 0.06, hex(layoutTokens(IG.light).colorBgLayout)) },
    { t: IG.dark, fill: over([255, 255, 255], 0.12, hex(layoutTokens(IG.dark).colorBgLayout)) },
  ]
  for (const { t, fill } of cases) {
    const ratio = contrast(hex(t.textSecondary), fill)
    assert.ok(ratio >= 4.5, `${t.text} mode ratio ${ratio.toFixed(2)}`)
  }
})
