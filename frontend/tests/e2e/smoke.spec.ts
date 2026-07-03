import { test, expect } from '@playwright/test'
import path from 'node:path'

/**
 * Primary-journey smoke test for the Data Analysis Agent dashboard.
 *
 * Runs against the real running app (FastAPI serving the static export at
 * /app/, same-origin with the /runs API). It uploads a fixture CSV, waits for
 * the synchronous run to complete, and asserts the report iframe + download
 * button render and the "Coming soon" stubs are present and disabled.
 */

const APP = '/app/'
const FIXTURE = path.resolve(__dirname, 'fixtures/sample.csv')

test('page loads, is styled, and shows the upload UI', async ({ page }) => {
  await page.goto(APP)
  await expect(page.getByRole('heading', { name: 'Data Analysis Agent' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Analyze' })).toBeVisible()

  // Styled (Tailwind loaded): the analyze button has a non-default background.
  const bg = await page
    .getByRole('button', { name: 'Analyze' })
    .evaluate(el => getComputedStyle(el).backgroundColor)
  expect(bg).not.toBe('rgba(0, 0, 0, 0)')
})

test('coming-soon stubs are labelled and disabled', async ({ page }) => {
  await page.goto(APP)
  const train = page.getByTestId('stub-train')
  const schedule = page.getByTestId('stub-schedule')
  await expect(train).toBeVisible()
  await expect(schedule).toBeVisible()
  await expect(train.getByText('Coming soon')).toBeVisible()
  await expect(schedule.getByText('Coming soon')).toBeVisible()
  await expect(train.getByRole('button')).toBeDisabled()
  await expect(schedule.getByRole('button')).toBeDisabled()
})

test('upload a CSV, run EDA, and see the report + download button', async ({ page }) => {
  await page.goto(APP)

  await page.getByTestId('file-input').setInputFiles(FIXTURE)
  await page.getByRole('button', { name: 'Analyze' }).click()

  // Synchronous run — allow generous time for the real pipeline + LLM call.
  const iframe = page.getByTestId('report-iframe')
  await expect(iframe).toBeVisible({ timeout: 90_000 })
  await expect(iframe).toHaveAttribute('src', /\/runs\/.+\/report/)

  await expect(page.getByTestId('download-report')).toBeVisible()
  await expect(page.getByTestId('download-report')).toHaveAttribute('download', '')

  // Report content renders inside the iframe.
  await expect(page.frameLocator('[data-testid="report-iframe"]').locator('body')).toContainText(
    /./,
  )
})

test('submitting with no file shows inline validation', async ({ page }) => {
  await page.goto(APP)
  await page.getByRole('button', { name: 'Analyze' }).click()
  await expect(page.getByText('Choose a CSV file to analyze first.')).toBeVisible()
})
