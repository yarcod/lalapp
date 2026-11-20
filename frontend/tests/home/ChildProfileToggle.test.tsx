import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('@/lib/api', () => ({ apiFetch: mocks.apiFetch }))

import { ChildProfileToggle } from '@/home/components/ChildProfileToggle'
import { useHomeProfileStore } from '@/home/store/profile'

function json(data: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: () => Promise.resolve(data) }
}

describe('ChildProfileToggle', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    useHomeProfileStore.setState({
      isChild: false,
      taggedLanguages: [],
      loaded: false,
    })
  })

  it('toggle reflects loaded profile', async () => {
    mocks.apiFetch.mockResolvedValue(
      json({ is_child: true, tagged_languages: [] })
    )
    render(<ChildProfileToggle />)
    const box = screen.getByLabelText('isChild') as HTMLInputElement
    await waitFor(() => expect(box.checked).toBe(true))
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/home/profile')
  })

  it('click saves immediately via PUT /api/home/profile', async () => {
    useHomeProfileStore.setState({ loaded: true })
    mocks.apiFetch.mockResolvedValue(
      json({ is_child: true, tagged_languages: ['sv-SE'] })
    )
    render(<ChildProfileToggle />)
    const box = screen.getByLabelText('isChild') as HTMLInputElement
    fireEvent.click(box)
    expect(box.checked).toBe(true)
    await waitFor(() => expect(mocks.apiFetch).toHaveBeenCalledTimes(1))
    const [path, init] = mocks.apiFetch.mock.calls[0]
    expect(path).toBe('/api/home/profile')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ is_child: true })
    await waitFor(() =>
      expect(useHomeProfileStore.getState().taggedLanguages).toEqual(['sv-SE'])
    )
  })

  it('failed save restores previous value and shows an error', async () => {
    useHomeProfileStore.setState({ loaded: true })
    mocks.apiFetch.mockResolvedValue(json({}, false))
    render(<ChildProfileToggle />)
    const box = screen.getByLabelText('isChild') as HTMLInputElement
    fireEvent.click(box)
    const error = await screen.findByText(/saveFailed/)
    expect(error.className).toContain('text-fl-error')
    expect(box.checked).toBe(false)
  })
})
