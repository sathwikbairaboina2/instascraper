import { expect, test } from '@playwright/test'

// The toggle is disabled while Graph is the only source in use, so these
// three specs cannot drive it. Re-enable them together with the control:
// drop `disabled` in AppShell and delete this skip.
test.describe.configure({ mode: 'serial' })
test.skip(true, 'adapter switching is disabled: Graph-only mode')

// antd Segmented hides the real radio input, so clicks go to the visible
// label and assertions go to the input, which is where checked state lives.
// 'Graph' must be matched exactly: the theme picker in the same header
// offers a 'Graphite' option, and Playwright matches names by substring.
// This spec is the only one that mutates server-wide state: switching the
// adapter changes which database every later spec reads. The suite runs
// with workers:1 and fullyParallel:false, so sequencing is safe, but the
// restore below is mandatory -- without it every spec that runs after this
// file sees an empty dataset.
test.afterAll(async ({ request }) => {
  await request.post('/api/adapter', { data: { adapter: 'fake' } })
})

test('the header shows which dataset is live', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('radio', { name: 'Fake', exact: true })).toBeChecked()
})

test('switching asks for confirmation and can be cancelled', async ({ page }) => {
  await page.goto('/')
  // Wait for status before clicking: until it arrives no option is selected.
  await expect(page.getByRole('radio', { name: 'Fake', exact: true })).toBeChecked()
  await page.getByText('Graph', { exact: true }).click()

  // Assert the dialog appears, not its exact wording -- the subject here is
  // that a switch is confirmed, not the copy used to confirm it.
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  await expect(page.getByRole('radio', { name: 'Fake', exact: true })).toBeChecked()
})

test('confirming the switch reloads onto the other dataset', async ({ page }) => {
  await page.goto('/')
  // Wait for status before clicking: until it arrives no option is selected.
  await expect(page.getByRole('radio', { name: 'Fake', exact: true })).toBeChecked()
  await page.getByText('Graph', { exact: true }).click()
  await page.getByRole('button', { name: 'Switch' }).click()

  await page.waitForURL('**/')
  await expect(page.getByRole('radio', { name: 'Graph', exact: true })).toBeChecked()

  // The graph database is a separate file and nothing has ever synced into
  // it, so the seeded fake profile is not merely hidden -- it is not there.
  await expect(page.getByText('nike')).toHaveCount(0)
})
