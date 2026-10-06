import { useMemo, useState } from 'react'
import { File, GitMerge, Users } from 'lucide-react'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  getMetricsAuthors,
  getMetricsFiles,
  getMetricsSeries,
  getMetricsSummary,
  hQuery,
} from '../api'
import { formatNumber } from '../format'
import { useFetch } from '../hooks'
import { Card, Chip, EmptyState, ErrorNote, MiniBar, PendingNote, Spinner, metricsState } from '../ui'

const AXIS = { fill: '#94a3b8', fontSize: 11 }
const TOOLTIP_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  borderRadius: 6,
  fontSize: 12,
}
const COLORS = { added: '#34d399', removed: '#fb7185', churn: '#fbbf24' }

function formatRate(value) {
  return value === null || value === undefined ? '–' : Number(value).toFixed(2)
}

/** Render one fetched panel body with consistent loading/pending/error states. */
function PanelBody({ fetch, endpoint, children }) {
  if (fetch.loading && !fetch.data) return <Spinner />
  if (fetch.error) {
    return metricsState(fetch.error) === 'pending' ? (
      <PendingNote endpoint={endpoint} onRetry={fetch.reload} />
    ) : (
      <ErrorNote error={fetch.error} onRetry={fetch.reload} />
    )
  }
  if (!fetch.data) return null
  return children(fetch.data)
}

const SUMMARY_TILES = [
  { key: 'commits', label: 'Commits |H|', hint: 'Size of the selected commit set' },
  { key: 'authors', label: 'Authors', hint: 'Distinct canonical authors in H' },
  { key: 'files', label: 'Files', hint: 'Files touched by commits in H (new paths after renames)' },
  { key: 'added', label: 'l⁺ added', tone: 'text-emerald-300', hint: 'Lines added across H' },
  { key: 'removed', label: 'l⁻ removed', tone: 'text-rose-300', hint: 'Lines removed across H' },
  { key: 'growth', label: 'δ growth', hint: 'δ = l⁺ − l⁻' },
  { key: 'churn', label: 'λ churn', tone: 'text-amber-300', hint: 'λ = l⁺ + l⁻' },
  { key: 'modifications', label: 'n modifications', hint: 'Commits in H that changed the entity (λ > 0)' },
  { key: 'frequency', label: 'η frequency', hint: 'η = n / |H|' },
  { key: 'churn_rate', label: 'ρ churn rate', hint: 'ρ = λ / |H|' },
]

function SummaryTiles({ data }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {SUMMARY_TILES.map((tile) => {
        const value = data[tile.key]
        const isGrowth = tile.key === 'growth'
        const tone =
          tile.tone ??
          (isGrowth && value != null ? (value >= 0 ? 'text-emerald-300' : 'text-rose-300') : 'text-slate-100')
        const display =
          tile.key === 'frequency' || tile.key === 'churn_rate'
            ? formatRate(value)
            : formatNumber(value)
        return (
          <div
            key={tile.key}
            title={tile.hint}
            className="rounded-md border border-surface-border bg-surface px-3 py-2"
          >
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {tile.label}
            </p>
            <p className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{display}</p>
          </div>
        )
      })}
    </div>
  )
}

function SeriesPanel({ fetch, bucket, onBucketChange }) {
  return (
    <Card
      title="Change volume over time"
      subtitle="l⁺ / l⁻ per bucket with λ churn overlay"
      right={
        <div className="flex gap-0.5 rounded-md bg-surface p-0.5">
          {['month', 'day'].map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onBucketChange(option)}
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                bucket === option ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      }
    >
      <PanelBody fetch={fetch} endpoint={`GET /api/metrics/{id}/series?bucket=${bucket}`}>
        {(data) =>
          data.buckets?.length ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.buckets} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="key" tick={AXIS} stroke="#334155" />
                  <YAxis tick={AXIS} stroke="#334155" width={48} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: '#e2e8f0' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar name="l⁺ added" dataKey="added" fill={COLORS.added} fillOpacity={0.85} />
                  <Bar name="l⁻ removed" dataKey="removed" fill={COLORS.removed} fillOpacity={0.85} />
                  <Line name="λ churn" dataKey="churn" stroke={COLORS.churn} strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No commits in the current selection" hint="Adjust the filters to see volume over time." />
          )
        }
      </PanelBody>
    </Card>
  )
}

function FilesPanel({ fetch, onDrillPath }) {
  const [sortKey, setSortKey] = useState('churn')
  const rows = fetch.data?.files ?? []
  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity))
    return copy
  }, [rows, sortKey])
  const maxChurn = useMemo(() => Math.max(0, ...sorted.map((row) => row.churn ?? 0)), [sorted])

  const columns = [
    { key: 'path', label: 'Path', align: 'text-left' },
    { key: 'added', label: 'l⁺', align: 'text-right' },
    { key: 'removed', label: 'l⁻', align: 'text-right' },
    { key: 'growth', label: 'δ', align: 'text-right' },
    { key: 'churn', label: 'λ', align: 'text-right' },
    { key: 'modifications', label: 'n', align: 'text-right' },
    { key: 'frequency', label: 'η', align: 'text-right' },
  ]

  return (
    <Card
      title="Top files"
      subtitle="Click a path to focus the dashboard on it"
      right={<Chip tone="slate">top {rows.length || 25} by λ churn</Chip>}
      bodyClassName="p-0"
    >
      <PanelBody fetch={fetch} endpoint="GET /api/metrics/{id}/files">
        {(data) =>
          data.files?.length ? (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-raised text-xs text-slate-500">
                  <tr className="border-b border-surface-border">
                    {columns.map((column) => (
                      <th
                        key={column.key}
                        onClick={() =>
                          column.key !== 'path' && setSortKey((current) => (current === column.key ? 'churn' : column.key))
                        }
                        className={`px-3 py-2 font-medium ${column.align} ${
                          column.key !== 'path' ? 'cursor-pointer select-none hover:text-slate-300' : ''
                        } ${sortKey === column.key ? 'text-indigo-300' : ''}`}
                        title={column.key !== 'path' ? `sort by ${column.label}` : undefined}
                      >
                        {column.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((row) => (
                    <tr
                      key={row.path}
                      className="cursor-pointer border-b border-surface-border/50 hover:bg-slate-700/30"
                      onClick={() => onDrillPath(row.path)}
                    >
                      <td className="max-w-[22rem] truncate px-3 py-1.5 font-mono text-xs text-slate-300" title={row.path}>
                        {row.path}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-emerald-300/90">{formatNumber(row.added)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-rose-300/90">{formatNumber(row.removed)}</td>
                      <td className={`px-3 py-1.5 text-right tabular-nums ${(row.growth ?? 0) >= 0 ? 'text-emerald-300/90' : 'text-rose-300/90'}`}>
                        {formatNumber(row.growth)}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-amber-300/90">
                        <div className="flex items-center justify-end gap-2">
                          <MiniBar value={row.churn ?? 0} max={maxChurn} className="w-14" />
                          {formatNumber(row.churn)}
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">{formatNumber(row.modifications)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">{formatRate(row.frequency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState icon={File} title="No files touched by the current selection" />
          )
        }
      </PanelBody>
    </Card>
  )
}

function AuthorsPanel({ fetch, onOpenMerge }) {
  const rows = fetch.data?.authors ?? []
  return (
    <Card
      title="Author impact & ownership (ω)"
      subtitle="ω = the author's share of λ on the current selection"
      right={
        <button
          type="button"
          onClick={onOpenMerge}
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-700/50"
        >
          <GitMerge className="h-3.5 w-3.5" /> Merge authors…
        </button>
      }
      bodyClassName="p-0"
    >
      <PanelBody fetch={fetch} endpoint="GET /api/metrics/{id}/authors">
        {(data) =>
          data.authors?.length ? (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-raised text-xs text-slate-500">
                  <tr className="border-b border-surface-border">
                    <th className="px-3 py-2 text-left font-medium">Author</th>
                    <th className="px-3 py-2 text-right font-medium">l⁺</th>
                    <th className="px-3 py-2 text-right font-medium">l⁻</th>
                    <th className="px-3 py-2 text-right font-medium">λ</th>
                    <th className="px-3 py-2 text-right font-medium">n</th>
                    <th className="px-3 py-2 text-left font-medium">ω ownership</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={`${row.email}-${index}`} className="border-b border-surface-border/50">
                      <td className="max-w-[18rem] px-3 py-1.5">
                        <div className="flex items-center gap-2">
                          <Users className="h-3.5 w-3.5 shrink-0 text-slate-600" />
                          <div className="min-w-0">
                            <p className="truncate text-slate-200" title={row.email}>
                              {row.name}
                            </p>
                            {row.email && <p className="truncate text-xs text-slate-500">{row.email}</p>}
                          </div>
                          {row.raw?.length > 1 && (
                            <Chip tone="violet" title={row.raw.map((r) => `${r.name} <${r.email}>`).join('\n')}>
                              {row.raw.length} emails
                            </Chip>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-emerald-300/90">{formatNumber(row.added)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-rose-300/90">{formatNumber(row.removed)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-amber-300/90">{formatNumber(row.churn)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">{formatNumber(row.modifications)}</td>
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-2">
                          <MiniBar value={(row.ownership ?? 0) * 100} max={100} tone="sky" className="w-20" />
                          <span className="text-xs tabular-nums text-slate-300">
                            {row.ownership == null ? '–' : `${(row.ownership * 100).toFixed(1)}%`}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState icon={Users} title="No authors in the current selection" />
          )
        }
      </PanelBody>
    </Card>
  )
}

/**
 * Metrics hub for the selected commit set. Each panel fetches its own
 * endpoint so widgets light up independently as the metrics engine lands.
 */
export default function MetricCharts({ repo, commitSet, author, path, refreshKey, onDrillPath, onOpenMerge }) {
  const [bucket, setBucket] = useState('month')
  const ready = repo?.status === 'ready'
  const params = hQuery(commitSet, { author, path })
  const key = JSON.stringify(params)

  const summary = useFetch(
    () => (ready ? getMetricsSummary(repo.id, params) : Promise.resolve(null)),
    [repo?.id, key, refreshKey],
  )
  const series = useFetch(
    () => (ready ? getMetricsSeries(repo.id, { ...params, bucket }) : Promise.resolve(null)),
    [repo?.id, key, bucket, refreshKey],
  )
  const files = useFetch(
    () => (ready ? getMetricsFiles(repo.id, { ...params, sort: 'churn', limit: 25 }) : Promise.resolve(null)),
    [repo?.id, key, refreshKey],
  )
  const authors = useFetch(
    () => (ready ? getMetricsAuthors(repo.id, params) : Promise.resolve(null)),
    [repo?.id, key, refreshKey],
  )

  if (!ready) return null

  // While the metrics engine is entirely absent one combined notice is tidier
  // than four identical pending panels.
  const allPending = [summary, series, files, authors].every(
    (fetch) => fetch.error && metricsState(fetch.error) === 'pending',
  )
  if (allPending) {
    return (
      <Card title="Metrics" subtitle="computed over the selected commit set H">
        <PendingNote
          endpoint="GET /api/metrics/{id}/summary|series|files|authors"
          onRetry={() => {
            summary.reload()
            series.reload()
            files.reload()
            authors.reload()
          }}
        />
        <p className="mt-3 text-xs text-slate-500">
          The dashboard is already wired to the integration contract in <code>src/api.js</code> —
          panels will populate automatically once the metrics routes respond.
        </p>
      </Card>
    )
  }

  const summaryState = summary.error ? metricsState(summary.error) : null

  return (
    <div className="space-y-4">
      <Card
        title="Summary"
        subtitle="All formulas evaluated over the selected commit set H"
        right={
          commitSet?.mode && commitSet.mode !== 'all' ? (
            <Chip tone="indigo">filtered: {commitSet.mode}</Chip>
          ) : null
        }
      >
        {summaryState === 'pending' ? (
          <PendingNote endpoint="GET /api/metrics/{id}/summary" onRetry={summary.reload} />
        ) : summaryState === 'failed' ? (
          <ErrorNote error={summary.error} onRetry={summary.reload} />
        ) : summary.loading && !summary.data ? (
          <Spinner />
        ) : summary.data ? (
          <SummaryTiles data={summary.data} />
        ) : null}
      </Card>

      <SeriesPanel fetch={series} bucket={bucket} onBucketChange={setBucket} />

      <div className="grid gap-4 2xl:grid-cols-2">
        <FilesPanel fetch={files} onDrillPath={onDrillPath} />
        <AuthorsPanel fetch={authors} onOpenMerge={onOpenMerge} />
      </div>
    </div>
  )
}
