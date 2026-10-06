import { useEffect, useState } from 'react'
import { GitBranch } from 'lucide-react'
import api from './api'

/**
 * Application shell. Dashboard widgets (ingestion, filters, tree, charts)
 * are added incrementally; for now it renders the header and verifies
 * connectivity with the backend.
 */
export default function App() {
  const [backendStatus, setBackendStatus] = useState('checking')

  useEffect(() => {
    api
      .get('/health')
      .then(() => setBackendStatus('online'))
      .catch(() => setBackendStatus('offline'))
  }, [])

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-surface-border bg-surface-raised px-5 py-3">
        <GitBranch className="h-5 w-5 text-indigo-400" />
        <h1 className="text-lg font-semibold text-slate-100">Repo Analysis Tool</h1>
        <span className="ml-auto flex items-center gap-2 text-xs text-slate-400">
          <span
            className={`h-2 w-2 rounded-full ${
              backendStatus === 'online'
                ? 'bg-emerald-400'
                : backendStatus === 'offline'
                  ? 'bg-rose-500'
                  : 'bg-amber-400'
            }`}
          />
          backend {backendStatus}
        </span>
      </header>

      <main className="flex flex-1 items-center justify-center p-6">
        <p className="text-sm text-slate-500">
          Dashboard widgets will appear here as they are built.
        </p>
      </main>
    </div>
  )
}
