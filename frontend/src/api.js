import axios from 'axios'

// Shared axios instance: the Vite dev server proxies /api to the FastAPI backend.
export const api = axios.create({ baseURL: '/api', timeout: 120000 })

/**
 * INTEGRATION CONTRACT — every backend call in the dashboard goes through this
 * module. The selected commit set `H` is serialised as query parameters:
 *   - since / until : committer timestamps in epoch seconds (since inclusive,
 *     until exclusive)  -> time-based H_t
 *   - from_index / to_index : 0-based positions in the newest-first git log
 *     (i inclusive, j exclusive)  -> interval H_{i,j}
 *   - hashes : comma-separated commit hashes  -> manual selection
 * Precedence when several are supplied: hashes > indices > time window.
 *
 * Repository endpoints (implemented — Steps 2/3):
 *   GET    /repo/list                         -> { repos: [...] }
 *   GET    /repo/{id}                         -> repo record
 *   GET    /repo/{id}/commits?offset&limit&since&until&author&path
 *   POST   /repo/upload  (multipart "file")   -> repo record (202)
 *   POST   /repo/clone   ({ url })            -> repo record (202)
 *   DELETE /repo/{id}
 *
 * Metrics endpoints (owned by the metrics engine; expected shapes used by the
 * dashboard — components degrade gracefully while these return 404):
 *   GET  /metrics/{id}/summary?<H>&author&path
 *        -> { commits, authors, files, added, removed, growth, churn,
 *             modifications, frequency, churn_rate }
 *   GET  /metrics/{id}/tree?<H>&author&path
 *        -> { path, kind, metrics: {...}, children: [
 *             { name, path, kind: 'dir'|'file', has_children, metrics } ] }
 *        metrics per node: { files, added, removed, growth, churn,
 *                            modifications, frequency, churn_rate, authors }
 *   GET  /metrics/{id}/files?<H>&path&sort&limit
 *        -> { files: [{ path, added, removed, growth, churn,
 *                       modifications, frequency, churn_rate }] }
 *   GET  /metrics/{id}/authors?<H>&path
 *        -> { authors: [{ name, email, raw: [{name,email}], added, removed,
 *                         churn, modifications, ownership }] }
 *   GET  /metrics/{id}/series?<H>&author&path&bucket=month|day
 *        -> { buckets: [{ key, added, removed, churn, commits }] }
 *   POST /repo/{id}/authors/merge  { target: {name,email},
 *                                    sources: [{name,email}] }
 */

/** Human-readable message for an axios error (FastAPI `detail` when present). */
export function apiError(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (error?.code === 'ERR_NETWORK') return 'cannot reach the backend — is it running?'
  return error?.message ?? 'unexpected error'
}

/**
 * True when the endpoint itself does not exist yet (metrics engine pending).
 * FastAPI answers unknown routes with 404 {"detail": "Not Found"}, whereas a
 * 404 from a known route carries a specific message (e.g. unknown repo id).
 */
export function isMissingEndpoint(error) {
  return (
    error?.response?.status === 404 &&
    error.response.data?.detail === 'Not Found'
  )
}

/**
 * Classify a failed metrics fetch: 'pending' while the route itself has not
 * landed yet (metrics engine still in progress), 'failed' otherwise.
 */
export function metricsState(error) {
  return isMissingEndpoint(error) ? 'pending' : 'failed'
}

/** Drop empty values and serialise arrays/sets as comma-separated strings. */
function cleanParams(params) {
  const out = {}
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      if (!value.length) continue
      out[key] = value.join(',')
    } else if (value instanceof Set) {
      if (!value.size) continue
      out[key] = [...value].join(',')
    } else {
      out[key] = value
    }
  }
  return out
}

/** Serialise an H (commit set) selection plus extra filters to query params. */
export function hQuery(commitSet, extra = {}) {
  const params = { ...extra }
  const mode = commitSet?.mode ?? 'all'
  if (mode === 'window') {
    params.since = commitSet.since
    params.until = commitSet.until
  } else if (mode === 'interval') {
    params.from_index = commitSet.fromIndex
    params.to_index = commitSet.toIndex
  } else if (mode === 'manual') {
    const hashes = commitSet.hashes instanceof Set ? [...commitSet.hashes] : commitSet.hashes
    params.hashes = hashes
  }
  return cleanParams(params)
}

// --- backend health ---------------------------------------------------------
export const getHealth = () => api.get('/health').then((r) => r.data)

// --- repositories -----------------------------------------------------------
export const listRepos = () => api.get('/repo/list').then((r) => r.data.repos)
export const getRepo = (repoId) => api.get(`/repo/${repoId}`).then((r) => r.data)
export const cloneRepo = (url) => api.post('/repo/clone', { url }).then((r) => r.data)
export const deleteRepo = (repoId) => api.delete(`/repo/${repoId}`)
export const getCommits = (repoId, params) =>
  api.get(`/repo/${repoId}/commits`, { params: cleanParams(params) }).then((r) => r.data)

export function uploadRepo(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  return api
    .post('/repo/upload', form, { timeout: 0, onUploadProgress: onProgress })
    .then((r) => r.data)
}

// --- metrics (contract above; degrade gracefully until implemented) ---------
export const getMetricsSummary = (repoId, params) =>
  api.get(`/metrics/${repoId}/summary`, { params: cleanParams(params) }).then((r) => r.data)
export const getMetricsTree = (repoId, params) =>
  api.get(`/metrics/${repoId}/tree`, { params: cleanParams(params) }).then((r) => r.data)
export const getMetricsFiles = (repoId, params) =>
  api.get(`/metrics/${repoId}/files`, { params: cleanParams(params) }).then((r) => r.data)
export const getMetricsAuthors = (repoId, params) =>
  api.get(`/metrics/${repoId}/authors`, { params: cleanParams(params) }).then((r) => r.data)
export const getMetricsSeries = (repoId, params) =>
  api.get(`/metrics/${repoId}/series`, { params: cleanParams(params) }).then((r) => r.data)

export const mergeAuthors = (repoId, payload) =>
  api.post(`/repo/${repoId}/authors/merge`, payload).then((r) => r.data)

export default api
