import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('@/lib/api', () => ({ apiFetch: mocks.apiFetch }))

import { ChildProfileToggle } from '@/home/components/ChildProfileToggle'
import { useHomeProfileStore } from '@/home/store/profile'
import { useAuthStore } from '@/store/auth'
import { useLanguageStore } from '@/store/language'

function json(data: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: () => Promise.resolve(data) }
}

function deferred() {
  let resolve!: (v: unknown) => void
  const promise = new Promise((r) => {
    resolve = r
  })
  return { promise, resolve }
}

const bumpSession = () =>
  act(() => {
    useAuthStore.setState((s) => ({ sessionVersion: s.sessionVersion + 1 }))
  })

describe('home profile store session handling', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    bumpSession()
  })

  it('a session change resets the profile and reloads for the new user', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      json({ is_child: true, tagged_languages: ['sv-SE'] })
    )
    render(<ChildProfileToggle />)
    await waitFor(() =>
      expect(useHomeProfileStore.getState().isChild).toBe(true)
    )

    mocks.apiFetch.mockResolvedValueOnce(
      json({ is_child: false, tagged_languages: [] })
    )
    bumpSession()
    expect(useHomeProfileStore.getState()).toMatchObject({
      isChild: false,
      taggedLanguages: [],
      loaded: false,
    })
    await waitFor(() => expect(mocks.apiFetch).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(useHomeProfileStore.getState().loaded).toBe(true)
    )
    expect(useHomeProfileStore.getState().taggedLanguages).toEqual([])
  })

  it('discards a stale response from the previous session', async () => {
    const late = deferred()
    mocks.apiFetch.mockReturnValueOnce(late.promise)
    mocks.apiFetch.mockResolvedValue(
      json({ is_child: false, tagged_languages: [] })
    )
    render(<ChildProfileToggle />)
    await waitFor(() => expect(mocks.apiFetch).toHaveBeenCalledTimes(1))
    bumpSession()
    late.resolve(json({ is_child: true, tagged_languages: ['sv-SE'] }))
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    await waitFor(() =>
      expect(useHomeProfileStore.getState().loaded).toBe(true)
    )
    expect(useHomeProfileStore.getState()).toMatchObject({
      isChild: false,
      taggedLanguages: [],
    })
  })

  it('disables the input while saving', async () => {
    useHomeProfileStore.setState({ loaded: true })
    const put = deferred()
    mocks.apiFetch.mockReturnValueOnce(put.promise)
    render(<ChildProfileToggle />)
    const box = screen.getByLabelText('isChild') as HTMLInputElement
    fireEvent.click(box)
    await waitFor(() => expect(box.disabled).toBe(true))
    put.resolve(json({ is_child: true, tagged_languages: [] }))
    await waitFor(() => expect(box.disabled).toBe(false))
    expect(box.checked).toBe(true)
  })

  it('a failed load can be retried on the next mount', async () => {
    mocks.apiFetch.mockResolvedValueOnce(json({}, false))
    const first = render(<ChildProfileToggle />)
    await waitFor(() => expect(mocks.apiFetch).toHaveBeenCalledTimes(1))
    await act(async () => {
      await Promise.resolve()
    })
    first.unmount()

    mocks.apiFetch.mockResolvedValueOnce(
      json({ is_child: true, tagged_languages: [] })
    )
    render(<ChildProfileToggle />)
    await waitFor(() =>
      expect(useHomeProfileStore.getState().isChild).toBe(true)
    )
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
  })

  it('reloads tagged languages when the learner languages change', async () => {
    mocks.apiFetch.mockResolvedValueOnce(
      json({ is_child: false, tagged_languages: [] })
    )
    render(<ChildProfileToggle />)
    await waitFor(() =>
      expect(useHomeProfileStore.getState().loaded).toBe(true)
    )

    mocks.apiFetch.mockResolvedValueOnce(
      json({ is_child: false, tagged_languages: ['en-GB'] })
    )
    const before = useLanguageStore.getState().userLanguages
    act(() => {
      useLanguageStore.setState({ userLanguages: [...before] })
    })
    await waitFor(() =>
      expect(useHomeProfileStore.getState().taggedLanguages).toEqual(['en-GB'])
    )
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
  })
})
