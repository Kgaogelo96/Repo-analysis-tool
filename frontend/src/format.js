/** Shared formatting and commit-set helpers for the dashboard. */

export function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  if (Math.abs(value) < 10000) return formatNumber(value)
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

export function formatDate(epochSeconds) {
  if (!epochSeconds) return '–'
  return new Date(epochSeconds * 1000).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function shortHash(hash) {
  return hash ? hash.slice(0, 8) : ''
}

/** datetime-local input value -> epoch seconds (undefined when empty/invalid). */
export function toEpoch(datetimeLocalValue) {
  if (!datetimeLocalValue) return undefined
  const ms = new Date(datetimeLocalValue).getTime()
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000)
}

/** Epoch seconds -> value for a datetime-local input ('' when absent). */
export function toDatetimeLocal(epochSeconds) {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  const pad = (value) => String(value).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** Full date + time for tables. */
export function formatDateTime(epochSeconds) {
  if (!epochSeconds) return '–'
  return new Date(epochSeconds * 1000).toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Human-readable byte size for uploads. */
export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

/** Epoch seconds -> 'YYYY-MM' (month bucket) or 'YYYY-MM-DD' (day bucket). */
export function bucketKey(epochSeconds, granularity) {
  const date = new Date(epochSeconds * 1000)
  if (granularity === 'day') return date.toISOString().slice(0, 10)
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

/**
 * Apply a commit-set (H) selection plus an author substring filter to the
 * parsed commit list — used by the preview widgets. The metrics engine applies
 * the same selection server-side for the authoritative numbers.
 */
export function selectCommits(commits, commitSet, authorQuery) {
  if (!commits?.length) return []
  let rows = commits
  const mode = commitSet?.mode ?? 'all'
  if (mode === 'window') {
    const { since, until } = commitSet
    rows = rows.filter(
      (commit) =>
        (since === undefined || commit.author_ts >= since) &&
        (until === undefined || commit.author_ts < until),
    )
  } else if (mode === 'interval') {
    const from = Number.isFinite(commitSet.fromIndex) ? commitSet.fromIndex : 0
    const to = Number.isFinite(commitSet.toIndex) ? commitSet.toIndex : rows.length
    rows = rows.slice(Math.max(0, from), Math.max(0, to))
  } else if (mode === 'manual') {
    const set = commitSet.hashes instanceof Set ? commitSet.hashes : new Set(commitSet.hashes ?? [])
    rows = rows.filter((commit) => set.has(commit.hash))
  }
  if (authorQuery) {
    const query = authorQuery.toLowerCase()
    rows = rows.filter((commit) =>
      `${commit.author.name} ${commit.author.email} ${commit.raw_author.name} ${commit.raw_author.email}`
        .toLowerCase()
        .includes(query),
    )
  }
  return rows
}
