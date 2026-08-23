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
