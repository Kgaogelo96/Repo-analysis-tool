import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, GitCommit } from 'lucide-react'
import { getCommits, hQuery } from '../api'
import { formatDateTime, formatNumber, shortHash } from '../format'
import { useFetch } from '../hooks'
import { Card, Chip, EmptyState, ErrorNote, Spinner } from '../ui'

const PAGE_SIZE = 200
const MANUAL_SCAN = 500

/**
 * Paginated commit browser for the current selection.
 *
 * Window/author/path filters and interval slices are evaluated server-side
 * (`since`/`until` and `offset`/`limit` map directly). Manual hash sets are
 * filtered client-side over the newest page window until the metrics engine
 * applies them server-side like every other widget.
 */
export default function CommitsPanel({ repo, commitSet, author, path, refreshKey }) {
  const [page, setPage] = useState(0)
  const ready = repo?.status === 'ready'
  const mode = commitSet?.mode ?? 'all'
  const key = JSON.stringify(hQuery(commitSet, { author, path }))

  useEffect(() => {
    setPage(0)
  }, [repo?.id, key, refreshKey])

  const fetchPage = async () => {
    if (!ready) return null

    if (mode === 'manual') {
      const hashes = commitSet.hashes instanceof Set ? commitSet.hashes : new Set()
      const data = await getCommits(repo.id, {
        offset: 0,
        limit: MANUAL_SCAN,
        ...(author ? { author } : {}),
        ...(path ? { path } : {}),
      })
      const matched = (data.commits ?? []).filter((commit) => hashes.has(commit.hash))
      return {
        rows: matched.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE),
        matchedTotal: matched.length,
        scanned: data.commits?.length ?? 0,
        availableTotal: data.total ?? 0,
        manual: true,
      }
    }

    const params = { offset: page * PAGE_SIZE, limit: PAGE_SIZE }
    if (mode === 'window') {
      if (commitSet.since) params.since = commitSet.since
      if (commitSet.until) params.until = commitSet.until
    }
    if (mode === 'interval') {
      const from = commitSet.fromIndex ?? 0
      const to = commitSet.toIndex ?? null
      params.offset = from + page * PAGE_SIZE
      if (to !== null) {
        if (params.offset >= to) return { rows: [], total: to - from, offset: params.offset, intervalTo: to }
        params.limit = Math.max(1, Math.min(to - params.offset, PAGE_SIZE))
      }
      const data = await getCommits(repo.id, {
        ...params,
        ...(author ? { author } : {}),
        ...(path ? { path } : {}),
      })
      return { ...data, rows: data.commits, intervalTo: to }
    }

    if (author) params.author = author
    if (path) params.path = path
    const data = await getCommits(repo.id, params)
    return { ...data, rows: data.commits }
  }

  const pageFetch = useFetch(fetchPage, [repo?.id, ready, key, page, refreshKey])

  if (!ready) return null

  const data = pageFetch.data
  const rows = data?.rows ?? []
  const count = mode === 'manual' ? (data?.matchedTotal ?? 0) : (data?.total ?? 0)
  const rangeStart = mode === 'manual' ? page * PAGE_SIZE : mode === 'interval' ? (commitSet.fromIndex ?? 0) + page * PAGE_SIZE : page * PAGE_SIZE
  const canPrev = page > 0
  const canNext = mode === 'manual'
    ? rangeStart + PAGE_SIZE < (data?.matchedTotal ?? 0)
    : mode === 'interval' && data?.intervalTo != null
      ? rangeStart + PAGE_SIZE < data.intervalTo
      : rows.length === PAGE_SIZE

  return (
    <Card
      title="Commits in H"
      subtitle={
        mode === 'window'
          ? 'author-timestamp window (since inclusive, until exclusive)'
          : mode === 'interval'
            ? 'interval slice H_{i,j} — i inclusive, j exclusive (newest first)'
            : mode === 'manual'
              ? 'explicit hash set'
              : 'all non-merge commits reachable from HEAD'
      }
      right={
        <div className="flex items-center gap-2">
          {pageFetch.loading && <span className="text-xs text-slate-500">loading…</span>}
          <Chip tone="slate">page {page + 1}</Chip>
        </div>
      }
      bodyClassName="p-0"
    >
      {pageFetch.error ? (
        <div className="p-4">
          <ErrorNote error={pageFetch.error} onRetry={pageFetch.reload} />
        </div>
      ) : pageFetch.loading && !data ? (
        <Spinner className="justify-center" label="loading commits…" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={GitCommit}
          title="No commits match the current selection"
          hint={mode === 'manual' && (data?.matchedTotal ?? 0) === 0 && (data?.scanned ?? 0) > 0
            ? `Selected hashes were not found within the newest ${formatNumber(data.scanned)} commits loaded for preview.`
            : undefined}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface text-xs text-slate-500">
              <tr className="border-b border-surface-border">
                <th className="px-3 py-2 text-left font-medium">commit</th>
                <th className="px-3 py-2 text-left font-medium">author</th>
                <th className="px-3 py-2 text-left font-medium">date</th>
                <th className="px-3 py-2 text-right font-medium">files</th>
                <th className="px-3 py-2 text-right font-medium">l⁺</th>
                <th className="px-3 py-2 text-right font-medium">l⁻</th>
                <th className="px-3 py-2 text-right font-medium">λ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((commit) => (
                <tr key={commit.hash} className="border-b border-surface-border/50 hover:bg-slate-700/20">
                  <td className="px-3 py-1.5">
                    <code className="rounded bg-surface px-1.5 py-0.5 text-xs text-indigo-300" title={commit.hash}>
                      {shortHash(commit.hash)}
                    </code>
                  </td>
                  <td className="max-w-[16rem] px-3 py-1.5">
                    <span className="truncate text-slate-200" title={`${commit.author.name} <${commit.author.email}>`}>
                      {commit.author.name}
                    </span>
                    {commit.raw_author.name !== commit.author.name && (
                      <span className="ml-1 text-xs text-slate-500" title="resolved by .mailmap">
                        ({commit.raw_author.name})
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-xs text-slate-400">
                    {formatDateTime(commit.author_ts)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-slate-400">
                    {formatNumber(commit.files_changed)}
                    {commit.binary_files > 0 && (
                      <span className="ml-1 text-[10px] text-violet-300" title={`${commit.binary_files} binary file(s) excluded from line metrics`}>
                        bin
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-emerald-300/90">{formatNumber(commit.added)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-rose-300/90">{formatNumber(commit.removed)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-amber-300/90">{formatNumber(commit.churn)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-t border-surface-border px-3 py-2 text-xs text-slate-500">
          <button
            type="button"
            disabled={!canPrev}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
            className="inline-flex items-center gap-1 rounded border border-surface-border px-2 py-1 font-medium text-slate-300 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> prev
          </button>
          <button
            type="button"
            disabled={!canNext}
            onClick={() => setPage((current) => current + 1)}
            className="inline-flex items-center gap-1 rounded border border-surface-border px-2 py-1 font-medium text-slate-300 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            next <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <span>
            {mode === 'manual'
              ? `${formatNumber(count)} selected commits found within the newest ${formatNumber(data?.scanned ?? 0)} loaded (of ${formatNumber(data?.availableTotal ?? 0)})`
              : mode === 'interval'
                ? `showing #${formatNumber(rangeStart)}–#${formatNumber(rangeStart + rows.length - 1)}${
                    data?.intervalTo != null ? ` of #${formatNumber(commitSet.fromIndex ?? 0)}–#${formatNumber(data.intervalTo - 1)}` : ''
                  }`
                : `showing ${formatNumber(rangeStart + 1)}–${formatNumber(rangeStart + rows.length)} of ${formatNumber(count)}`}
          </span>
          {mode === 'manual' && (
            <span className="text-slate-600">
              hash set filtered client-side until the metrics engine evaluates it server-side
            </span>
          )}
        </div>
      )}
    </Card>
  )
}
