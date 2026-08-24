import { expect, test } from '@playwright/test'

// A tab that is hidden when the screen mounts, and is never uncovered, used
// to poll exactly once and then freeze: the fetch the user asked for finished
// on the server and the lightbox sat on the thumbnail forever. Hidden tabs
// now poll slowly instead of stopping.
test('a hidden tab still sees work it asked for finish', async ({ page }) => {
  test.setTimeout(60_000)

  await page.addInitScript(() => {
    Object.defineProperty(document, 'hidden', { get: () => true })
    Object.defineProperty(document, 'visibilityState', { get: () => 'hidden' })
  })

  // Paced like the real worker: the refresh fired straight after `ensure`
  // still reports "queued", so only a later poll can report "ready".
  let readyAt = 0
  await page.route('**/api/media/ensure', async (route) => {
    readyAt = Date.now() + 3000
    await route.fulfill({ json: { statuses: { 'nike-4': 'queued' }, errors: {}, ready: 0, total: 1 } })
  })
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    const status = readyAt === 0 ? 'none' : Date.now() >= readyAt ? 'ready' : 'queued'
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === 'nike-4' ? { ...i, full_status: status } : i,
    )
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-4').click()
  await page.getByTestId('lightbox-fetch').click()

  await expect(page.getByTestId('lightbox-image')).toBeVisible({ timeout: 40_000 })
})
