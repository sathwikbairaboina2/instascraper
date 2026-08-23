import { expect, test } from '@playwright/test'

test('home lists the seeded tracked profile', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('tracked-profiles')).toContainText('nike')
})

test('submitting a username routes to the profile screen', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('username-input').fill('nike')
  await page.getByTestId('lookup-submit').click()
  await expect(page).toHaveURL(/\/p\/nike$/)
})

test('an empty username does not navigate', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('lookup-submit').click()
  await expect(page).toHaveURL(/\/$/)
})
