import { useEffect } from 'react'
import { apiFetch } from '@/lib/api'
import {
  SPEECH_SESSION_STATES,
  useSpeechSessionStore,
  type SpeechSessionState,
} from '@/store/speech-session'

const KEEPALIVE_INTERVAL_MS = 60_000

async function call(path: string, method: 'POST' | 'GET') {
  const setState = useSpeechSessionStore.getState().setState
  try {
    const res = await apiFetch(`/api/speech-session/${path}`, { method })
    if (!res.ok) return setState('away')
    const data = (await res.json()) as { state?: string }
    setState(
      (SPEECH_SESSION_STATES as readonly string[]).includes(data.state ?? '')
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
    // A missing, off or away session never recovers by itself: open it again.
    const tick = () => {
      const current = useSpeechSessionStore.getState().state
      const needsOpen =
        current === null || current === 'off' || current === 'away'
      void call(needsOpen ? 'open' : 'keepalive', 'POST')
    }
    tick()
    const keepAlive = () => {
      if (document.visibilityState === 'visible') tick()
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
