import { expect, test } from '@playwright/test'

test('activity table renders the seeded log', async ({ page }) => {
  await page.goto('/activity')
  await expect(page.getByTestId('activity-table')).toBeVisible()
})

test('a download shows up in the activity log', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('base-filename').fill('activity_check')
  await page.getByTestId('download-submit').click()
  await expect(page.getByTestId('download-result')).toBeVisible({ timeout: 30_000 })

  await page.goto('/activity')

  const firstRow = page.getByTestId('activity-table').locator('tbody tr').first()
  await expect(firstRow).toContainText('download')
  await expect(firstRow).toContainText('activity_check')
})
