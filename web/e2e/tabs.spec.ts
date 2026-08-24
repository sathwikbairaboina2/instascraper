import { expect, test } from '@playwright/test'

// Seeded: nike-0..5 photos, nike-6..7 carousels, nike-8..9 reels.

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const tiles = (page: import('@playwright/test').Page) =>
  page.getByTestId('media-grid').locator('.tile')

const pickTab = (page: import('@playwright/test').Page, label: string) =>
  page.getByTestId('profile-tabs').getByText(label, { exact: true }).click()

test('posts is the default tab and excludes reels', async ({ page }) => {
  await page.goto('/p/nike')

  await expect(tiles(page)).toHaveCount(8)
  await expect(page.getByTestId('tile-nike-8')).toHaveCount(0)
  await expect(page.getByTestId('tile-nike-0')).toBeVisible()
})

test('reels shows only reels', async ({ page }) => {
  await page.goto('/p/nike')
  await pickTab(page, 'REELS')

  await expect(tiles(page)).toHaveCount(2)
  await expect(page.getByTestId('tile-nike-8')).toBeVisible()
  await expect(page.getByTestId('tile-nike-9')).toBeVisible()
  await expect(page.getByTestId('tile-nike-0')).toHaveCount(0)
})

test('saved shows only what has been downloaded', async ({ page }) => {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>, idx: number) => ({
      ...i,
      full_status: idx < 3 ? 'ready' : 'none',
    }))
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await pickTab(page, 'SAVED')

  // Saved spans every surface: the three newest are two reels and a carousel.
  await expect(tiles(page)).toHaveCount(3)
})

test('the header reports posts, followers and indexed', async ({ page }) => {
  await page.goto('/p/nike')

  await expect(page.getByTestId('profile-username')).toHaveText('nike')
  await expect(page.getByTestId('profile-stat-posts')).toBeVisible()
  await expect(page.getByTestId('profile-stat-followers')).toBeVisible()
  await expect(page.getByTestId('profile-stat-indexed')).toContainText('10')
})

test('a profile that is mostly posts stays on posts', async ({ page }) => {
  // The seed is eight posts to two reels. Nothing to switch to.
  await page.goto('/p/nike')

  await expect(page.getByTestId('profile-tabs').getByText('POSTS', { exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(tiles(page)).toHaveCount(8)
})

test('a profile with no feed posts opens on reels rather than an empty grid', async ({
  page,
}) => {
  // Real accounts exist that post almost only reels: bbcnews indexed twelve
  // items, eleven of them reels. Opening on POSTS showed one tile.
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) => ({ ...i, kind: 'reel' }))
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')

  await expect(page.getByTestId('profile-tabs').getByText('REELS', { exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(tiles(page)).toHaveCount(10)
})

test('choosing a tab is never overridden', async ({ page }) => {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) => ({ ...i, kind: 'reel' }))
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await pickTab(page, 'POSTS')

  // Empty, and that is the answer to what was asked for.
  await expect(tiles(page)).toHaveCount(0)
  await expect(page.getByTestId('profile-tabs').getByText('POSTS', { exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
})
