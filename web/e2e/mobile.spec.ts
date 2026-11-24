import { expect, test, type Page } from '@playwright/test'

const sidewaysScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('the sider gives way to a top bar with a menu button', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByTestId('mobile-menu')).toBeVisible()
    await expect(page.locator('.app-sider')).toBeHidden()
    await expect(page.locator('.app-toolbar')).toBeHidden()
  })

  test('the menu opens, marks the current screen and closes on navigation', async ({ page }) => {
    await page.goto('/activity')
    await page.getByTestId('mobile-menu').click()

    const drawer = page.locator('.nav-drawer')
    await expect(drawer.getByTestId('nav-trending')).toBeVisible()
    await expect(drawer.getByRole('link', { name: 'Activity' })).toHaveAttribute('aria-current', 'page')
    await expect(drawer.getByRole('link', { name: 'Trending' })).not.toHaveAttribute('aria-current', 'page')

    await drawer.getByTestId('nav-trending').click()
    await expect(page).toHaveURL(/\/trending$/)
    await expect(page.locator('.nav-drawer .ant-drawer-content')).toBeHidden()
  })

  test('the menu marks the tracked profile being viewed', async ({ page }) => {
    await page.goto('/p/nike')
    await page.getByTestId('mobile-menu').click()
    const drawer = page.locator('.nav-drawer')
    await expect(drawer.getByRole('link', { name: /nike/ })).toHaveAttribute('aria-current', 'page')
  })

  test('the menu closes on its close button and hands focus back', async ({ page }) => {
    await page.goto('/')
    const open = page.getByTestId('mobile-menu')
    await open.click()
    await expect(page.locator('.nav-drawer').getByTestId('nav-direct')).toBeVisible()

    await page.locator('.nav-drawer .ant-drawer-close').click()
    await expect(page.locator('.nav-drawer .ant-drawer-content')).toBeHidden()
    await expect(open).toBeFocused()
  })

  test('the menu looks a profile up', async ({ page }) => {
    await page.goto('/activity')
    await page.getByTestId('mobile-menu').click()
    const drawer = page.locator('.nav-drawer')
    await drawer.getByTestId('username-input').fill('nike')
    await drawer.getByTestId('lookup-submit').click()
    await expect(page).toHaveURL(/\/p\/nike$/)
  })

  for (const route of ['/', '/p/nike', '/direct', '/recreate', '/trending', '/activity']) {
    test(`${route} does not scroll sideways`, async ({ page }) => {
      await page.goto(route)
      await expect(page.getByTestId('mobile-menu')).toBeVisible()
      await page.waitForTimeout(800)
      expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0)
    })
  }

  test('a tap selects a tile and a bar offers the actions in a sheet', async ({ page }) => {
    await page.goto('/p/nike')
    const panel = page.locator('.side-panel')
    await expect(panel).toBeHidden()
    await expect(page.getByTestId('selection-open')).toHaveCount(0)

    await page.getByTestId('tile-nike-0').tap()
    await expect(page.getByTestId('tile-nike-0')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('selection-bar-count')).toHaveText('1 selected')
    await expect(panel).toBeHidden()

    const opener = page.getByTestId('selection-open')
    await opener.tap()
    await expect(panel).toBeVisible()
    await expect(panel.getByTestId('download-submit')).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Close selection' })).toBeFocused()

    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(opener).toBeFocused()
  })

  test('the sheet closes when the selection is cleared', async ({ page }) => {
    await page.goto('/p/nike')
    await page.getByTestId('tile-nike-0').tap()
    await page.getByTestId('selection-open').tap()
    await page.getByTestId('clear-selection').tap()
    await expect(page.locator('.side-panel')).toBeHidden()
    await expect(page.getByTestId('selection-open')).toHaveCount(0)
  })

  test('the last tile is not hidden behind the selection bar', async ({ page }) => {
    await page.goto('/p/nike')
    await page.getByTestId('tile-nike-0').tap()
    const last = page.getByTestId('media-grid').locator('.tile').last()
    await last.scrollIntoViewIfNeeded()
    await page.evaluate(() => {
      const main = document.querySelector('.app-main')
      if (main) main.scrollTop = main.scrollHeight
    })
    const tile = await last.boundingBox()
    const bar = await page.locator('.sel-bar').boundingBox()
    expect(tile && bar && tile.y + tile.height <= bar.y + 1).toBe(true)
  })

  test('tile controls and navigation are at least 44 px', async ({ page }) => {
    await page.goto('/p/nike')
    for (const id of ['preview-nike-0', 'recreate-nike-0', 'copy-url-nike-0']) {
      const box = await page.getByTestId(id).boundingBox()
      expect(box, id).not.toBeNull()
      expect(box!.width, id).toBeGreaterThanOrEqual(44)
      expect(box!.height, id).toBeGreaterThanOrEqual(44)
    }
    for (const tab of await page.getByRole('tab').all()) {
      expect((await tab.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
  })

  test('the lightbox fills the screen and its controls are reachable', async ({ page }) => {
    await page.goto('/p/nike')
    await page.getByTestId('preview-nike-6').tap()
    await expect(page.getByTestId('lightbox')).toBeVisible()
    // The modal scales in, so wait for its settled width.
    await expect
      .poll(async () => (await page.locator('.lightbox .ant-modal').boundingBox())?.width ?? 0)
      .toBeGreaterThanOrEqual(389)
    await expect(page.getByTestId('lightbox-next')).toBeVisible()
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0)
  })

  test('the activity log stacks into one card per entry', async ({ page }) => {
    await page.goto('/activity')
    const row = page.getByTestId('activity-table').locator('tbody tr.ant-table-row').first()
    await expect(row).toBeVisible()
    await expect(row.locator('td').first()).toHaveAttribute('data-label', 'When')
    const box = await row.boundingBox()
    expect(box!.width).toBeLessThanOrEqual(390)
  })

  test('the stored theme still applies to the top bar', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Switch to (light|dark) theme/ }).click()
    await expect(page.getByRole('button', { name: /Switch to (light|dark) theme/ })).toBeVisible()
  })
})

test.describe('tablet', () => {
  test.use({ viewport: { width: 768, height: 1024 } })

  for (const route of ['/', '/p/nike', '/direct', '/recreate', '/trending', '/activity']) {
    test(`${route} does not scroll sideways`, async ({ page }) => {
      await page.goto(route)
      await page.waitForTimeout(800)
      expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0)
    })
  }

  test('keeps the sider and turns the inspector rail into a sheet', async ({ page }) => {
    await page.goto('/p/nike')
    await expect(page.getByTestId('tracked-profiles')).toBeVisible()
    await expect(page.getByTestId('mobile-menu')).toBeHidden()
    await expect(page.locator('.side-panel')).toBeHidden()

    await page.getByTestId('tile-nike-0').click()
    await expect(page.getByTestId('selection-bar-count')).toHaveText('1 selected')
    await page.getByTestId('selection-open').click()
    await expect(page.locator('.side-panel').getByTestId('download-submit')).toBeVisible()
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0)
  })
})

test.describe('desktop', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('keeps the sider and the inspector rail, with no phone chrome', async ({ page }) => {
    await page.goto('/p/nike')
    await expect(page.getByTestId('mobile-menu')).toBeHidden()
    await expect(page.locator('.sel-bar')).toHaveCount(0)
    await expect(page.getByTestId('tracked-profiles')).toBeVisible()
    await expect(page.locator('.side-panel')).toBeVisible()
    await expect(page.locator('.sheet-head')).toBeHidden()
    expect(await sidewaysScroll(page)).toBeLessThanOrEqual(0)
  })

  test('shows the toolbar readouts in the page itself', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('.app-toolbar')).toBeVisible()
    await expect(page.locator('.app-topbar')).toBeHidden()
  })
})
