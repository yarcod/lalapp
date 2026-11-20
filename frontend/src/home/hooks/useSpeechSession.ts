import { useEffect } from 'react'
import { apiFetch } from '@/lib/api'
import {
  SPEECH_SESSION_STATES,
  useSpeechSessionStore,
  type SpeechSessionState,
} from '@/home/store/speech-session'

const KEEPALIVE_INTERVAL_MS = 60_000
const SETTLING_POLL_INTERVAL_MS = 5_000

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

function nextPollDelay() {
  const current = useSpeechSessionStore.getState().state
  return current === 'switching' || current === 'busy'
    ? SETTLING_POLL_INTERVAL_MS
    : KEEPALIVE_INTERVAL_MS
}

/**
 * Opens the speech session once enabled and returns the gateway state. Keeps it
 * alive while the page is visible: every 5 s while the voice is switching or
 * busy, otherwise every 60 s.
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
      return call(needsOpen ? 'open' : 'keepalive', 'POST')
    }
    let timer: ReturnType<typeof setTimeout>
    let stopped = false
    const schedule = () => {
      clearTimeout(timer)
      if (!stopped) timer = setTimeout(poll, nextPollDelay())
    }
    const poll = async () => {
      if (document.visibilityState === 'visible') await tick()
      schedule()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void tick().finally(schedule)
    }
    void tick().finally(schedule)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stopped = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [enabled])

  return state
}
