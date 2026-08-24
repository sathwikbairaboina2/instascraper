import { expect, test, type Page } from '@playwright/test'

// Cache state is shared across specs, so anything asserting "uncached" or
// "cached" stubs the media list rather than trusting the seed database.

async function withStatus(page: Page, shortcode: string, status: string) {
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === shortcode ? { ...i, full_status: status } : i,
    )
    await route.fulfill({ response: res, json: body })
  })
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('preview opens a lightbox without selecting the tile', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-0').click()

  await expect(page.getByTestId('lightbox')).toBeVisible()
  await expect(page.getByTestId('tile-nike-0')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByTestId('selection-count')).toHaveCount(0)
})

test('an uncached item previews the thumbnail with a fetch offer', async ({ page }) => {
  await withStatus(page, 'nike-0', 'none')
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-0').click()

  await expect(page.getByTestId('lightbox-placeholder')).toBeVisible()
  await expect(page.getByTestId('lightbox-placeholder')).toContainText('Not downloaded yet')
  await expect(page.getByTestId('lightbox-fetch')).toBeVisible()
})

test('a cached image previews full quality', async ({ page }) => {
  await withStatus(page, 'nike-0', 'ready')
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-0').click()

  await expect(page.getByTestId('lightbox-image')).toBeVisible()
  await expect(page.getByTestId('lightbox-image')).toHaveAttribute(
    'src',
    /\/api\/media\/nike-0\/full\?child=0/,
  )
})

test('a carousel steps through its children', async ({ page }) => {
  await withStatus(page, 'nike-6', 'ready')
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-6').click()

  await expect(page.getByTestId('lightbox-image')).toHaveAttribute('src', /child=1/)
  await page.getByTestId('lightbox-next').click()
  await expect(page.getByTestId('lightbox-image')).toHaveAttribute('src', /child=2/)
  await page.getByTestId('lightbox-prev').click()
  await expect(page.getByTestId('lightbox-image')).toHaveAttribute('src', /child=1/)
})

test('arrow keys navigate a carousel', async ({ page }) => {
  await withStatus(page, 'nike-6', 'ready')
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-6').click()

  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('lightbox-image')).toHaveAttribute('src', /child=2/)
})

test('escape closes the lightbox', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-1').click()
  await expect(page.getByTestId('lightbox')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.getByTestId('lightbox')).toHaveCount(0)
})

test('the lightbox swaps to full quality once the fetch lands', async ({ page }) => {
  // The React layer is what is under test, so the media list is stubbed:
  // "none" until the ensure call is seen, "ready" on every poll after it.
  let fetched = false
  await page.route('**/api/media/ensure', async (route) => {
    fetched = true
    await route.fulfill({ json: { statuses: { 'nike-0': 'ready' }, errors: {}, ready: 1, total: 1 } })
  })
  await page.route('**/api/profiles/nike/media**', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.items = body.items.map((i: Record<string, unknown>) =>
      i.shortcode === 'nike-0' ? { ...i, full_status: fetched ? 'ready' : 'none' } : i,
    )
    await route.fulfill({ response: res, json: body })
  })

  await page.goto('/p/nike')
  await page.getByTestId('preview-nike-0').click()
  await expect(page.getByTestId('lightbox-fetch')).toBeVisible()

  await page.getByTestId('lightbox-fetch').click()

  await expect(page.getByTestId('lightbox-image')).toBeVisible()
  await expect(page.getByTestId('lightbox-image')).toHaveAttribute(
    'src',
    /\/api\/media\/nike-0\/full\?child=0/,
  )
})
