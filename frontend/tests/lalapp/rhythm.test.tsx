import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const { mockApiFetch } = vi.hoisted(() => ({ mockApiFetch: vi.fn() }))
vi.mock('next-intl', () => ({ useLocale: () => 'sv' }))
vi.mock('@/lib/api', () => ({ apiFetch: mockApiFetch }))
vi.mock('@/lalapp/config', () => ({ LALAPP_RHYTHM_ENABLED: true }))
vi.mock('@/store/language', () => ({
  useLanguageStore: (select: (s: unknown) => unknown) =>
    select({ activeLanguage: { code: 'es-ES' } }),
}))

import { RhythmCard } from '@/lalapp/rhythm/RhythmCard'

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response
}

const rhythm = {
  target_language: 'es-ES',
  days_per_week: 3,
  week_start: '2026-10-19',
  active_days: ['2026-10-19', '2026-10-21'],
  weeks_kept: 5,
  weeks_counted: 8,
  turns_this_week: 34,
  stretch_turns_this_week: 6,
  milestones: [
    {
      id: 1,
      key: 'skill_level:vocabulary:A2',
      data: { skill: 'vocabulary', level: 'A2' },
      created_at: '2026-10-21T10:00:00',
    },
    {
      id: 2,
      key: 'scene_done:es-valencia-1-cafe',
      data: { title: 'Desayuno en el Bar Pepa', npc: 'Pepa' },
      created_at: '2026-10-21T11:00:00',
    },
  ],
}

beforeEach(() => {
  mockApiFetch.mockReset()
})

describe('RhythmCard', () => {
  it('shows the week against the goal without loss framing', async () => {
    mockApiFetch.mockResolvedValueOnce(json(rhythm))
    render(<RhythmCard />)

    expect(
      await screen.findByText('2 av 3 dagar den här veckan')
    ).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(7 + 2)
    expect(
      screen.getByText('Rytmen hölls 5 av de senaste 8 veckorna')
    ).toBeInTheDocument()
    expect(
      screen.getByText('34 egna repliker den här veckan · 6 längre än vanligt')
    ).toBeInTheDocument()
    expect(screen.queryByText(/Veckans mål är nått/)).not.toBeInTheDocument()
  })

  it('explains milestones and dismisses them for good', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(rhythm))
      .mockResolvedValueOnce({ ok: true, status: 204 } as Response)
    render(<RhythmCard />)

    expect(
      await screen.findByText(
        'Uppskattningen för ordförråd ligger nu på A2, över din plan.'
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText('Du klarade scenen ”Desayuno en el Bar Pepa” med Pepa.')
    ).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Uppfattat' })[0])
    expect(screen.queryByText(/ordförråd/)).not.toBeInTheDocument()
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenLastCalledWith(
        '/api/lalapp/milestones/1/seen',
        { method: 'POST' }
      )
    )
  })

  it('saves a new goal', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(rhythm))
      .mockResolvedValueOnce(json({ ...rhythm, days_per_week: 2 }))
    render(<RhythmCard />)
    fireEvent.change(await screen.findByRole('combobox'), {
      target: { value: '2' },
    })
    expect(await screen.findByText(/Veckans mål är nått/)).toBeInTheDocument()
    const [, init] = mockApiFetch.mock.calls[1]
    expect(JSON.parse(init.body)).toEqual({ days_per_week: 2 })
  })
})
