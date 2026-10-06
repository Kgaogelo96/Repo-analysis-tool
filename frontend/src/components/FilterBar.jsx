import { useEffect, useMemo, useState } from 'react'
import {
  Calendar,
  Check,
  ChevronDown,
  Clock,
  GitBranch,
  ListChecks,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { getCommits } from '../api'
import { formatDate, formatNumber, shortHash, toDatetimeLocal, toEpoch } from '../format'
import { useFetch } from '../hooks'
import { Chip, EmptyState, Spinner } from '../ui'

const MODES = [
  { id: 'all', label: 'All', title: 'H = every non-merge commit on the branch (H_t unbounded)' },
  { id: 'window', label: 'Time window', title: 'H_t — commits with committer timestamp in [since, until)' },
  { id: 'interval', label: 'Interval', title: 'H_{i,j} — commits at positions i..j-1 of the newest-first log' },
  { id: 'manual', label: 'Manual', title: 'An explicit set of commit hashes' },
]

const inputClass =
  'rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-400 focus:outline-none'

/** Compact human description of the currently selected commit set. */
function describeSet(commitSet, repo) {
  const mode = commitSet?.mode ?? 'all'
  if (mode === 'window') {
    const { since, until } = commitSet
    if (since && until) return `H: ${formatDate(since)} → ${formatDate(until)}`
    if (since) return `H: since ${formatDate(since)}`
    if (until) return `H: until ${formatDate(until)}`
    return 'H: open time window'
  }
  if (mode === 'interval') {
    const from = commitSet.fromIndex ?? 0
    const to = commitSet.toIndex
    return to !== undefined && to !== null
      ? `H: commits #${from}–#${to - 1} (newest first)`
      : `H: commits #${from}–latest`
  }
  if (mode === 'manual') return `H: ${commitSet.hashes?.size ?? 0} selected commits`
  return repo?.commit_count ? `H: all ${formatNumber(repo.commit_count)} commits` : 'H: all commits'
}

export default function FilterBar({
  repos,
  repo,
  commitSet,
  author,
  path,
  onRepoChange,
  onCommitSetChange,
  onAuthorChange,
  onPathChange,
  onReset,
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerSearch, setPickerSearch] = useState('')
  const [sinceRaw, setSinceRaw] = useState(toDatetimeLocal(commitSet?.since))
  const [untilRaw, setUntilRaw] = useState(toDatetimeLocal(commitSet?.until))

  useEffect(() => setSinceRaw(toDatetimeLocal(commitSet?.since)), [commitSet?.since])
  useEffect(() => setUntilRaw(toDatetimeLocal(commitSet?.until)), [commitSet?.until])

  const mode = commitSet?.mode ?? 'all'

  const switchMode = (nextMode) => {
    if (nextMode === mode) return
    const next = { ...commitSet, mode: nextMode }
    if (nextMode === 'interval' && next.fromIndex === undefined) next.fromIndex = 0
    if (nextMode === 'manual' && !(next.hashes instanceof Set)) next.hashes = new Set()
    onCommitSetChange(next)
    setPickerOpen(nextMode === 'manual')
  }

  // Manual mode needs a browsable list of commits to pick from.
  const picker = useFetch(
    () => (pickerOpen && repo ? getCommits(repo.id, { offset: 0, limit: 500 }) : Promise.resolve(null)),
    [pickerOpen, repo?.id],
  )

  const pickerRows = useMemo(() => {
    const commits = picker.data?.commits ?? []
    const query = pickerSearch.trim().toLowerCase()
    if (!query) return commits
    return commits.filter((commit) =>
      `${commit.hash} ${commit.author.name} ${commit.author.email} ${commit.raw_author.name} ${commit.raw_author.email} ${formatDate(commit.author_ts)}`
        .toLowerCase()
        .includes(query),
    )
  }, [picker.data, pickerSearch])

  const hashes = commitSet?.hashes instanceof Set ? commitSet.hashes : new Set()

  const toggleHash = (hash) => {
    const next = new Set(hashes)
    if (next.has(hash)) next.delete(hash)
    else next.add(hash)
    onCommitSetChange({ ...commitSet, mode: 'manual', hashes: next })
  }

  const setIntervalBound = (field, raw) => {
    const next = { ...commitSet, mode: 'interval', [field]: raw === '' ? undefined : Math.max(0, Number(raw)) }
    if (field === 'fromIndex' && next.fromIndex === undefined) next.fromIndex = 0
    onCommitSetChange(next)
  }

  const intervalHint =
    repo?.commit_count != null
      ? `0 = newest · ${formatNumber(repo.commit_count)} non-merge commits total`
      : '0 = newest commit'

  const filtered =
    (commitSet && mode !== 'all') || Boolean(author) || Boolean(path)

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        {/* repository */}
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-slate-500" />
          <select
            value={repo?.id ?? ''}
            onChange={(event) => onRepoChange(event.target.value || null)}
            className={`${inputClass} max-w-[16rem]`}
            title="Repository filter"
          >
            {!repo && <option value="">select a repository…</option>}
            {repos.map((record) => (
              <option key={record.id} value={record.id} disabled={record.status !== 'ready'}>
                {record.name}
                {record.status !== 'ready' ? ` (${record.status})` : ''}
              </option>
            ))}
          </select>
        </div>

        {/* commit set H mode */}
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-slate-500" />
          <div className="flex gap-0.5 rounded-md bg-surface p-0.5">
            {MODES.map((option) => (
              <button
                key={option.id}
                type="button"
                title={option.title}
                onClick={() => switchMode(option.id)}
                className={`rounded px-2.5 py-1 text-xs font-medium ${
                  mode === option.id
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        {/* mode-specific inputs */}
        {mode === 'window' && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Clock className="h-4 w-4 text-slate-500" />
            <input
              type="datetime-local"
              value={sinceRaw}
              onChange={(event) => {
                setSinceRaw(event.target.value)
                onCommitSetChange({ ...commitSet, mode: 'window', since: toEpoch(event.target.value) })
              }}
              className={`${inputClass} [color-scheme:dark]`}
              title="since (inclusive, committer timestamp)"
            />
            <span>→</span>
            <input
              type="datetime-local"
              value={untilRaw}
              onChange={(event) => {
                setUntilRaw(event.target.value)
                onCommitSetChange({ ...commitSet, mode: 'window', until: toEpoch(event.target.value) })
              }}
              className={`${inputClass} [color-scheme:dark]`}
              title="until (exclusive, author timestamp)"
            />
          </div>
        )}

        {mode === 'interval' && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>#</span>
            <input
              type="number"
              min={0}
              value={commitSet.fromIndex ?? 0}
              onChange={(event) => setIntervalBound('fromIndex', event.target.value)}
              className={`${inputClass} w-20`}
              title="i (inclusive)"
            />
            <span>–</span>
            <input
              type="number"
              min={0}
              placeholder={repo?.commit_count != null ? String(repo.commit_count) : 'end'}
              value={commitSet.toIndex ?? ''}
              onChange={(event) => setIntervalBound('toIndex', event.target.value)}
              className={`${inputClass} w-24`}
              title="j (exclusive)"
            />
            <button
              type="button"
              onClick={() => onCommitSetChange({ ...commitSet, mode: 'interval', fromIndex: 0, toIndex: 100 })}
              className="rounded border border-surface-border px-2 py-1 text-[11px] hover:bg-slate-700/50"
            >
              Newest 100
            </button>
            <button
              type="button"
              onClick={() =>
                onCommitSetChange({ ...commitSet, mode: 'interval', fromIndex: 0, toIndex: undefined })
              }
              className="rounded border border-surface-border px-2 py-1 text-[11px] hover:bg-slate-700/50"
            >
              Full range
            </button>
            <span className="text-slate-600">{intervalHint}</span>
          </div>
        )}

        {mode === 'manual' && (
          <button
            type="button"
            onClick={() => setPickerOpen((open) => !open)}
            className="inline-flex items-center gap-2 rounded-md border border-surface-border px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700/50"
          >
            <ListChecks className="h-4 w-4" />
            {hashes.size ? `${hashes.size} commits selected` : 'Select commits…'}
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${pickerOpen ? 'rotate-180' : ''}`} />
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Chip tone={filtered ? 'indigo' : 'slate'}>{describeSet(commitSet, repo)}</Chip>
        </div>
      </div>

      {/* manual commit picker */}
      {mode === 'manual' && pickerOpen && (
        <div className="mt-3 rounded-md border border-surface-border bg-surface">
          <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
            <Search className="h-3.5 w-3.5 text-slate-500" />
            <input
              value={pickerSearch}
              onChange={(event) => setPickerSearch(event.target.value)}
              placeholder="filter by hash, author, date…"
              className="flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none"
            />
            <span className="text-xs text-slate-500">{hashes.size} selected</span>
            <button
              type="button"
              onClick={() => onCommitSetChange({ ...commitSet, mode: 'manual', hashes: new Set() })}
              disabled={!hashes.size}
              className="rounded border border-surface-border px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-700/50 disabled:opacity-40"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setPickerOpen(false)}
              className="rounded border border-surface-border px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-700/50"
            >
              Done
            </button>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {picker.loading ? (
              <Spinner className="justify-center py-6" label="loading commits…" />
            ) : picker.error ? (
              <p className="px-3 py-4 text-sm text-rose-300">
                Could not load commits: {picker.error?.response?.data?.detail ?? picker.error.message}
              </p>
            ) : pickerRows.length === 0 ? (
              <EmptyState icon={Calendar} title="No commits match" hint="Adjust the search text." />
            ) : (
              <ul className="divide-y divide-surface-border/60">
                {pickerRows.map((commit) => {
                  const selected = hashes.has(commit.hash)
                  return (
                    <li key={commit.hash}>
                      <button
                        type="button"
                        onClick={() => toggleHash(commit.hash)}
                        className={`flex w-full items-center gap-3 px-3 py-1.5 text-left text-sm hover:bg-slate-700/30 ${
                          selected ? 'bg-indigo-500/10' : ''
                        }`}
                      >
                        <span
                          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                            selected
                              ? 'border-indigo-400 bg-indigo-500 text-white'
                              : 'border-slate-600'
                          }`}
                        >
                          {selected && <Check className="h-3 w-3" />}
                        </span>
                        <code className="w-20 shrink-0 text-xs text-indigo-300">
                          {shortHash(commit.hash)}
                        </code>
                        <span className="truncate text-slate-300">
                          {commit.author.name}
                          {commit.raw_author.name !== commit.author.name && (
                            <span className="text-slate-500"> ({commit.raw_author.name})</span>
                          )}
                        </span>
                        <span className="ml-auto shrink-0 text-xs text-slate-500">
                          {formatDate(commit.author_ts)} · λ {formatNumber(commit.churn)}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            {picker.data?.total > (picker.data?.commits?.length ?? 0) && (
              <p className="border-t border-surface-border px-3 py-2 text-xs text-slate-500">
                Showing the newest {formatNumber(picker.data.commits.length)} of{' '}
                {formatNumber(picker.data.total)} commits — narrow with search to reach older ones.
              </p>
            )}
          </div>
        </div>
      )}

      {/* author + path filters */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <Search className="h-3.5 w-3.5 text-slate-500" />
          <input
            value={author}
            onChange={(event) => onAuthorChange(event.target.value)}
            placeholder="author name or email…"
            className={`${inputClass} w-56`}
            title="Matches canonical and raw author identities (case-insensitive substring)"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">path</span>
          <input
            value={path}
            onChange={(event) => onPathChange(event.target.value)}
            placeholder="file or directory prefix…"
            className={`${inputClass} w-64 font-mono text-xs`}
            title="Exact file path or directory prefix"
          />
          {path && (
            <button
              type="button"
              onClick={() => onPathChange('')}
              className="rounded p-1 text-slate-500 hover:bg-slate-700/50 hover:text-slate-200"
              title="Clear path filter"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {filtered && (
          <button
            type="button"
            onClick={() => {
              onReset()
              setPickerOpen(false)
            }}
            className="ml-auto inline-flex items-center gap-1 rounded border border-surface-border px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700/50"
          >
            <X className="h-3.5 w-3.5" /> Clear filters
          </button>
        )}
      </div>
    </div>
  )
}
