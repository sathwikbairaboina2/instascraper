import { expect, test, type Page } from '@playwright/test'

// The recreate list is server state shared by every spec in this file, so
// each one clears it first rather than trusting what ran before.
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

test('a tile can be marked and shows a flag once it is', async ({ page }) => {
  await page.goto('/p/nike')

  await expect(page.getByTestId('recreate-flag-nike-0')).toHaveCount(0)
  await page.getByTestId('recreate-nike-0').click()

  await expect(page.getByTestId('recreate-flag-nike-0')).toBeVisible()
})

test('marking the same tile again removes it', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-0').click()
  await expect(page.getByTestId('recreate-flag-nike-0')).toBeVisible()

  await page.getByTestId('recreate-nike-0').click()

  await expect(page.getByTestId('recreate-flag-nike-0')).toHaveCount(0)
})

test('a whole selection can be sent at once', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-1').click()

  await page.getByTestId('send-to-recreate').click()

  await expect(page.getByTestId('recreate-flag-nike-0')).toBeVisible()
  await expect(page.getByTestId('recreate-flag-nike-1')).toBeVisible()
})

test('the list shows what was marked, and can drop it', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-2').click()
  await expect(page.getByTestId('recreate-flag-nike-2')).toBeVisible()

  await page.goto('/recreate')
  await expect(page.getByTestId('recreate-row-nike-2')).toBeVisible()
  await expect(page.getByTestId('recreate-tabs')).toContainText('Selected 1')

  await page.getByTestId('recreate-remove-nike-2').click()

  await expect(page.getByTestId('recreate-row-nike-2')).toHaveCount(0)
})

test('an empty list says how to fill it', async ({ page }) => {
  await page.goto('/recreate')

  await expect(page.getByTestId('recreate-empty')).toBeVisible()
})

test('an item opens its own page, which admits there is no generator', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-3').click()
  await expect(page.getByTestId('recreate-flag-nike-3')).toBeVisible()

  await page.goto('/recreate')
  await page.getByTestId('recreate-open-nike-3').click()

  await expect(page).toHaveURL(/\/recreate\/nike-3$/)
  await expect(page.getByTestId('no-generator')).toBeVisible()
  await expect(page.getByTestId('item-status')).toHaveText('selected')
})

test('the sidebar counts what is lined up', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-4').click()

  await expect(page.getByTestId('nav-recreate')).toContainText('1')
})

test('a reel can be marked', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('profile-tabs').getByText('REELS', { exact: true }).click()

  await page.getByTestId('recreate-nike-8').click()

  await expect(page.getByTestId('recreate-flag-nike-8')).toBeVisible()
  await page.goto('/recreate')
  await expect(page.getByTestId('recreate-row-nike-8')).toBeVisible()
})

test('a carousel can be marked', async ({ page }) => {
  await page.goto('/p/nike')

  await page.getByTestId('recreate-nike-6').click()

  await expect(page.getByTestId('recreate-flag-nike-6')).toBeVisible()
  await page.goto('/recreate')
  await expect(page.getByTestId('recreate-row-nike-6')).toBeVisible()
})

test('a marked item survives its cached thumbnail going away', async ({ page }) => {
  // The row is queued work and outlives the cache, but the picture is served
  // from that cache -- so the list has to cope with the image 404ing rather
  // than showing a broken frame.
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-5').click()
  await expect(page.getByTestId('recreate-flag-nike-5')).toBeVisible()

  await page.route('**/api/media/nike-5/thumb', (route) => route.fulfill({ status: 404 }))
  await page.goto('/recreate')

  await expect(page.getByTestId('recreate-row-nike-5')).toBeVisible()
  await expect(page.getByTestId('recreate-thumb-fallback-nike-5')).toBeVisible()
})

test('a tab with nothing in it says so without claiming the list is empty', async ({
  page,
}) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-1').click()
  await expect(page.getByTestId('recreate-flag-nike-1')).toBeVisible()

  await page.goto('/recreate')
  await page.getByTestId('recreate-tabs').getByText('Done 0', { exact: true }).click()

  await expect(page.getByTestId('recreate-empty')).toContainText('Nothing done right now')
  await expect(page.getByTestId('recreate-list')).toHaveCount(0)
})

test('a profile has a tab for what it has lined up', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-0').click()
  await expect(page.getByTestId('recreate-flag-nike-0')).toBeVisible()

  await page.getByTestId('profile-tabs').getByText('RECREATE', { exact: true }).click()

  await expect(page.getByTestId('tile-nike-0')).toBeVisible()
  await expect(page.getByTestId('tile-nike-1')).toHaveCount(0)
})

test('the recreate tab is empty until something is marked', async ({ page }) => {
  await page.goto('/p/nike')

  await page.getByTestId('profile-tabs').getByText('RECREATE', { exact: true }).click()

  await expect(page.getByTestId('media-grid').locator('.tile')).toHaveCount(0)
})

test('a tile in the recreate tab opens its item rather than selecting', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-4').click()
  await expect(page.getByTestId('recreate-flag-nike-4')).toBeVisible()

  await page.getByTestId('profile-tabs').getByText('RECREATE', { exact: true }).click()
  await page.getByTestId('tile-nike-4').click()

  await expect(page).toHaveURL(/\/recreate\/nike-4$/)
  await expect(page.getByTestId('no-generator')).toBeVisible()
})

test('a tile still selects on the other tabs', async ({ page }) => {
  // The open behaviour is scoped to one tab; everywhere else a click must
  // still build a selection, or download stops working.
  await page.goto('/p/nike')

  await page.getByTestId('tile-nike-0').click()

  await expect(page.getByTestId('selection-count')).toHaveText('1 selected')
})

test('a carousel offers its slides; a single post does not', async ({ page }) => {
  // nike-6 is a three-slide carousel in the seed; nike-0 is a lone photo.
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-6').click()
  await page.getByTestId('recreate-nike-0').click()
  await expect(page.getByTestId('recreate-flag-nike-0')).toBeVisible()

  await page.goto('/recreate/nike-6')
  await expect(page.getByTestId('slide-picker')).toBeVisible()
  await expect(page.getByTestId('slide-3')).toBeVisible()

  await page.goto('/recreate/nike-0')
  await expect(page.getByTestId('slide-picker')).toHaveCount(0)
})

test('every slide starts chosen and can be dropped', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-6').click()
  await expect(page.getByTestId('recreate-flag-nike-6')).toBeVisible()

  await page.goto('/recreate/nike-6')
  await expect(page.getByTestId('slide-picker')).toContainText('3 of 3 selected')

  await page.getByTestId('slide-2').click()

  await expect(page.getByTestId('slide-picker')).toContainText('2 of 3 selected')
  await expect(page.getByTestId('slide-2')).toHaveAttribute('aria-checked', 'false')
})

test('submitting downloads, builds the payload, and shows it read only', async ({
  page,
}) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-6').click()
  await expect(page.getByTestId('recreate-flag-nike-6')).toBeVisible()

  await page.goto('/recreate/nike-6')
  await page.getByTestId('slide-2').click()
  await page.getByTestId('prepare').click()

  const preview = page.getByTestId('payload-preview')
  await expect(preview).toBeVisible({ timeout: 30000 })
  await expect(preview).toContainText('"shortcode": "nike-6"')
  await expect(preview).toContainText('"index": 1')
  await expect(preview).toContainText('"index": 3')
  await expect(preview).not.toContainText('"index": 2')

  // Prepared is not submitted: nothing has reached a queue.
  await expect(page.getByTestId('not-submitted')).toBeVisible()
  await expect(page.getByTestId('item-status')).toHaveText('prepared')
})

test('a prepared payload is still there after a reload', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-7').click()
  await expect(page.getByTestId('recreate-flag-nike-7')).toBeVisible()

  await page.goto('/recreate/nike-7')
  await page.getByTestId('prepare').click()
  await expect(page.getByTestId('payload-preview')).toBeVisible({ timeout: 30000 })

  await page.reload()

  await expect(page.getByTestId('payload-preview')).toBeVisible()
  await expect(page.getByTestId('payload-preview')).toContainText('"shortcode": "nike-7"')
})

test('a prepared item moves to its own tab', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('recreate-nike-5').click()
  await expect(page.getByTestId('recreate-flag-nike-5')).toBeVisible()

  await page.goto('/recreate/nike-5')
  await page.getByTestId('prepare').click()
  await expect(page.getByTestId('payload-preview')).toBeVisible({ timeout: 30000 })

  await page.goto('/recreate')
  await expect(page.getByTestId('recreate-tabs')).toContainText('Prepared 1')
  await page.getByTestId('recreate-tabs').getByText('Prepared 1', { exact: true }).click()
  await expect(page.getByTestId('recreate-row-nike-5')).toBeVisible()
})
