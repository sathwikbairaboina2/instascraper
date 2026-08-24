import { expect, test } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

async function withLimits(page: import('@playwright/test').Page, hour: number, day: number) {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({
      response: res,
      json: {
        ...body,
        reel_limits: {
          hour: { used: hour, max: 20, resets_at: '2026-08-25T12:10:00+00:00' },
          day: { used: day, max: 100, resets_at: '2026-08-25T18:00:00+00:00' },
        },
      },
    })
  })
}

test('both reel windows render as progress', async ({ page }) => {
  await withLimits(page, 7, 31)
  await page.goto('/')

  await expect(page.getByTestId('reel-limit-hour')).toContainText('HOUR 7/20')
  await expect(page.getByTestId('reel-limit-day')).toContainText('DAY 31/100')
})

test('a spent window shows when headroom returns instead of a count', async ({ page }) => {
  await withLimits(page, 20, 40)
  await page.goto('/')

  // The count is no longer the useful number once there is nothing left.
  await expect(page.getByTestId('reel-limit-hour')).not.toContainText('20/20')
  await expect(page.getByTestId('reel-limit-day')).toContainText('DAY 40/100')
})

test('the bar fills in proportion to what has been spent', async ({ page }) => {
  await withLimits(page, 10, 25)
  await page.goto('/')

  const width = await page
    .getByTestId('reel-limit-hour-fill')
    .evaluate((el) => (el as HTMLElement).style.width)

  expect(width).toBe('50%')
})

test('the limits are hidden when the adapter does not scrape', async ({ page }) => {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({ response: res, json: { ...body, reel_limits: null } })
  })

  await page.goto('/')

  await expect(page.getByTestId('reel-limits')).toHaveCount(0)
})
