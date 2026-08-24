import { expect, test } from '@playwright/test'

// A profile the app has never seen 404s from /api/profiles/<name>. That 404
// means two different things, and the body says which: `last_error` is null
// while the sync is still in flight, and carries the reason once it failed.

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

async function notSyncedYet(page: import('@playwright/test').Page) {
  await page.route('**/api/profiles/ghost', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: { message: 'ghost has not been synced', last_error: null },
      }),
    })
  })
}

test('a profile still being fetched shows progress, not an error', async ({ page }) => {
  await notSyncedYet(page)

  await page.goto('/p/ghost')

  await expect(page.getByTestId('profile-loading')).toBeVisible()
  await expect(page.getByTestId('profile-loading')).toContainText('ghost')
  await expect(page.getByTestId('profile-error')).toHaveCount(0)
})

test('opening a profile directly asks for it to be fetched', async ({ page }) => {
  // Without this, a profile reached by url rather than by the search box
  // waits for a sync nobody ever queued.
  const syncs: string[] = []
  await page.route('**/api/profiles/ghost/sync', async (route) => {
    syncs.push(route.request().url())
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"queued":true}' })
  })
  await notSyncedYet(page)

  await page.goto('/p/ghost')
  await expect(page.getByTestId('profile-loading')).toBeVisible()

  expect(syncs.length).toBeGreaterThan(0)
})

test('a profile whose sync failed still shows the reason', async ({ page }) => {
  await page.route('**/api/profiles/ghost', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: {
          message: 'ghost has not been synced',
          last_error: 'ghost is not an Instagram Business account',
        },
      }),
    })
  })

  await page.goto('/p/ghost')

  await expect(page.getByTestId('profile-error')).toBeVisible()
  await expect(page.getByTestId('profile-loading')).toHaveCount(0)
})
