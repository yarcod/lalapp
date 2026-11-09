import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiFetch }))

import { useSpeechSession } from '@/hooks/useSpeechSession'
import { useSpeechSessionStore } from '@/store/speech-session'

function answer(state: string) {
  apiFetch.mockResolvedValue({ ok: true, json: async () => ({ state }) })
}

function setVisibility(value: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => value,
  })
}

const calls = (path: string) =>
  apiFetch.mock.calls.filter(([url]) => url === path).length

describe('useSpeechSession', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    apiFetch.mockReset()
    answer('switching')
    setVisibility('visible')
    useSpeechSessionStore.setState({ state: null })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('opens the session on load and exposes the state', async () => {
    const { result } = renderHook(() => useSpeechSession(true))
    await act(async () => {})
    expect(apiFetch).toHaveBeenCalledWith('/api/speech-session/open', {
      method: 'POST',
    })
    expect(result.current).toBe('switching')
  })

  it('does nothing until enabled', async () => {
    renderHook(() => useSpeechSession(false))
    await act(async () => {
      vi.advanceTimersByTime(120_000)
    })
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it('keeps alive every 60s while visible and skips while hidden', async () => {
    renderHook(() => useSpeechSession(true))
    await act(async () => {})
    answer('ready')

    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(1)
    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(2)

    setVisibility('hidden')
    await act(async () => {
      vi.advanceTimersByTime(180_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(2)
  })

  it.each(['switching', 'busy'])('polls every 5s while %s', async (state) => {
    answer(state)
    renderHook(() => useSpeechSession(true))
    await act(async () => {})

    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(1)

    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(2)
  })

  it('falls back to 60s polling once ready', async () => {
    answer('switching')
    renderHook(() => useSpeechSession(true))
    await act(async () => {})
    answer('ready')
    await act(async () => {
      vi.advanceTimersByTime(5_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(1)

    await act(async () => {
      vi.advanceTimersByTime(30_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(1)
    await act(async () => {
      vi.advanceTimersByTime(30_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(2)
  })

  it('stops keeping alive after unmount', async () => {
    const { unmount } = renderHook(() => useSpeechSession(true))
    await act(async () => {})
    unmount()
    await act(async () => {
      vi.advanceTimersByTime(120_000)
    })
    expect(calls('/api/speech-session/keepalive')).toBe(0)
  })

  it('reports away when the request fails', async () => {
    apiFetch.mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useSpeechSession(true))
    await act(async () => {})
    expect(result.current).toBe('away')
  })

  it.each(['off', 'away'])('hook reopens when %s', async (state) => {
    answer(state)
    renderHook(() => useSpeechSession(true))
    await act(async () => {})
    expect(calls('/api/speech-session/open')).toBe(1)

    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    expect(calls('/api/speech-session/open')).toBe(2)
    expect(calls('/api/speech-session/keepalive')).toBe(0)
  })
})
