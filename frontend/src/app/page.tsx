'use client'

import { useRef, useState } from 'react'

type RunResult = {
  run_id: string
  status: 'completed' | 'failed'
  report_url: string | null
  narrative: string | null
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

      {/* Coming-soon stubs */}
      <section className="mt-14 grid gap-4 sm:grid-cols-2" aria-label="Upcoming features">
        <ComingSoon
          title="Train a model"
          phase="Phase 2"
          description="Fit a scikit-learn classifier on a labeled column, review evaluation metrics, and download the model artifact."
          testid="stub-train"
        />
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
