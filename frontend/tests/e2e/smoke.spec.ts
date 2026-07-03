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

test('Train and Schedule are both live — no "Coming soon" stubs remain', async ({ page }) => {
  await page.goto(APP)

  // No labelled stubs remain after Phase 3.
  await expect(page.getByTestId('stub-train')).toHaveCount(0)
  await expect(page.getByTestId('stub-schedule')).toHaveCount(0)
  await expect(page.getByText('Coming soon')).toHaveCount(0)

  // Train is a live panel with a working submit button.
  await expect(page.getByRole('heading', { name: 'Train a model' })).toBeVisible()
  await expect(page.getByTestId('train-submit')).toBeEnabled()

  // Schedule is a live panel with a working create button.
  await expect(page.getByRole('heading', { name: 'Schedule recurring runs' })).toBeVisible()
  await expect(page.getByTestId('schedule-submit')).toBeEnabled()
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

test('schedule journey: create a schedule, Run now, see a run with a report link', async ({
  page,
}) => {
  await page.goto(APP)

  // Create a schedule from a fixture CSV with an interval.
  await page.getByTestId('schedule-file-input').setInputFiles(FIXTURE)
  await page.getByTestId('schedule-name-input').fill('E2E schedule')
  await page.getByTestId('schedule-interval-input').fill('60')
  await page.getByTestId('schedule-submit').click()

  // The new schedule appears in the list.
  const list = page.getByTestId('schedule-list')
  await expect(list).toBeVisible({ timeout: 30_000 })
  const item = list.getByTestId('schedule-item').filter({ hasText: 'E2E schedule' }).first()
  await expect(item).toBeVisible()
  await expect(item).toContainText('every 60 min')

  // Run now — synchronous EDA pipeline + LLM narrative; allow generous time.
  await item.getByTestId('schedule-run-now').click()

  // A completed run appears in this schedule's history with a report link.
  const run = item.getByTestId('schedule-run-history').getByTestId('schedule-run').first()
  await expect(run).toBeVisible({ timeout: 120_000 })
  await expect(run).toContainText('completed')

  const reportLink = run.getByTestId('schedule-run-report')
  await expect(reportLink).toBeVisible()
  await expect(reportLink).toHaveAttribute('href', /\/runs\/.+\/report/)
})

test('creating a schedule with no file shows inline validation', async ({ page }) => {
  await page.goto(APP)
  await page.getByTestId('schedule-submit').click()
  await expect(page.getByText('Choose a CSV file to schedule first.')).toBeVisible()
})
