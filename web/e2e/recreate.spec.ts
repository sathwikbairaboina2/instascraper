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
  await expect(page.getByTestId('recreate-status-nike-2')).toHaveText('Selected')

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
