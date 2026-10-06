import { useEffect, useMemo, useState } from 'react'
import { Check, GitMerge, Loader2, Search, Users, X } from 'lucide-react'
import { getCommits, getMetricsAuthors, hQuery, isMissingEndpoint, mergeAuthors } from '../api'
import { formatNumber } from '../format'
import { useFetch } from '../hooks'
import { EmptyState, ErrorNote, PendingNote, Spinner } from '../ui'

const identityKey = (identity) => `${identity.name} <${identity.email}>`

/**
 * Manual author merging: several raw identities (name/email pairs) are folded
 * into one canonical identity, layered on top of the repository .mailmap.
 *
 * The author index comes from the metrics engine when available; until then
 * the modal derives raw identities from the newest commits so the workflow is
 * usable end-to-end.
 */
export default function AuthorMergeModal({ open, repo, onClose, onMerged }) {
  const [target, setTarget] = useState(null)
  const [sources, setSources] = useState(new Set())
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [submittedPayload, setSubmittedPayload] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (open) {
      setTarget(null)
      setSources(new Set())
      setSearch('')
      setBusy(false)
      setError(null)
      setSubmittedPayload(null)
      setResult(null)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])

  const ready = repo?.status === 'ready'

  const authors = useFetch(async () => {
    if (!open || !ready) return null
    try {
      const data = await getMetricsAuthors(repo.id, hQuery({ mode: 'all' }))
      return { source: 'metrics', rows: data.authors ?? [] }
    } catch (err) {
      if (!isMissingEndpoint(err)) throw err
      // Interim fallback: aggregate raw identities from the newest commits.
      const data = await getCommits(repo.id, { offset: 0, limit: 500 })
      const byIdentity = new Map()
      for (const commit of data.commits ?? []) {
        const key = identityKey(commit.raw_author)
        const entry = byIdentity.get(key) ?? {
          name: commit.raw_author.name,
          email: commit.raw_author.email,
          commits: 0,
          churn: 0,
        }
        entry.commits += 1
        entry.churn += commit.churn ?? 0
        byIdentity.set(key, entry)
      }
      return {
        source: 'commits',
        scanned: data.commits?.length ?? 0,
        rows: [...byIdentity.values()].sort((a, b) => b.commits - a.commits),
      }
    }
  }, [open, repo?.id, ready])

  const rows = useMemo(() => {
    const all = authors.data?.rows ?? []
    const query = search.trim().toLowerCase()
    if (!query) return all
    return all.filter((row) => `${row.name} ${row.email}`.toLowerCase().includes(query))
  }, [authors.data, search])

  const toggleSource = (key) => {
    if (key === target) return
    setSources((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const byKey = useMemo(() => {
    const map = new Map()
    for (const row of authors.data?.rows ?? []) map.set(identityKey(row), row)
    return map
  }, [authors.data])

  const submit = async () => {
    if (!target || sources.size === 0 || busy) return
    const payload = {
      target: { name: byKey.get(target).name, email: byKey.get(target).email },
      sources: [...sources].map((key) => ({ name: byKey.get(key).name, email: byKey.get(key).email })),
    }
    setBusy(true)
    setError(null)
    setSubmittedPayload(payload)
    try {
      await mergeAuthors(repo.id, payload)
      setResult(
        `Merged ${payload.sources.length} identit${payload.sources.length === 1 ? 'y' : 'ies'} into ${payload.target.name}.`,
      )
      setSources(new Set())
      setTarget(null)
      authors.reload()
      onMerged?.()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const pending = error && isMissingEndpoint(error)

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="w-full max-w-2xl rounded-lg border border-surface-border bg-surface-raised shadow-2xl">
        <header className="flex items-center gap-3 border-b border-surface-border px-5 py-3">
          <GitMerge className="h-5 w-5 text-indigo-400" />
          <h2 className="text-base font-semibold text-slate-100">Merge authors</h2>
          <span className="text-xs text-slate-500">{repo?.name}</span>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-700/50 hover:text-slate-100 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-3 p-5">
          <p className="text-xs text-slate-500">
            Fold duplicate identities into one canonical author. Choose a <strong className="text-slate-300">target</strong>{' '}
            identity with the radio button, tick the identities to merge into it, then apply. The merge
            is layered on top of the repository <code>.mailmap</code>.
          </p>

          {authors.data?.source === 'commits' && (
            <PendingNote
              compact
              endpoint="GET /api/metrics/{id}/authors"
              onRetry={authors.reload}
            />
          )}

          <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-3 py-2">
            <Search className="h-3.5 w-3.5 text-slate-500" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="filter identities…"
              className="flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none"
            />
            <span className="text-xs text-slate-500">
              {sources.size} source{sources.size === 1 ? '' : 's'}
            </span>
          </div>

          {error &&
            (pending ? (
              <div className="space-y-2">
                <PendingNote endpoint="POST /api/repo/{id}/authors/merge" />
                <details className="rounded-md border border-surface-border bg-surface px-3 py-2 text-xs text-slate-400">
                  <summary className="cursor-pointer text-slate-300">
                    Request the dashboard sent (contract preview)
                  </summary>
                  <pre className="mt-2 overflow-x-auto text-[11px] text-slate-400">
                    {JSON.stringify(submittedPayload, null, 2)}
                  </pre>
                </details>
              </div>
            ) : (
              <ErrorNote error={error} />
            ))}

          {result && (
            <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
              <Check className="h-4 w-4" /> {result}
            </div>
          )}

          <div className="max-h-80 overflow-y-auto rounded-md border border-surface-border bg-surface">
            {authors.loading ? (
              <Spinner className="justify-center py-6" label="loading identities…" />
            ) : authors.error && !pending ? (
              <div className="p-3">
                <ErrorNote error={authors.error} onRetry={authors.reload} />
              </div>
            ) : rows.length === 0 ? (
              <EmptyState icon={Users} title="No identities found" />
            ) : (
              <ul className="divide-y divide-surface-border/60">
                {rows.map((row) => {
                  const key = identityKey(row)
                  const isTarget = key === target
                  const isSource = sources.has(key)
                  return (
                    <li
                      key={key}
                      className={`flex items-center gap-3 px-3 py-1.5 ${isTarget ? 'bg-emerald-500/10' : isSource ? 'bg-indigo-500/10' : ''}`}
                    >
                      <input
                        type="radio"
                        name="merge-target"
                        checked={isTarget}
                        onChange={() => {
                          setTarget(key)
                          setSources((current) => {
                            const next = new Set(current)
                            next.delete(key)
                            return next
                          })
                        }}
                        title="use as target identity"
                        className="accent-emerald-400"
                      />
                      <input
                        type="checkbox"
                        checked={isSource}
                        disabled={isTarget}
                        onChange={() => toggleSource(key)}
                        title="merge into the target"
                        className="accent-indigo-400"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-slate-200">{row.name}</p>
                        <p className="truncate text-xs text-slate-500">{row.email}</p>
                      </div>
                      <div className="shrink-0 text-right text-xs text-slate-400">
                        {row.commits != null && <p>{formatNumber(row.commits)} commits</p>}
                        {row.churn != null && <p className="text-slate-500">λ {formatNumber(row.churn)}</p>}
                        {row.raw?.length > 1 && (
                          <p className="text-violet-300">{row.raw.length} emails currently merged</p>
                        )}
                      </div>
                      {isTarget && <span className="shrink-0 text-[10px] font-semibold uppercase text-emerald-300">target</span>}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={submit}
              disabled={!target || sources.size === 0 || busy}
              className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitMerge className="h-4 w-4" />}
              {sources.size > 0 && target
                ? `Merge ${sources.size} into “${byKey.get(target)?.name}”`
                : 'Merge identities'}
            </button>
            {authors.data?.source === 'commits' && (
              <span className="text-xs text-slate-500">
                interim index: newest {formatNumber(authors.data.scanned)} commits
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
