import { expect, test, type Page } from '@playwright/test'

// The recreate queue is server state shared with the other specs, so this
// file leaves it exactly as it found it.
async function clearRecreate(page: Page) {
  const res = await page.request.get('/api/recreate')
  for (const item of (await res.json()).items) {
    await page.request.delete(`/api/recreate/${item.shortcode}`)
  }
}

test.beforeEach(async ({ page }) => {
  await clearRecreate(page)
})

test.afterEach(async ({ page }) => {
  await clearRecreate(page)
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('the nav reaches the feed and the day window has tags', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('nav-trending').click()

  await expect(page).toHaveURL(/\/trending$/)
  await expect(page.getByTestId('trending-row-nike')).toBeVisible()
  await expect(page.getByTestId('trending-score-nike')).not.toBeEmpty()
})

test('switching to the week window brings in older tags', async ({ page }) => {
  await page.goto('/trending')
  // #gear is on posts three days old: absent from the day window by design.
  await expect(page.getByTestId('trending-row-gear')).toHaveCount(0)

  await page.getByTestId('trending-window').getByText('Week').click()

  await expect(page.getByTestId('trending-row-gear')).toBeVisible()
})

test('switching back to day drops the week-only tags again', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-window').getByText('Week').click()
  await expect(page.getByTestId('trending-row-gear')).toBeVisible()

  await page.getByTestId('trending-window').getByText('Day').click()

  await expect(page.getByTestId('trending-row-gear')).toHaveCount(0)
})

test('load more appends a page without repeating rows', async ({ page }) => {
  // Small page size so the seeded dataset is enough to page at all.
  await page.route('**/api/hashtags/trending*', async (route) => {
    const url = new URL(route.request().url())
    url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  })

  await page.goto('/trending')
  await expect(page.locator('[data-testid^="trending-row-"]')).toHaveCount(1)
  await expect(page.getByTestId('trending-load-more')).toBeVisible()

  await page.getByTestId('trending-load-more').click()

  const rows = page.locator('[data-testid^="trending-row-"]')
  await expect(rows).toHaveCount(2)
  const ids = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
  expect(new Set(ids).size).toBe(2)
})

test('expanding a tag lists the posts behind it', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-expand-nike').click()

  await expect(page.getByTestId('trending-posts-nike')).toBeVisible()
  await expect(
    page.getByTestId('trending-posts-nike').locator('[data-testid^="trending-post-"]'),
  ).not.toHaveCount(0)
})

test('a post picked from a tag lands in the recreate queue', async ({ page }) => {
  await page.goto('/trending')
  await page.getByTestId('trending-expand-nike').click()

  const first = page
    .getByTestId('trending-posts-nike')
    .locator('[data-testid^="trending-post-"]')
    .first()
  const shortcode = (await first.getAttribute('data-testid'))!.replace('trending-post-', '')

  await first.click()
  await page.getByTestId('trending-mark-nike').click()

  await expect(page.getByTestId(`trending-marked-${shortcode}`)).toBeVisible()

  await page.goto('/recreate')
  await expect(page.getByTestId(`recreate-row-${shortcode}`)).toBeVisible()
})

test('an empty window says why it is empty', async ({ page }) => {
  await page.route('**/api/hashtags/trending*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        window: 'day',
        since: '2026-08-24T00:00:00+00:00',
        total: 0,
        items: [],
      }),
    }),
  )

  await page.goto('/trending')

  await expect(page.getByTestId('trending-empty')).toContainText('last 24 hours')
})
