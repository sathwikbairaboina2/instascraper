import { expect, test } from '@playwright/test'

// Every downloaded file advertises the local url it is served from, so it
// can be pasted into another tab or tool without spelling the API route by
// hand.

test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

test('a downloaded tile offers its local url for copying', async ({ page }) => {
  await page.goto('/direct')
  await page.getByTestId('url-input').fill('https://www.instagram.com/p/nike-0/')
  await page.getByTestId('url-submit').click()

  // The worker fetches in the background; polling brings the tile in ready.
  const tile = page.getByTestId('tile-nike-0')
  await expect(tile).toBeVisible({ timeout: 20_000 })

  const copy = page.getByTestId('copy-url-nike-0')
  await expect(copy).toBeVisible()
  await copy.click()

  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe('http://localhost:3000/api/media/nike-0/full?child=0')

  // Copying must not double as selecting the tile.
  await expect(tile).toHaveAttribute('aria-pressed', 'false')
})

test('a carousel tile copies every slide url, comma separated', async ({ page }) => {
  await page.goto('/direct')
  await page.getByTestId('url-input').fill('https://www.instagram.com/p/nike-7/')
  await page.getByTestId('url-submit').click()
  await expect(page.getByTestId('tile-nike-7')).toBeVisible({ timeout: 20_000 })

  await page.getByTestId('copy-url-nike-7').click()
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(
      [1, 2, 3]
        .map((c) => `http://localhost:3000/api/media/nike-7/full?child=${c}`)
        .join(', '),
    )
})

test('the lightbox copies the url of the slide on show', async ({ page }) => {
  await page.goto('/direct')
  await page.getByTestId('url-input').fill('https://www.instagram.com/p/nike-6/')
  await page.getByTestId('url-submit').click()
  await expect(page.getByTestId('tile-nike-6')).toBeVisible({ timeout: 20_000 })

  await page.getByTestId('preview-nike-6').click()
  await expect(page.getByTestId('lightbox-image')).toBeVisible()

  // A carousel opens on slide 1; the copied url must follow the slide.
  const copy = page.getByTestId('lightbox-copy-url')
  await copy.click()
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe('http://localhost:3000/api/media/nike-6/full?child=1')

  await page.getByTestId('lightbox-next').click()
  await copy.click()
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe('http://localhost:3000/api/media/nike-6/full?child=2')
})
