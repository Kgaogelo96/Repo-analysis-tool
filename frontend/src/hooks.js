import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Run an async fetcher and track its loading/error state, re-running whenever
 * the dependency list changes. Responses are discarded when a newer request
 * has started in the meantime, which matters when filters change quickly and
 * several overlapping requests could resolve out of order.
 */
export function useFetch(fetcher, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const sequence = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const load = useCallback(() => {
    const id = ++sequence.current
    setState((prev) => ({ ...prev, loading: true }))
    fetcherRef.current().then(
      (data) => {
        if (sequence.current === id) setState({ data, error: null, loading: false })
      },
      (error) => {
        if (sequence.current === id) setState({ data: null, error, loading: false })
      },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    load()
  }, [load])

  return { ...state, reload: load }
}
