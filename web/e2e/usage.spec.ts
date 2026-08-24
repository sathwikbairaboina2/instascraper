import { expect, test } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('the quota readout is hidden when the adapter does not call Meta', async ({ page }) => {
  // The e2e stack runs the fake adapter, which reports no usage at all. A 0%
  // here would read as a measurement rather than an absence.
  await page.goto('/')
  await expect(page.getByTestId('usage-meter')).toHaveCount(0)
})

test('the quota readout shows the reported percentage', async ({ page }) => {
  await page.route('**/api/status', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    await route.fulfill({ response: res, json: { ...body, usage: 42 } })
  })

  await page.goto('/')

  await expect(page.getByTestId('usage-meter')).toHaveText('API 42%')
})
