import { useCallback, useEffect, useMemo, useState } from 'react'
import { GitBranch, GitMerge, HardDriveDownload, Loader2, Plus, RefreshCw } from 'lucide-react'
import { getHealth, listRepos } from './api'
import AuthorMergeModal from './components/AuthorMergeModal'
import CommitsPanel from './components/CommitsPanel'
import DirectoryTree from './components/DirectoryTree'
import FilterBar from './components/FilterBar'
import IngestionModal from './components/IngestionModal'
import MetricCharts from './components/MetricCharts'
import { formatNumber, shortHash } from './format'
import { Chip, EmptyState, ErrorNote } from './ui'

const MODE_RESET = { mode: 'all' }

/**
 * Repo Analysis Tool dashboard.
 *
 * State flow: the repository list polls while any ingestion is in flight; the
 * selected repository and the commit-set filter H are owned here and passed to
 * every widget. Metric widgets fetch their own endpoints through the shared
 * contract in `src/api.js` and light up as the metrics engine lands.
 */
export default function App() {
  const [health, setHealth] = useState('checking')
  const [repos, setRepos] = useState([])
  const [reposError, setReposError] = useState(null)
  const [repoId, setRepoId] = useState(() => localStorage.getItem('rat.repoId'))
  const [commitSet, setCommitSet] = useState(MODE_RESET)
  const [author, setAuthor] = useState('')
  const [path, setPath] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [showIngestion, setShowIngestion] = useState(false)
  const [showMerge, setShowMerge] = useState(false)

  const loadRepos = useCallback(async () => {
    try {
      setRepos(await listRepos())
      setReposError(null)
      setHealth('online')
    } catch (error) {
      setReposError(error)
      setHealth('offline')
    }
  }, [])

  useEffect(() => {
    getHealth()
      .then(() => setHealth('online'))
      .catch(() => setHealth('offline'))
    loadRepos()
  }, [loadRepos])

  // Poll the registry while any repository is being ingested or parsed.
  const busy = repos.some((record) => record.status === 'queued' || record.status === 'processing')
  useEffect(() => {
    if (!busy) return undefined
    const timer = setInterval(loadRepos, 1500)
    return () => clearInterval(timer)
  }, [busy, loadRepos])

  const repo = useMemo(() => repos.find((record) => record.id === repoId) ?? null, [repos, repoId])

  // Keep the selection pointing at an existing repository.
  useEffect(() => {
    if (repos.length === 0) return
    if (!repos.some((record) => record.id === repoId)) {
      const firstReady = repos.find((record) => record.status === 'ready')
      setRepoId(firstReady?.id ?? repos[0].id)
    }
  }, [repos, repoId])

  // Selecting a different repository resets all repo-scoped filters.
  useEffect(() => {
    if (repoId) localStorage.setItem('rat.repoId', repoId)
    setCommitSet(MODE_RESET)
    setAuthor('')
    setPath('')
  }, [repoId])

  const bumpRefresh = () => setRefreshKey((key) => key + 1)
  const ready = repo?.status === 'ready'

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-surface-border bg-surface-raised px-5 py-3">
        <GitBranch className="h-5 w-5 text-indigo-400" />
        <h1 className="text-lg font-semibold text-slate-100">Repo Analysis Tool</h1>
        {repo && (
          <span className="hidden items-center gap-2 text-sm text-slate-400 md:flex">
            <span className="text-slate-600">/</span>
            <span className="font-medium text-slate-300">{repo.name}</span>
            {ready && (
              <>
                <Chip tone="slate" title={`HEAD ${repo.head ?? ''}`}>
                  {shortHash(repo.head)}
                </Chip>
                <Chip tone="slate">{formatNumber(repo.commit_count ?? 0)} commits</Chip>
              </>
            )}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <span className="mr-1 flex items-center gap-2 text-xs text-slate-500">
            <span
              className={`h-2 w-2 rounded-full ${
                health === 'online' ? 'bg-emerald-400' : health === 'offline' ? 'bg-rose-500' : 'bg-amber-400'
              }`}
            />
            backend {health}
          </span>
          <button
            type="button"
            onClick={() => {
              bumpRefresh()
              loadRepos()
            }}
            title="Refresh data"
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700/50"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowMerge(true)}
            disabled={!ready}
            title="Merge duplicate author identities"
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <GitMerge className="h-3.5 w-3.5" /> Merge authors
          </button>
          <button
            type="button"
            onClick={() => setShowIngestion(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
          >
            <HardDriveDownload className="h-3.5 w-3.5" /> Repositories
          </button>
        </div>
      </header>

      <main className="flex-1 space-y-4 p-4">
        {reposError && !repos.length && (
          <ErrorNote
            error={reposError}
            onRetry={loadRepos}
            action={
              <span className="text-xs text-rose-300/80">
                start the backend with <code>uvicorn app.main:app</code> (see README)
              </span>
            }
          />
        )}

        {!reposError && repos.length === 0 && (
          <div className="mx-auto mt-[10vh] max-w-md rounded-lg border border-surface-border bg-surface-raised p-8">
            <EmptyState
              icon={HardDriveDownload}
              title="No repositories ingested yet"
              hint="Upload a .zip archive containing a full .git structure, or clone a remote repository URL."
            >
              <button
                type="button"
                onClick={() => setShowIngestion(true)}
                className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
              >
                <Plus className="h-4 w-4" /> Ingest a repository
              </button>
            </EmptyState>
          </div>
        )}

        {repos.length > 0 && repo && !ready && (
          <div
            className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm ${
              repo.status === 'error'
                ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                : 'border-sky-500/30 bg-sky-500/10 text-sky-200'
            }`}
          >
            {repo.status === 'error' ? (
              <>
                <span className="font-medium">Ingestion failed:</span> {repo.error}
              </>
            ) : (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>
                  Ingesting <strong>{repo.name}</strong> — stage: {repo.stage || repo.status}
                </span>
                <span className="text-xs opacity-70">the view updates automatically</span>
              </>
            )}
          </div>
        )}

        {ready && (
          <>
            <FilterBar
              repos={repos}
              repo={repo}
              commitSet={commitSet}
              author={author}
              path={path}
              onRepoChange={setRepoId}
              onCommitSetChange={setCommitSet}
              onAuthorChange={setAuthor}
              onPathChange={setPath}
              onReset={() => {
                setCommitSet(MODE_RESET)
                setAuthor('')
                setPath('')
              }}
            />

            <div className="grid items-start gap-4 xl:grid-cols-3">
              <div className="xl:col-span-2">
                <MetricCharts
                  repo={repo}
                  commitSet={commitSet}
                  author={author}
                  path={path}
                  refreshKey={refreshKey}
                  onDrillPath={setPath}
                  onOpenMerge={() => setShowMerge(true)}
                />
              </div>
              <DirectoryTree
                repo={repo}
                commitSet={commitSet}
                author={author}
                path={path}
                refreshKey={refreshKey}
                onDrillPath={setPath}
              />
            </div>

            <CommitsPanel repo={repo} commitSet={commitSet} author={author} path={path} refreshKey={refreshKey} />
          </>
        )}
      </main>

      <IngestionModal
        open={showIngestion}
        onClose={() => setShowIngestion(false)}
        repos={repos}
        activeRepoId={repoId}
        onSelect={setRepoId}
        onRefresh={loadRepos}
      />
      <AuthorMergeModal
        open={showMerge}
        repo={repo}
        onClose={() => setShowMerge(false)}
        onMerged={bumpRefresh}
      />
    </div>
  )
}
