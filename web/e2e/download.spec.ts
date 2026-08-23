import { expect, test } from '@playwright/test'

test('selection bar appears only when something is selected', async ({ page }) => {
  await page.goto('/p/nike')
  await expect(page.getByTestId('selection-bar')).toHaveCount(0)
  await page.getByTestId('tile-nike-0').click()
  await expect(page.getByTestId('selection-bar')).toBeVisible()
})

test('downloading three items reports the output directory', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('tile-nike-1').click()
  await page.getByTestId('tile-nike-2').click()

  await page.getByTestId('base-filename').fill('e2e_set')
  await page.getByTestId('download-submit').click()

  await expect(page.getByTestId('download-result')).toContainText('3 files', {
    timeout: 30_000,
  })
})

test('selecting every post downloads one file per carousel child', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('select-all').click()
  await page.getByTestId('base-filename').fill('e2e_all')
  await page.getByTestId('download-submit').click()

  await expect(page.getByTestId('download-result')).toBeVisible({ timeout: 60_000 })
  // 8 posts, but two of them are 3-slide carousels: 6 + 3 + 3 = 12 files.
  await expect(page.getByTestId('download-result')).toContainText('12 files')
})

test('an empty base filename is rejected before any request', async ({ page }) => {
  await page.goto('/p/nike')
  await page.getByTestId('tile-nike-0').click()
  await page.getByTestId('base-filename').fill('   ')
  await page.getByTestId('download-submit').click()
  await expect(page.getByTestId('download-error')).toContainText('filename')
})
