import { expect, test } from '@playwright/test'

// Seeded dataset: nike-0..nike-5 photos, nike-6 and nike-7 three-slide
// carousels, nike-8 and nike-9 reels. POSTS is the default tab and holds the
// eight non-reels.

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const tiles = (page: import('@playwright/test').Page) =>
  page.getByTestId('media-grid').locator('.tile')

// antd Segmented renders labelled radios, not a native <select>. The label,
// not the input, is what is actually clickable.
const pickTab = (page: import('@playwright/test').Page, label: string) =>
  page.getByTestId('profile-tabs').getByText(label, { exact: true }).click()

test('caption search filters by text', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('filter-query').fill('caption 3')
  await expect(tiles(page)).toHaveCount(1)
  await expect(page.getByTestId('tile-nike-3')).toBeVisible()
})

test('cached-only keeps exactly the downloaded items', async ({ page }) => {
  // Other specs download media into the shared seed database, so the cache is
  // not empty by the time this runs. Stub the list instead of assuming.
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    // The three oldest are photos. Marking the newest three would mark the
    // two reels, which the POSTS tab excludes anyway.
    body.items = body.items.map((i: Record<string, unknown>, idx: number) => ({
      ...i,
      full_status: idx >= body.items.length - 3 ? 'ready' : 'none',
    }))
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await expect(tiles(page)).toHaveCount(8)

  await page.getByTestId('filter-cached').click()

  await expect(tiles(page)).toHaveCount(3)
  await expect(page.getByTestId('filter-count')).toHaveText('3 of 8 shown')
})

test('reset restores the full grid', async ({ page }) => {
  await page.goto('/p/nike')
  await pickTab(page, 'REELS')
  await expect(tiles(page)).toHaveCount(2)

  await page.getByTestId('filter-reset').click()

  await expect(tiles(page)).toHaveCount(8)
})

test('select all respects the active filter', async ({ page }) => {
  await page.goto('/p/nike')
  await pickTab(page, 'REELS')
  await page.getByTestId('select-all').click()

  await expect(page.getByTestId('selection-count')).toHaveText('2 selected')
})

test('a saved selection can be stored and reloaded', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-1').click()
  await page.getByTestId('save-name').fill('pair')
  await page.getByTestId('save-selection').click()

  await page.getByTestId('clear-selection').click()
  await expect(page.getByTestId('selection-count')).toHaveCount(0)

  await page.getByTestId('load-selection-pair').click()
  await expect(page.getByTestId('selection-count')).toHaveText('2 selected')
})

test('a saved selection survives a reload and can be deleted', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-2').click()
  await page.getByTestId('save-name').fill('single')
  await page.getByTestId('save-selection').click()

  await page.reload()
  await expect(page.getByTestId('load-selection-single')).toBeVisible()

  await page.getByTestId('delete-selection-single').click()
  await expect(page.getByTestId('load-selection-single')).toHaveCount(0)
})
