'use client'

import { useRef, useState } from 'react'

type RunResult = {
  run_id: string
  status: 'completed' | 'failed'
  report_url: string | null
  narrative: string | null
  error: string | null
}

type TrainResult = {
  train_id: string
  status: 'completed' | 'failed'
  task_type: 'classification' | 'regression' | null
  algorithm: string | null
  target_column: string | null
  metrics: Record<string, unknown> | null
  feature_columns: string[] | null
  artifact_url: string | null
  insight: string | null
  error: string | null
}

const MAX_BYTES = 50 * 1024 * 1024 // 50 MB — matches backend 413 limit

export default function Home() {
  const [file, setFile] = useState<File | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [validation, setValidation] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function pickFile(f: File | null) {
    setValidation(null)
    setError(null)
    if (!f) {
      setFile(null)
      return
    }
    const isCsv = f.name.toLowerCase().endsWith('.csv') || f.type === 'text/csv'
    if (!isCsv) {
      setValidation('Please choose a .csv file.')
      setFile(null)
      return
    }
    if (f.size === 0) {
      setValidation('That file is empty. Choose a CSV with data.')
      setFile(null)
      return
    }
    if (f.size > MAX_BYTES) {
      setValidation('That file is larger than 50 MB. Choose a smaller CSV.')
      setFile(null)
      return
    }
    setFile(f)
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragActive(false)
    pickFile(e.dataTransfer.files?.[0] ?? null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setValidation(null)
    setError(null)
    if (!file) {
      setValidation('Choose a CSV file to analyze first.')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch('/runs', { method: 'POST', body })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        const message =
          payload?.detail?.message ??
          payload?.detail ??
          `Request failed (${res.status})`
        setError(typeof message === 'string' ? message : `Request failed (${res.status})`)
        return
      }
      const data: RunResult | undefined = payload?.data
      if (!data) {
        setError('Unexpected response from the server.')
        return
      }
      if (data.status === 'failed' || data.error) {
        setError(
          `${data.error ?? 'The analysis run failed.'}${
            data.run_id ? ` (run ${data.run_id})` : ''
          }`,
        )
        setResult(data)
        return
      }
      setResult(data)
    } catch {
      setError('Network error — is the server running?')
    } finally {
      setLoading(false)
    }
  }

  const reportUrl = result?.report_url ?? null

  return (
    <main className="mx-auto max-w-4xl px-4 py-12 sm:py-16">
      <header className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          Data Analysis Agent
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-gray-600 sm:text-base">
          Upload a CSV dataset and get an automated exploratory-data-analysis report —
          summary statistics, missingness, sample rows, charts, and a written narrative.
        </p>
      </header>

      {/* Upload */}
      <section
        aria-labelledby="upload-heading"
        className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
      >
        <h2 id="upload-heading" className="text-lg font-semibold text-gray-900">
          Upload a dataset
        </h2>
        <form onSubmit={handleSubmit} className="mt-4">
          <div
            onDragOver={e => {
              e.preventDefault()
              setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
            }}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
              dragActive
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-300 bg-gray-50 hover:border-blue-400 hover:bg-blue-50/40'
            }`}
          >
            <svg
              className="h-10 w-10 text-gray-400"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
              />
            </svg>
            <p className="mt-3 text-sm font-medium text-gray-700">
              {file ? file.name : 'Drop a .csv file here, or click to browse'}
            </p>
            <p className="mt-1 text-xs text-gray-400">CSV up to 50 MB</p>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={e => pickFile(e.target.files?.[0] ?? null)}
              data-testid="file-input"
            />
          </div>

          {validation && (
            <p role="alert" className="mt-3 text-sm text-red-600">
              {validation}
            </p>
          )}

          <div className="mt-4 flex items-center gap-3">
            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading && (
                <svg
                  className="h-4 w-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              )}
              {loading ? 'Analyzing your dataset…' : 'Analyze'}
            </button>
            {file && !loading && (
              <span className="text-xs text-gray-500">Ready: {file.name}</span>
            )}
          </div>
        </form>
      </section>

      {/* Error card */}
      {error && (
        <div
          role="alert"
          className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-800"
        >
          <p className="font-semibold">Analysis failed</p>
          <p className="mt-1">{error}</p>
        </div>
      )}

      {/* Report */}
      {reportUrl && result?.status === 'completed' && (
        <section aria-labelledby="report-heading" className="mt-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="report-heading" className="text-lg font-semibold text-gray-900">
              Analysis report
            </h2>
            <a
              href={reportUrl}
              download
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-gray-50"
              data-testid="download-report"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
                />
              </svg>
              Download report
            </a>
          </div>

          {result?.narrative && (
            <div className="mt-4 rounded-2xl border border-blue-200 bg-blue-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
                Summary
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-blue-950">
                {result.narrative}
              </p>
            </div>
          )}

          <div className="mt-4 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
            <iframe
              src={reportUrl}
              title="EDA report"
              className="h-[70vh] min-h-[560px] w-full border-0"
              data-testid="report-iframe"
            />
          </div>
        </section>
      )}

      {/* Empty state */}
      {!reportUrl && !error && !loading && (
        <p className="mt-10 text-center text-sm text-gray-400">
          Your report will appear here after you analyze a dataset.
        </p>
      )}

      {/* Train a model (Phase 2 — live) */}
      <TrainPanel />

      {/* Coming-soon stubs */}
      <section className="mt-14 grid gap-4 sm:grid-cols-2" aria-label="Upcoming features">
        <ComingSoon
          title="Schedule recurring runs"
          phase="Phase 3"
          description="Save a pipeline, run it on a schedule, and deliver reports by email or webhook."
          testid="stub-schedule"
        />
      </section>
    </main>
  )
}

const ALGORITHMS: { value: string; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'logistic_regression', label: 'Logistic Regression' },
  { value: 'random_forest', label: 'Random Forest' },
]

// Human-friendly labels + formatting hints for the metrics table.
const METRIC_LABELS: Record<string, string> = {
  accuracy: 'Accuracy',
  f1: 'F1 (weighted)',
  precision: 'Precision (weighted)',
  recall: 'Recall (weighted)',
  n_classes: 'Classes',
  n_test: 'Test rows',
  r2: 'R²',
  mae: 'MAE',
  rmse: 'RMSE',
}

// Ordered so the most important metrics surface first; unknown keys append after.
const METRIC_ORDER = [
  'accuracy',
  'f1',
  'precision',
  'recall',
  'r2',
  'mae',
  'rmse',
  'n_classes',
  'n_test',
]

function formatMetric(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(3)
  }
  if (Array.isArray(value)) return value.join(', ')
  if (value == null) return '—'
  return String(value)
}

function orderedMetricEntries(metrics: Record<string, unknown>): [string, unknown][] {
  const keys = Object.keys(metrics).filter(k => k !== 'classes')
  keys.sort((a, b) => {
    const ia = METRIC_ORDER.indexOf(a)
    const ib = METRIC_ORDER.indexOf(b)
    if (ia === -1 && ib === -1) return a.localeCompare(b)
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  return keys.map(k => [k, metrics[k]])
}

function TrainPanel() {
  const [file, setFile] = useState<File | null>(null)
  const [columns, setColumns] = useState<string[]>([])
  const [target, setTarget] = useState('')
  const [algorithm, setAlgorithm] = useState('auto')
  const [dragActive, setDragActive] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TrainResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [validation, setValidation] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function parseHeader(f: File) {
    // Read only the first line client-side to populate the target-column select.
    const reader = new FileReader()
    reader.onload = () => {
      const text = typeof reader.result === 'string' ? reader.result : ''
      const firstLine = text.split(/\r?\n/)[0] ?? ''
      const cols = firstLine
        .split(',')
        .map(c => c.trim().replace(/^"|"$/g, '').trim())
        .filter(c => c.length > 0)
      setColumns(cols)
      // Default the target to the last column (common label position) if present.
      setTarget(cols.length ? cols[cols.length - 1] : '')
    }
    reader.onerror = () => {
      setColumns([])
      setTarget('')
      setValidation('Could not read that file. Choose a valid CSV.')
    }
    // Slice to the first 1 MB — enough to capture the header row of any CSV.
    reader.readAsText(f.slice(0, 1024 * 1024))
  }

  function pickFile(f: File | null) {
    setValidation(null)
    setError(null)
    setResult(null)
    setColumns([])
    setTarget('')
    if (!f) {
      setFile(null)
      return
    }
    const isCsv = f.name.toLowerCase().endsWith('.csv') || f.type === 'text/csv'
    if (!isCsv) {
      setValidation('Please choose a .csv file.')
      setFile(null)
      return
    }
    if (f.size === 0) {
      setValidation('That file is empty. Choose a CSV with data.')
      setFile(null)
      return
    }
    if (f.size > MAX_BYTES) {
      setValidation('That file is larger than 50 MB. Choose a smaller CSV.')
      setFile(null)
      return
    }
    setFile(f)
    parseHeader(f)
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragActive(false)
    pickFile(e.dataTransfer.files?.[0] ?? null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setValidation(null)
    setError(null)
    if (!file) {
      setValidation('Choose a labeled CSV file to train on first.')
      return
    }
    if (!target) {
      setValidation('Pick the target column to predict.')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('target_column', target)
      body.append('algorithm', algorithm)
      const res = await fetch('/train', { method: 'POST', body })
      const payload = await res.json().catch(() => null)
      if (!res.ok) {
        const message =
          payload?.detail?.message ??
          payload?.detail ??
          `Request failed (${res.status})`
        setError(typeof message === 'string' ? message : `Request failed (${res.status})`)
        return
      }
      const data: TrainResult | undefined = payload?.data
      if (!data) {
        setError('Unexpected response from the server.')
        return
      }
      if (data.status === 'failed' || data.error) {
        setError(
          `${data.error ?? 'Training failed.'}${
            data.train_id ? ` (train ${data.train_id})` : ''
          }`,
        )
        setResult(data)
        return
      }
      setResult(data)
    } catch {
      setError('Network error — is the server running?')
    } finally {
      setLoading(false)
    }
  }

  const completed = result?.status === 'completed'
  const metricEntries = completed && result?.metrics ? orderedMetricEntries(result.metrics) : []

  return (
    <section
      aria-labelledby="train-heading"
      className="mt-14 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
    >
      <div className="flex items-center justify-between">
        <h2 id="train-heading" className="text-lg font-semibold text-gray-900">
          Train a model
        </h2>
        <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
          Live
        </span>
      </div>
      <p className="mt-1 text-sm text-gray-600">
        Upload a labeled CSV, pick the target column and an algorithm, and train a
        scikit-learn model. Review the evaluation metrics and download the fitted model.
      </p>

      <form onSubmit={handleSubmit} className="mt-4">
        <div
          onDragOver={e => {
            e.preventDefault()
            setDragActive(true)
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
          }}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${
            dragActive
              ? 'border-emerald-500 bg-emerald-50'
              : 'border-gray-300 bg-gray-50 hover:border-emerald-400 hover:bg-emerald-50/40'
          }`}
        >
          <svg
            className="h-9 w-9 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
            />
          </svg>
          <p className="mt-3 text-sm font-medium text-gray-700">
            {file ? file.name : 'Drop a labeled .csv file here, or click to browse'}
          </p>
          <p className="mt-1 text-xs text-gray-400">CSV up to 50 MB</p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={e => pickFile(e.target.files?.[0] ?? null)}
            data-testid="train-file-input"
          />
        </div>

        {validation && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            {validation}
          </p>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Target column</span>
            <select
              value={target}
              onChange={e => setTarget(e.target.value)}
              disabled={columns.length === 0}
              data-testid="train-target-select"
              className="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
            >
              {columns.length === 0 ? (
                <option value="">Choose a CSV to list columns…</option>
              ) : (
                columns.map(c => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="block">
            <span className="text-sm font-medium text-gray-700">Algorithm</span>
            <select
              value={algorithm}
              onChange={e => setAlgorithm(e.target.value)}
              data-testid="train-algo-select"
              className="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {ALGORITHMS.map(a => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            data-testid="train-submit"
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading && (
              <svg
                className="h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
            )}
            {loading ? 'Training your model…' : 'Train model'}
          </button>
          {file && target && !loading && (
            <span className="text-xs text-gray-500">
              Ready: predict <span className="font-medium">{target}</span>
            </span>
          )}
        </div>
      </form>

      {/* Error card */}
      {error && (
        <div
          role="alert"
          className="mt-6 rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-800"
        >
          <p className="font-semibold">Training failed</p>
          <p className="mt-1">{error}</p>
        </div>
      )}

      {/* Metrics card */}
      {completed && (
        <div
          data-testid="train-metrics"
          className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-gray-900">Evaluation metrics</h3>
            {result?.artifact_url && (
              <a
                href={result.artifact_url}
                download
                data-testid="download-model"
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-white px-4 py-2 text-sm font-medium text-emerald-800 shadow-sm transition hover:bg-emerald-50"
              >
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={1.5}
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
                  />
                </svg>
                Download model
              </a>
            )}
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <div className="rounded-lg border border-emerald-200 bg-white px-3 py-2">
              <dt className="text-xs font-medium uppercase tracking-wide text-gray-500">
                Task type
              </dt>
              <dd className="mt-0.5 font-semibold text-gray-900">
                {result?.task_type ?? '—'}
              </dd>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-white px-3 py-2">
              <dt className="text-xs font-medium uppercase tracking-wide text-gray-500">
                Algorithm
              </dt>
              <dd className="mt-0.5 font-semibold text-gray-900">
                {result?.algorithm ?? '—'}
              </dd>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-white px-3 py-2">
              <dt className="text-xs font-medium uppercase tracking-wide text-gray-500">
                Target column
              </dt>
              <dd className="mt-0.5 font-semibold text-gray-900">
                {result?.target_column ?? '—'}
              </dd>
            </div>
          </dl>

          {metricEntries.length > 0 && (
            <div className="mt-4 overflow-hidden rounded-lg border border-emerald-200 bg-white">
              <table className="w-full text-sm">
                <tbody>
                  {metricEntries.map(([key, value], i) => (
                    <tr
                      key={key}
                      className={i % 2 === 0 ? 'bg-white' : 'bg-emerald-50/40'}
                    >
                      <th
                        scope="row"
                        className="px-3 py-2 text-left font-medium text-gray-600"
                      >
                        {METRIC_LABELS[key] ?? key}
                      </th>
                      <td className="px-3 py-2 text-right font-mono text-gray-900">
                        {formatMetric(value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result?.insight && (
            <div className="mt-4 rounded-lg border border-emerald-200 bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                Insight
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
                {result.insight}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!completed && !error && !loading && (
        <p className="mt-6 text-center text-sm text-gray-400">
          Your model metrics will appear here after training.
        </p>
      )}
    </section>
  )
}

function ComingSoon({
  title,
  phase,
  description,
  testid,
}: {
  title: string
  phase: string
  description: string
  testid: string
}) {
  return (
    <div
      className="relative rounded-2xl border border-dashed border-gray-300 bg-gray-50/60 p-5 opacity-90"
      data-testid={testid}
      aria-disabled="true"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-gray-500">{title}</h3>
        <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
          Coming soon
        </span>
      </div>
      <p className="mt-2 text-sm text-gray-400">{description}</p>
      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-lg bg-gray-200 px-4 py-2 text-sm font-medium text-gray-400"
        >
          {title}
        </button>
        <span className="text-xs font-medium text-gray-400">{phase}</span>
      </div>
    </div>
  )
}
