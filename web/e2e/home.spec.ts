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

test('the home screen carries the banner and its own search', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('username-input')).toBeVisible()
  await expect(page.getByTestId('suggestions')).toBeVisible()
})

test('the sidebar search is hidden on home and present elsewhere', async ({ page }) => {
  // Two search boxes on one screen is a question about which is the real one.
  await page.goto('/')
  await expect(page.getByTestId('username-input')).toHaveCount(1)

  await page.goto('/p/nike')
  await expect(page.getByTestId('username-input')).toHaveCount(1)
  await expect(page.getByTestId('suggestions')).toHaveCount(0)
})

test('starter profiles are offered when nothing is tracked', async ({ page }) => {
  await page.route('**/api/profiles', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"items":[]}' })
  })

  await page.goto('/')

  await expect(page.getByTestId('suggestions')).toContainText('START WITH')
  await expect(page.getByTestId('suggestion-natgeo')).toBeVisible()
})

test('your own profiles replace the starters once you have some', async ({ page }) => {
  await page.route('**/api/profiles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            username: 'nike',
            full_name: 'Nike',
            post_count: 1669,
            avatar_url: '/api/profiles/nike/avatar',
            last_synced_at: null,
          },
        ],
      }),
    })
  })

  await page.goto('/')

  await expect(page.getByTestId('suggestions')).toContainText('YOUR PROFILES')
  await expect(page.getByTestId('suggestion-nike')).toContainText('1,669 posts')
  await expect(page.getByTestId('suggestion-natgeo')).toHaveCount(0)
})

test('a suggestion card looks the profile up', async ({ page }) => {
  await page.route('**/api/profiles', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"items":[]}' })
  })

  await page.goto('/')
  await page.getByTestId('suggestion-nike').click()

  await expect(page).toHaveURL(/\/p\/nike$/)
})
