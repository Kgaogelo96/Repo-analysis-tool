import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CloudDownload,
  FileCode2,
  GitBranch,
  HardDriveDownload,
  Link,
  Loader2,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { cloneRepo, deleteRepo, uploadRepo } from '../api'
import { formatBytes, shortHash } from '../format'
import { Chip, ErrorNote, StatusChip } from '../ui'

/**
 * Repository ingestion and management. Upload a `.zip` archive containing a
 * full `.git` structure or clone a remote URL; both feed the same async
 * pipeline (queued -> extracting|cloning -> verifying -> parsing -> ready).
 * The repository list polls through the parent while anything is processing.
 */
export default function IngestionModal({ open, onClose, repos, activeRepoId, onSelect, onRefresh }) {
  const [tab, setTab] = useState('upload')
  const [file, setFile] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [url, setUrl] = useState('')
  const [progress, setProgress] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const fileInput = useRef(null)

  // Reset transient state each time the dialog opens.
  useEffect(() => {
    if (open) {
      setError(null)
      setProgress(null)
      setBusy(false)
      setConfirmDelete(null)
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

  const pickFile = (candidate) => {
    if (!candidate) return
    if (!candidate.name.toLowerCase().endsWith('.zip')) {
      setError('expected a .zip archive containing the repository (with its .git folder)')
      return
    }
    setError(null)
    setFile(candidate)
  }

  const submitUpload = useCallback(async () => {
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setProgress(0)
    try {
      const record = await uploadRepo(file, (event) => {
        const total = event.total || file.size
        setProgress(total ? Math.round((event.loaded / total) * 100) : 0)
      })
      setFile(null)
      setProgress(null)
      onRefresh()
      onSelect(record.id)
    } catch (err) {
      setError(err)
      setProgress(null)
    } finally {
      setBusy(false)
    }
  }, [file, busy, onRefresh, onSelect])

  const submitClone = useCallback(async () => {
    if (!url.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const record = await cloneRepo(url.trim())
      setUrl('')
      onRefresh()
      onSelect(record.id)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }, [url, busy, onRefresh, onSelect])

  const handleDelete = async (repoId) => {
    if (confirmDelete !== repoId) {
      setConfirmDelete(repoId)
      return
    }
    setConfirmDelete(null)
    try {
      await deleteRepo(repoId)
      onRefresh(repoId)
    } catch (err) {
      setError(err)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="w-full max-w-2xl rounded-lg border border-surface-border bg-surface-raised shadow-2xl">
        <header className="flex items-center gap-3 border-b border-surface-border px-5 py-3">
          <HardDriveDownload className="h-5 w-5 text-indigo-400" />
          <h2 className="text-base font-semibold text-slate-100">Repositories</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-700/50 hover:text-slate-100 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-5">
          <div className="flex gap-1 rounded-md bg-surface p-1 text-sm">
            <button
              type="button"
              onClick={() => setTab('upload')}
              className={`flex flex-1 items-center justify-center gap-2 rounded px-3 py-1.5 font-medium ${
                tab === 'upload' ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Upload className="h-4 w-4" /> Upload .zip
            </button>
            <button
              type="button"
              onClick={() => setTab('clone')}
              className={`flex flex-1 items-center justify-center gap-2 rounded px-3 py-1.5 font-medium ${
                tab === 'clone' ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <CloudDownload className="h-4 w-4" /> Clone URL
            </button>
          </div>

          {error && <ErrorNote error={error} />}

          {tab === 'upload' ? (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                submitUpload()
              }}
            >
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragOver(true)
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragOver(false)
                  pickFile(event.dataTransfer.files?.[0])
                }}
                onClick={() => !busy && fileInput.current?.click()}
                className={`flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
                  dragOver
                    ? 'border-indigo-400 bg-indigo-500/10'
                    : 'border-surface-border hover:border-slate-500'
                }`}
              >
                <FileCode2 className="h-6 w-6 text-slate-500" />
                {file ? (
                  <p className="text-sm text-slate-200">
                    {file.name} <span className="text-slate-500">({formatBytes(file.size)})</span>
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-slate-300">
                      Drop a repository archive here, or click to choose
                    </p>
                    <p className="text-xs text-slate-500">
                      .zip containing the working tree and its <code>.git</code> directory
                    </p>
                  </>
                )}
                <input
                  ref={fileInput}
                  type="file"
                  accept=".zip,application/zip"
                  className="hidden"
                  onChange={(event) => pickFile(event.target.files?.[0])}
                />
              </div>

              {progress !== null && (
                <div className="mt-3">
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-700/60">
                    <div
                      className="h-full rounded-full bg-indigo-400 transition-[width]"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">uploading… {progress}%</p>
                </div>
              )}

              <button
                type="submit"
                disabled={!file || busy}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {busy ? 'Uploading…' : 'Ingest archive'}
              </button>
            </form>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                submitClone()
              }}
            >
              <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-400">
                <Link className="h-3.5 w-3.5" /> Remote repository URL
              </label>
              <input
                type="text"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://github.com/owner/repo.git"
                autoFocus
                className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-400 focus:outline-none"
              />
              <p className="mt-1.5 text-xs text-slate-500">
                Full history is cloned (all branches, no shallow truncation); SSH URLs work when
                credentials are configured for the git user.
              </p>
              <button
                type="submit"
                disabled={!url.trim() || busy}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CloudDownload className="h-4 w-4" />
                )}
                {busy ? 'Cloning…' : 'Clone & ingest'}
              </button>
            </form>
          )}

          <div className="border-t border-surface-border pt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Ingested repositories
            </h3>
            {repos.length === 0 ? (
              <p className="py-3 text-center text-sm text-slate-500">Nothing ingested yet.</p>
            ) : (
              <ul className="space-y-2">
                {repos.map((record) => (
                  <li
                    key={record.id}
                    className={`flex items-center gap-3 rounded-md border px-3 py-2 ${
                      record.id === activeRepoId
                        ? 'border-indigo-500/50 bg-indigo-500/10'
                        : 'border-surface-border bg-surface'
                    }`}
                  >
                    <GitBranch className="h-4 w-4 shrink-0 text-slate-500" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-slate-200">
                          {record.name}
                        </span>
                        <Chip tone="slate">{record.source}</Chip>
                        <StatusChip record={record} />
                      </div>
                      <p className="truncate text-xs text-slate-500" title={record.origin}>
                        {record.status === 'ready'
                          ? `${shortHash(record.head)} · ${record.commit_count ?? 0} non-merge commits`
                          : record.status === 'error'
                            ? record.error
                            : record.origin}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <button
                        type="button"
                        disabled={record.status !== 'ready'}
                        onClick={() => {
                          onSelect(record.id)
                          onClose()
                        }}
                        className="rounded border border-surface-border px-2 py-1 text-xs font-medium text-slate-300 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        Open
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(record.id)}
                        title="Delete repository"
                        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-medium ${
                          confirmDelete === record.id
                            ? 'border-rose-500/60 bg-rose-500/15 text-rose-300'
                            : 'border-surface-border text-slate-400 hover:bg-slate-700/50 hover:text-rose-300'
                        }`}
                      >
                        <Trash2 className="h-3 w-3" />
                        {confirmDelete === record.id ? 'Confirm' : ''}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
