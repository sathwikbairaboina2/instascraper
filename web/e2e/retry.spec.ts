import { expect, test, type Page } from '@playwright/test'

// The seeded dataset never fails, and adding a permanently-failing item would
// break the select-all download test. So the failed state is produced by
// intercepting the API instead.

const REASON = 'connection reset by peer'

/** Make nike-0 come back as failed, leaving every other tile healthy. */
async function failFirstTile(page: Page) {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === 'nike-0'
        ? { ...i, full_status: 'failed', full_error: REASON }
        : i,
    )
    await route.fulfill({ response: res, json: body })
  })
}

// The profile screen polls every 4s, so a route callback can still be in
// flight when the page closes. Without this the teardown throws even though
// the assertions passed.
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('a failed item shows its reason on the tile', async ({ page }) => {
  await failFirstTile(page)
  await page.goto('/p/nike')

  const failed = page.getByTestId('failed-nike-0')
  await expect(failed).toBeVisible()
  await expect(failed).toContainText(REASON)
  await expect(page.getByTestId('retry-nike-0')).toBeVisible()
})

test('healthy tiles show no failure overlay', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('tile-nike-1')).toBeVisible()
  await expect(page.getByTestId('failed-nike-1')).toHaveCount(0)
})

test('per-tile retry re-requests the item with retry set', async ({ page }) => {
  await failFirstTile(page)

  const ensureCalls: Array<Record<string, unknown>> = []
  await page.route('**/api/media/ensure', async (route) => {
    ensureCalls.push(route.request().postDataJSON())
    await route.fulfill({
      json: { statuses: { 'nike-0': 'queued' }, errors: {}, ready: 0, total: 1 },
    })
  })

  await page.goto('/p/nike')
  await page.getByTestId('retry-nike-0').click()

  await expect.poll(() => ensureCalls.length).toBeGreaterThan(0)
  expect(ensureCalls[0]).toEqual({ shortcodes: ['nike-0'], retry: true })
})

test('retrying does not toggle the tile selection', async ({ page }) => {
  await failFirstTile(page)
  await page.route('**/api/media/ensure', (route) =>
    route.fulfill({
      json: { statuses: { 'nike-0': 'queued' }, errors: {}, ready: 0, total: 1 },
    }),
  )

  await page.goto('/p/nike')
  await page.getByTestId('retry-nike-0').click()

  await expect(page.getByTestId('tile-nike-0')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByTestId('selection-count')).toHaveCount(0)
})

test('the selection bar names which items failed', async ({ page }) => {
  await page.route('**/api/media/ensure', (route) =>
    route.fulfill({
      json: {
        statuses: { 'nike-0': 'failed' },
        errors: { 'nike-0': '429 rate limited' },
        ready: 0,
        total: 1,
      },
    }),
  )

  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('base-filename').fill('retry_check')
  await page.getByTestId('download-submit').click()

  const err = page.getByTestId('download-error')
  await expect(err).toContainText('nike-0')
  await expect(err).toContainText('429 rate limited')
})
