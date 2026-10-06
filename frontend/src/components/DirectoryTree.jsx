import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ChevronDown, ChevronRight, File, Folder, FolderTree, Loader2, RefreshCw } from 'lucide-react'
import { getMetricsTree, hQuery, metricsState } from '../api'
import { formatNumber } from '../format'
import { useFetch } from '../hooks'
import { Card, EmptyState, ErrorNote, MiniBar, PendingNote, Spinner } from '../ui'

const ROW_GRID = 'grid grid-cols-[minmax(0,1fr)_4.5rem_6.5rem_2.5rem] items-center gap-2'

function MetricsCells({ metrics, reference }) {
  if (!metrics) {
    return (
      <>
        <span className="text-right text-xs text-slate-600">–</span>
        <span />
        <span className="text-right text-xs text-slate-600">–</span>
      </>
    )
  }
  const growth = metrics.growth ?? 0
  return (
    <>
      <span
        className={`text-right text-xs tabular-nums ${growth >= 0 ? 'text-emerald-300/90' : 'text-rose-300/90'}`}
        title="δ growth = l⁺ − l⁻"
      >
        {growth >= 0 ? '+' : ''}
        {formatNumber(growth)}
      </span>
      <span className="flex items-center gap-1.5" title="λ churn = l⁺ + l⁻">
        <MiniBar value={metrics.churn ?? 0} max={Math.max(reference, 1)} className="w-10" />
        <span className="w-11 text-right text-xs tabular-nums text-amber-300/90">
          {formatNumber(metrics.churn)}
        </span>
      </span>
      <span className="text-right text-xs tabular-nums text-slate-400" title="n modifications">
        {formatNumber(metrics.modifications)}
      </span>
    </>
  )
}

function TreeRow({ node, depth, expanded, onToggle, onDrill, reference }) {
  const isDir = node.kind === 'dir'
  const isOpen = expanded.has(node.path)
  const Chevron = isOpen ? ChevronDown : ChevronRight
  return (
    <button
      type="button"
      onClick={() => onDrill(node.path)}
      className={`${ROW_GRID} w-full border-b border-surface-border/40 px-2 py-1 text-left hover:bg-slate-700/30`}
      style={{ paddingLeft: `${8 + depth * 14}px` }}
      title={isDir ? `focus dashboard on ${node.path}/` : node.path}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {isDir && node.has_children ? (
          <span
            role="presentation"
            onClick={(event) => {
              event.stopPropagation()
              onToggle(node.path)
            }}
            className="rounded p-0.5 text-slate-500 hover:bg-slate-600/40 hover:text-slate-200"
          >
            <Chevron className="h-3.5 w-3.5" />
          </span>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        {isDir ? (
          <Folder className="h-3.5 w-3.5 shrink-0 text-indigo-400/80" />
        ) : (
          <File className="h-3.5 w-3.5 shrink-0 text-slate-500" />
        )}
        <span className="truncate font-mono text-xs text-slate-300">{node.name}</span>
        {isDir && node.metrics?.files != null && (
          <span className="shrink-0 text-[10px] text-slate-600">({formatNumber(node.metrics.files)})</span>
        )}
      </span>
      <MetricsCells metrics={node.metrics} reference={reference} />
    </button>
  )
}

/**
 * Directory rollup tree for the selected commit set. Children load lazily as
 * directories are expanded; clicking a node narrows the whole dashboard to
 * that path (the tree then re-roots itself on the drilled directory).
 */
export default function DirectoryTree({ repo, commitSet, author, path, refreshKey, onDrillPath }) {
  const ready = repo?.status === 'ready'
  const params = hQuery(commitSet, { author, path })
  const key = JSON.stringify(params)
  const [expanded, setExpanded] = useState(new Set())
  const [cache, setCache] = useState(() => new Map())
  const [loadingPaths, setLoadingPaths] = useState(new Set())
  const activeRef = useRef(true)

  const root = useFetch(
    () => (ready ? getMetricsTree(repo.id, params) : Promise.resolve(null)),
    [repo?.id, key, refreshKey],
  )

  const rootPath = root.data?.path ?? ''

  // Fresh filters / root: collapse back to the root and drop cached children.
  useEffect(() => {
    setExpanded(new Set([rootPath]))
    setCache(new Map())
  }, [repo?.id, key, rootPath, refreshKey])

  useEffect(() => {
    activeRef.current = true
    return () => {
      activeRef.current = false
    }
  }, [])

  const toggle = async (nodePath) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(nodePath)) {
        next.delete(nodePath)
      } else {
        next.add(nodePath)
      }
      return next
    })
    if (!ready || cache.has(nodePath) || loadingPaths.has(nodePath)) return
    setLoadingPaths((current) => new Set(current).add(nodePath))
    try {
      const node = await getMetricsTree(repo.id, { ...params, path: nodePath })
      if (activeRef.current) setCache((current) => new Map(current).set(nodePath, node))
    } catch {
      // surfaced through the row staying collapsed; keep the tree usable
    } finally {
      if (activeRef.current) {
        setLoadingPaths((current) => {
          const next = new Set(current)
          next.delete(nodePath)
          return next
        })
      }
    }
  }

  const reference = Math.max(root.data?.metrics?.churn ?? 0, 1)
  const segments = (path ?? '').split('/').filter(Boolean)

  const renderChildren = (node, depth) => {
    if (!expanded.has(node.path) || depth > 40) return null
    const loaded = node.path === rootPath ? node : cache.get(node.path)
    if (!loaded) {
      return (
        <div className="flex items-center gap-2 border-b border-surface-border/40 py-1 text-xs text-slate-500" style={{ paddingLeft: `${24 + depth * 14}px` }}>
          <Loader2 className="h-3 w-3 animate-spin" /> loading…
        </div>
      )
    }
    return (loaded.children ?? []).map((child) => (
      <div key={child.path}>
        <TreeRow node={child} depth={depth} expanded={expanded} onToggle={toggle} onDrill={onDrillPath} reference={reference} />
        {child.kind === 'dir' && renderChildren(child, depth + 1)}
      </div>
    ))
  }

  return (
    <Card
      title="Directory tree"
      subtitle="rollup λ / δ / n per directory (recursive sums)"
      right={
        <button
          type="button"
          onClick={() => {
            setCache(new Map())
            root.reload()
          }}
          className="rounded p-1 text-slate-500 hover:bg-slate-700/50 hover:text-slate-200"
          title="Refresh tree"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      }
      bodyClassName="p-0"
    >
      <div className="flex flex-wrap items-center gap-1 border-b border-surface-border px-3 py-2 text-xs">
        {segments.length > 0 && (
          <button
            type="button"
            onClick={() => onDrillPath('')}
            className="mr-1 inline-flex items-center gap-1 rounded border border-surface-border px-1.5 py-0.5 text-slate-300 hover:bg-slate-700/50"
            title="Back to repository root"
          >
            <ArrowLeft className="h-3 w-3" /> up
          </button>
        )}
        <button
          type="button"
          onClick={() => onDrillPath('')}
          className={`rounded px-1.5 py-0.5 font-mono ${segments.length ? 'text-slate-400 hover:bg-slate-700/50' : 'text-slate-200'}`}
        >
          {repo?.name ?? 'root'}/
        </button>
        {segments.map((segment, index) => {
          const prefix = segments.slice(0, index + 1).join('/')
          const isLast = index === segments.length - 1
          return (
            <span key={prefix} className="flex items-center">
              <button
                type="button"
                onClick={() => !isLast && onDrillPath(prefix)}
                className={`rounded px-1 py-0.5 font-mono ${isLast ? 'text-indigo-300' : 'text-slate-400 hover:bg-slate-700/50'}`}
              >
                {segment}/
              </button>
            </span>
          )
        })}
      </div>

      {!ready ? (
        <Spinner className="justify-center" />
      ) : root.error ? (
        metricsState(root.error) === 'pending' ? (
          <div className="p-4">
            <PendingNote endpoint="GET /api/metrics/{id}/tree" onRetry={root.reload} />
          </div>
        ) : (
          <div className="p-4">
            <ErrorNote error={root.error} onRetry={root.reload} />
          </div>
        )
      ) : root.loading && !root.data ? (
        <Spinner className="justify-center" label="loading rollups…" />
      ) : root.data ? (
        <div className="max-h-[28rem] overflow-auto">
          <div className={`${ROW_GRID} border-b border-surface-border bg-surface px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-slate-500`}>
            <span className="pl-1">path</span>
            <span className="text-right">δ growth</span>
            <span className="text-right">λ churn</span>
            <span className="text-right">n</span>
          </div>
          <TreeRow
            node={{ ...root.data, name: (root.data.path?.split('/').pop() || repo?.name || 'root') + '/', has_children: Boolean(root.data.children?.length) }}
            depth={0}
            expanded={expanded}
            onToggle={toggle}
            onDrill={onDrillPath}
            reference={reference}
          />
          {renderChildren(root.data, 1)}
          {expanded.has(rootPath) && !root.data.children?.length && (
            <EmptyState icon={FolderTree} title="No files touched in the current selection" />
          )}
        </div>
      ) : null}
    </Card>
  )
}
