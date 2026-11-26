import assert from 'node:assert/strict'
import { test } from 'node:test'

import { modeFromMessage, modeFromSearch, panelOrigins } from './themeSync.ts'

const allowed = panelOrigins(undefined)

test('reads light or dark from the url, and nothing else', () => {
  assert.equal(modeFromSearch('?theme=dark'), 'dark')
  assert.equal(modeFromSearch('?a=1&theme=light'), 'light')
  assert.equal(modeFromSearch('?theme=sepia'), null)
  assert.equal(modeFromSearch('?theme='), null)
  assert.equal(modeFromSearch(''), null)
})

test('accepts the panel origins and rejects others', () => {
  for (const origin of [
    'http://localhost:28100',
    'http://127.0.0.1:28100',
    'http://localhost:28101',
    'http://127.0.0.1:28101',
    'https://beast.tail88cf35.ts.net:8444',
  ]) {
    assert.equal(modeFromMessage({ origin, data: { type: 'insta-theme', mode: 'dark' } }, allowed), 'dark', origin)
  }
  assert.equal(modeFromMessage({ origin: 'https://evil.example', data: { type: 'insta-theme', mode: 'dark' } }, allowed), null)
  assert.equal(modeFromMessage({ origin: 'http://localhost:3000', data: { type: 'insta-theme', mode: 'dark' } }, allowed), null)
})

test('ignores payloads that are not a theme message', () => {
  const origin = 'http://localhost:28100'
  for (const data of [null, undefined, 'dark', 42, {}, { type: 'other', mode: 'dark' }, { type: 'insta-theme' }, { type: 'insta-theme', mode: 'blue' }]) {
    assert.equal(modeFromMessage({ origin, data }, allowed), null)
  }
})

test('takes extra origins from the env value', () => {
  const extra = panelOrigins(' https://panel.example.com , http://10.0.0.5:28100/ ,not a url,')
  assert.ok(extra.includes('https://panel.example.com'))
  assert.ok(extra.includes('http://10.0.0.5:28100'))
  assert.ok(extra.includes('http://localhost:28100'))
  assert.equal(extra.length, allowed.length + 2)
  assert.equal(modeFromMessage({ origin: 'https://panel.example.com', data: { type: 'insta-theme', mode: 'light' } }, extra), 'light')
  assert.equal(modeFromMessage({ origin: 'https://panel.example.com', data: { type: 'insta-theme', mode: 'light' } }, allowed), null)
})
