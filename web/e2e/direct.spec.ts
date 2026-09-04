import { expect, test } from '@playwright/test'

// The seeded fake dataset owns these posts; a pasted link to one of them is
// fetched by the worker through FakeAdapter.fetch_url the way a real link
// goes through yt-dlp.

test('an invalid link is reported, not queued', async ({ page }) => {
  await page.goto('/direct')
  await page.getByTestId('url-input').fill('https://example.com/nope')
  await page.getByTestId('url-submit').click()
  await expect(page.getByTestId('url-invalid')).toBeVisible()
})

test('a pasted post link lands in the grid as real media', async ({ page }) => {
  await page.goto('/direct')
  await page.getByTestId('url-input').fill('https://www.instagram.com/p/nike-0/')
  await page.getByTestId('url-submit').click()

  // The worker fetches in the background; polling brings the tile in.
  await expect(page.getByTestId('tile-nike-0')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('direct-counts')).toContainText('fetched')
})

test('a fetched tile selects and shows the selection rail', async ({ page }) => {
  await page.goto('/direct')
  const tile = page.getByTestId('tile-nike-0')
  await expect(tile).toBeVisible({ timeout: 20_000 })
  await tile.click()
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('selection-count')).toHaveText('1 selected')
})

test('the sidebar reaches the page', async ({ page }) => {
  await page.goto('/activity')
  await page.getByTestId('nav-direct').click()
  await expect(page).toHaveURL(/\/direct$/)
  await expect(page.getByTestId('url-input')).toBeVisible()
})
