import {
  AlertTriangle,
  FolderTree,
  Info,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { apiError, isMissingEndpoint } from './api'

/** Panel with an optional header row (title, subtitle, right-side actions). */
export function Card({ title, subtitle, right, children, className = '', bodyClassName = '' }) {
  return (
    <section className={`rounded-lg border border-surface-border bg-surface-raised ${className}`}>
      {(title || right) && (
        <header className="flex items-center gap-2 border-b border-surface-border px-4 py-2.5">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="truncate text-xs text-slate-500">{subtitle}</p>}
          </div>
          {right && <div className="ml-auto flex shrink-0 items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={bodyClassName || 'p-4'}>{children}</div>
    </section>
  )
}

const CHIP_TONES = {
  slate: 'bg-slate-500/15 text-slate-300 ring-slate-400/20',
  sky: 'bg-sky-500/15 text-sky-300 ring-sky-400/30',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-400/30',
  emerald: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/30',
  rose: 'bg-rose-500/15 text-rose-300 ring-rose-400/30',
  indigo: 'bg-indigo-500/15 text-indigo-300 ring-indigo-400/30',
  violet: 'bg-violet-500/15 text-violet-300 ring-violet-400/30',
}

export function Chip({ tone = 'slate', children, title, className = '' }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${CHIP_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

/** Status chip for an ingested repository record. */
export function StatusChip({ record }) {
  if (record.status === 'ready') {
    return (
      <Chip tone="emerald" title={`HEAD ${record.head ?? ''}`}>
        ready
      </Chip>
    )
  }
  if (record.status === 'error') {
    return (
      <Chip tone="rose" title={record.error ?? undefined}>
        error
      </Chip>
    )
  }
  return (
    <Chip tone={record.status === 'queued' ? 'amber' : 'sky'}>
      <Loader2 className="h-3 w-3 animate-spin" />
      {record.stage || record.status}
    </Chip>
  )
}

export function Spinner({ label = 'loading…', className = '' }) {
  return (
    <div className={`flex items-center gap-2 py-6 text-sm text-slate-400 ${className}`}>
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  )
}

export function EmptyState({ icon: Icon = FolderTree, title, hint, children }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Icon className="h-6 w-6 text-slate-600" />
      <p className="text-sm font-medium text-slate-300">{title}</p>
      {hint && <p className="max-w-md text-xs text-slate-500">{hint}</p>}
      {children}
    </div>
  )
}

/** Error panel for unexpected failures; offers a retry when given. */
export function ErrorNote({ error, onRetry, action }) {
  return (
    <div className="flex items-start gap-3 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
      <div className="min-w-0 flex-1">
        <p className="break-words text-rose-200">{apiError(error)}</p>
        <div className="mt-1.5 flex gap-2">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 text-xs font-medium text-rose-300 hover:text-rose-100"
            >
              <RefreshCw className="h-3 w-3" /> Retry
            </button>
          )}
          {action}
        </div>
      </div>
    </div>
  )
}

/**
 * Placeholder shown while an endpoint owned by the metrics engine has not
 * landed yet. The dashboard stays fully navigable; widgets light up as soon
 * as the routes start responding.
 */
export function PendingNote({ endpoint, onRetry, compact = false }) {
  return (
    <div
      className={`flex items-start gap-3 rounded-md border border-violet-500/25 bg-violet-500/10 px-3 ${
        compact ? 'py-2' : 'py-2.5'
      } text-sm`}
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
      <div className="min-w-0 flex-1 text-violet-200">
        <span>Waiting for the metrics engine. </span>
        {endpoint && <code className="rounded bg-black/30 px-1 py-0.5 text-[11px]">{endpoint}</code>}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-medium text-violet-300 hover:text-violet-100"
          >
            <RefreshCw className="h-3 w-3" /> Retry
          </button>
        )}
      </div>
    </div>
  )
}

/** When a fetch 404s because the metrics engine has not landed it yet. */
export function metricsState(error) {
  return isMissingEndpoint(error) ? 'pending' : 'failed'
}

/** Horizontal magnitude bar used in tables and the directory tree. */
export function MiniBar({ value, max, tone = 'amber', className = '' }) {
  const width = max > 0 && Number.isFinite(value) ? Math.max(2, Math.round((value / max) * 100)) : 0
  const tones = { amber: 'bg-amber-400/80', emerald: 'bg-emerald-400/80', sky: 'bg-sky-400/80' }
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-700/60 ${className}`}>
      <div className={`h-full rounded-full ${tones[tone]}`} style={{ width: `${width}%` }} />
    </div>
  )
}
