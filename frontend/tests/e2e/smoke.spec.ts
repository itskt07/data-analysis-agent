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
// Larger, class-separable dataset (240 rows, 3 classes) so the 0.75/0.25 split
// yields a meaningful test set and non-degenerate metrics.
const TRAIN_FIXTURE = path.resolve(__dirname, 'fixtures/train.csv')
const TRAIN_TARGET = 'species'

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

test('the Schedule stub is labelled and disabled (Train is now live)', async ({ page }) => {
  await page.goto(APP)

  // Schedule stays a labelled Phase-3 "Coming soon" stub.
  const schedule = page.getByTestId('stub-schedule')
  await expect(schedule).toBeVisible()
  await expect(schedule.getByText('Coming soon')).toBeVisible()
  await expect(schedule.getByRole('button')).toBeDisabled()

  // Train is no longer a stub — it's a live panel with a working submit button.
  await expect(page.getByTestId('stub-train')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Train a model' })).toBeVisible()
  await expect(page.getByTestId('train-submit')).toBeEnabled()
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

test('train a model: upload labeled CSV, pick target, train, see metrics + download', async ({
  page,
}) => {
  await page.goto(APP)

  // Choose a labeled CSV — the header row is parsed client-side to populate the
  // target-column select.
  await page.getByTestId('train-file-input').setInputFiles(TRAIN_FIXTURE)

  const targetSelect = page.getByTestId('train-target-select')
  // Wait for the select to be populated with the fixture's columns.
  await expect(targetSelect.locator(`option[value="${TRAIN_TARGET}"]`)).toHaveCount(1)
  await targetSelect.selectOption(TRAIN_TARGET)

  // Keep the default Auto algorithm.
  await expect(page.getByTestId('train-algo-select')).toHaveValue('auto')

  await page.getByTestId('train-submit').click()

  // Training is synchronous (fit + evaluate + non-fatal LLM insight) — allow
  // generous time for the real pipeline.
  const metrics = page.getByTestId('train-metrics')
  await expect(metrics).toBeVisible({ timeout: 120_000 })
  await expect(metrics).toContainText('classification')

  const download = page.getByTestId('download-model')
  await expect(download).toBeVisible()
  await expect(download).toHaveAttribute('download', '')
  await expect(download).toHaveAttribute('href', /\/train\/.+\/artifact/)
})
