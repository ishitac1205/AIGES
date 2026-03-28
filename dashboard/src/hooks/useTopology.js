import { useState, useEffect, useRef, useCallback } from 'react'
import { HAS_OPERATOR_TOKEN, OPERATOR_HEADERS, apiFetch, apiJson } from '../api'
const POLL_MS = 2000
const REQUEST_TIMEOUT_MS = 8000
const OFFLINE_GRACE_MS = 20000
const FAILURE_THRESHOLD = 3

export function useTopology() {
  const [data, setData] = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)
  const inFlightRef = useRef(false)
  const failureCountRef = useRef(0)
  const lastSuccessRef = useRef(0)

  const fetchTopology = useCallback(async () => {
    if (inFlightRef.current) return
    inFlightRef.current = true
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS)
    try {
      const json = await apiJson('/topology', { signal: ctrl.signal })
      clearTimeout(timer)
      if (!ctrl.signal.aborted) {
        setData(json)
        setConnected(true)
        setError(null)
        failureCountRef.current = 0
        lastSuccessRef.current = Date.now()
      }
    } catch (e) {
      clearTimeout(timer)
      if (!ctrl.signal.aborted) {
        failureCountRef.current += 1
        const staleForMs = Date.now() - lastSuccessRef.current
        const shouldMarkOffline =
          !lastSuccessRef.current ||
          failureCountRef.current >= FAILURE_THRESHOLD ||
          staleForMs >= OFFLINE_GRACE_MS
        if (shouldMarkOffline) {
          setConnected(false)
        }
        setError(e.name === 'AbortError' ? 'API timeout' : e.message)
      }
    } finally {
      inFlightRef.current = false
    }
  }, [])

  useEffect(() => {
    fetchTopology()
    const interval = setInterval(fetchTopology, POLL_MS)
    return () => {
      clearInterval(interval)
      abortRef.current?.abort()
    }
  }, [fetchTopology])

  const fetchWindow = useCallback(async (service, signal) => {
    try {
      const res = await apiFetch(`/window/${service}`, signal ? { signal } : undefined)
      if (!res.ok) return null
      return await res.json()
    } catch { return null }
  }, [])

  const triggerRemediation = useCallback(async (service, failureType = 'generic_anomaly') => {
    try {
      const res = await apiFetch('/remediate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...OPERATOR_HEADERS },
        body: JSON.stringify({ service, failure_type: failureType }),
      })
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}))
        throw new Error(payload?.detail || `HTTP ${res.status}`)
      }
      return await res.json()
    } catch (e) {
      return { result: { status: 'manual_required', operator_summary: e.message } }
    }
  }, [])

  const triggerDemo = useCallback(async (service = 'recommendationservice', owner = 'operator') => {
    const demoPath = HAS_OPERATOR_TOKEN ? '/demo/run' : '/demo/public-run'
    const res = await apiFetch(demoPath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...OPERATOR_HEADERS },
      body: JSON.stringify({ service, owner: HAS_OPERATOR_TOKEN ? owner : 'public-viewer' }),
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      throw new Error(payload?.detail || `HTTP ${res.status}`)
    }
    return await res.json()
  }, [])

  return { data, connected, error, fetchWindow, triggerRemediation, triggerDemo, refreshTopology: fetchTopology }
}
