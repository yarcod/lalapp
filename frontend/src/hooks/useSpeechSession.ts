import { useEffect } from 'react'
import { apiFetch } from '@/lib/api'
import {
  useSpeechSessionStore,
  type SpeechSessionState,
} from '@/store/speech-session'

const KEEPALIVE_INTERVAL_MS = 60_000
const KNOWN_STATES = ['off', 'switching', 'ready', 'busy', 'shared', 'away']

async function call(path: string, method: 'POST' | 'GET') {
  const setState = useSpeechSessionStore.getState().setState
  try {
    const res = await apiFetch(`/api/speech-session/${path}`, { method })
    if (!res.ok) return setState('away')
    const data = (await res.json()) as { state?: string }
    setState(
      KNOWN_STATES.includes(data.state ?? '')
        ? (data.state as SpeechSessionState)
        : 'away'
    )
  } catch {
    setState('away')
  }
}

/**
 * Opens the speech session once enabled, keeps it alive every 60 s while the
 * page is visible, and returns the gateway state.
 */
export function useSpeechSession(enabled: boolean) {
  const state = useSpeechSessionStore((s) => s.state)

  useEffect(() => {
    if (!enabled) return
    void call('open', 'POST')
    const keepAlive = () => {
      if (document.visibilityState === 'visible') void call('keepalive', 'POST')
    }
    const timer = setInterval(keepAlive, KEEPALIVE_INTERVAL_MS)
    document.addEventListener('visibilitychange', keepAlive)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', keepAlive)
    }
  }, [enabled])

  return state
}
