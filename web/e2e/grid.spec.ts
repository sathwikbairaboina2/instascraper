import { expect, test } from '@playwright/test'

test('grid renders seeded tiles newest first', async ({ page }) => {
  await page.goto('/p/nike')
  // .tile, not every button: each tile now also carries a preview control.
  await expect(page.getByTestId('media-grid').locator('.tile')).toHaveCount(8)
})

test('clicking a tile selects it', async ({ page }) => {
  await page.goto('/p/nike')
  const tile = page.getByTestId('tile-nike-0')
  await tile.click()
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('selection-count')).toHaveText('1 selected')
})

test('shift-click selects an inclusive range', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-3').click({ modifiers: ['Shift'] })
  await expect(page.getByTestId('selection-count')).toHaveText('4 selected')
})

test('select all then clear', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('select-all').click()
  await expect(page.getByTestId('selection-count')).toHaveText('8 selected')
  await page.getByTestId('clear-selection').click()
  await expect(page.getByTestId('selection-count')).toHaveCount(0)
})

test('load more is disabled once the profile is exhausted', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('load-more')).toBeDisabled()
})

test('carousel tiles show a child count badge', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('tile-nike-6').getByText('3')).toBeVisible()
})

test('a tile shows its engagement on hover', async ({ page }) => {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === 'nike-0'
        ? { ...i, like_count: 72692, comments_count: 342, view_count: null }
        : i,
    )
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').hover()

  const stats = page.getByTestId('engagement-nike-0')
  await expect(stats).toContainText('72.7K')
  await expect(stats).toContainText('342')
})

test('a photo shows no view count', async ({ page }) => {
  // Business Discovery reports views for reels only; zero would claim nobody
  // watched something that was never watchable.
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === 'nike-0'
        ? { ...i, like_count: 10, comments_count: 2, view_count: null }
        : { ...i, like_count: 10, comments_count: 2, view_count: 3256857 },
    )
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').hover()

  await expect(page.getByTestId('engagement-nike-0')).not.toContainText('3.3M')
  await page.getByTestId('tile-nike-1').hover()
  await expect(page.getByTestId('engagement-nike-1')).toContainText('3.3M')
})
