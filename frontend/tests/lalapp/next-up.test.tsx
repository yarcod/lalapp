import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const { mockApiFetch, mockPush } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  mockPush: vi.fn(),
}))
vi.mock('next-intl', () => ({ useLocale: () => 'sv' }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }))
vi.mock('@/lib/api', () => ({ apiFetch: mockApiFetch }))
vi.mock('@/lalapp/config', () => ({ LALAPP_ADAPTIVE_ENABLED: true }))
vi.mock('@/store/language', () => ({
  useLanguageStore: (select: (s: unknown) => unknown) =>
    select({ activeLanguage: { code: 'es-ES' } }),
}))

import { LalappNextUp } from '@/lalapp/adaptive/NextUp'

function json(body: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as Response
}

const suggestion = {
  plan_id: 7,
  skill: 'grammar',
  cefr_level: 'A2',
  reason: 'review',
  focus: ['preterito-vs-imperfecto'],
  unit_title: 'Describir el pasado',
  predicted_success: 0.72,
  lesson: null,
  level_up: null,
}
const lesson = {
  id: 42,
  title: 'Cuando era niño',
  lesson_type: 'grammar',
  cefr_level: 'A2',
  reason: 'review',
  focus: ['preterito-vs-imperfecto'],
  predicted_success: 0.7,
}

beforeEach(() => {
  mockApiFetch.mockReset()
  mockPush.mockReset()
})

describe('LalappNextUp', () => {
  it('explains the suggestion and creates the lesson on demand', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(suggestion))
      .mockResolvedValueOnce(json({ ...suggestion, lesson }))
    render(<LalappNextUp />)

    expect(await screen.findByText('Describir el pasado')).toBeInTheDocument()
    expect(
      screen.getByText(/Repetera preterito vs imperfecto/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/A2 · du väntas klara cirka 72 %/)
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Skapa lektionen' }))
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/lesson/42'))
    expect(mockApiFetch).toHaveBeenLastCalledWith('/api/lalapp/next', {
      method: 'POST',
    })
    expect(
      screen.getByRole('link', { name: 'Starta lektionen' })
    ).toHaveAttribute('href', '/lesson/42')
  })

  it('shows an error when generation fails', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(suggestion))
      .mockResolvedValueOnce(json({ detail: 'x' }, 503))
    render(<LalappNextUp />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Skapa lektionen' })
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Lektionen kunde inte skapas'
    )
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('confirms before starting the next level with the same schedule', async () => {
    const levelUp = {
      next_level: 'B1',
      goals: ['grammar', 'vocabulary'],
      duration_weeks: 8,
      days_per_week: 3,
      target_language: 'es-ES',
    }
    mockApiFetch
      .mockResolvedValueOnce(json({ ...suggestion, level_up: levelUp }))
      .mockResolvedValueOnce(json({ id: 8 }))
    render(<LalappNextUp />)

    expect(await screen.findByText('Redo för B1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Gå upp till B1' }))
    expect(mockApiFetch).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Starta plan för B1' }))

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/plan'))
    const [url, init] = mockApiFetch.mock.calls[1]
    expect(url).toBe('/api/study-plan/generate')
    expect(JSON.parse(init.body)).toEqual({
      cefr_level: 'B1',
      goals: ['grammar', 'vocabulary'],
      duration_weeks: 8,
      days_per_week: 3,
      target_language: 'es-ES',
    })
  })

  it('renders nothing without an active plan', async () => {
    mockApiFetch.mockResolvedValueOnce(json(null))
    const { container } = render(<LalappNextUp />)
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
