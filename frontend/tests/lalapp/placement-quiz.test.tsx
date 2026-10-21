import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => 'en',
}))

const { mockApiFetch } = vi.hoisted(() => ({ mockApiFetch: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiFetch: mockApiFetch }))
vi.mock('@/components/ui/page-loading', () => ({
  PageLoading: ({ label }: { label: string }) => <p>{label}</p>,
}))

import LalappPlacementQuiz from '@/lalapp/placement/LalappPlacementQuiz'

function json(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 500, json: async () => body } as Response
}

function step(id: string, questionNumber: number) {
  return {
    session_id: 'session-1',
    question_number: questionNumber,
    max_questions: 25,
    question: {
      id,
      skill: 'grammar',
      difficulty: 'B1',
      question: `Question ${id}`,
      options: ['alpha', 'beta', 'gamma', 'delta'],
    },
    result: null,
  }
}

const result = {
  cefr_level: 'B2',
  score: 0.78,
  skill_profile: { grammar: 0.6, reading: 0.5, vocabulary: 0.55 },
  strengths: [],
  weaknesses: [],
}

describe('LalappPlacementQuiz', () => {
  beforeEach(() => mockApiFetch.mockReset())

  it('starts a session for the language and posts answers to the pending question', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(step('q1', 1)))
      .mockResolvedValueOnce(json(step('q2', 2)))
    render(<LalappPlacementQuiz language="es-ES" onResult={vi.fn()} />)

    fireEvent.click(await screen.findByText('alpha'))
    await screen.findByText('Question q2')

    expect(mockApiFetch).toHaveBeenCalledTimes(2)
    const [startUrl, startInit] = mockApiFetch.mock.calls[0]
    expect(startUrl).toBe('/api/lalapp/placement/start')
    expect(JSON.parse(startInit.body)).toEqual({ language: 'es-ES' })
    const [answerUrl, answerInit] = mockApiFetch.mock.calls[1]
    expect(answerUrl).toBe('/api/lalapp/placement/session-1/answer')
    expect(JSON.parse(answerInit.body)).toEqual({
      question_id: 'q1',
      answer: 'alpha',
    })
  })

  it('hands the final result to the parent', async () => {
    const onResult = vi.fn()
    mockApiFetch
      .mockResolvedValueOnce(json(step('q1', 1)))
      .mockResolvedValueOnce(json({ ...step('q1', 1), question: null, result }))
    render(<LalappPlacementQuiz language="en-GB" onResult={onResult} />)

    fireEvent.click(await screen.findByText('beta'))

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(result))
  })

  it('starts only one session across parent re-renders', async () => {
    mockApiFetch.mockResolvedValue(json(step('q1', 1)))
    const { rerender } = render(
      <LalappPlacementQuiz language="en-GB" onResult={() => {}} />
    )
    await screen.findByText('Question q1')
    rerender(<LalappPlacementQuiz language="en-GB" onResult={() => {}} />)
    rerender(<LalappPlacementQuiz language="en-GB" onResult={() => {}} />)

    expect(mockApiFetch).toHaveBeenCalledTimes(1)
  })

  it('offers a retry that repeats the failed request', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json({}, false))
      .mockResolvedValueOnce(json(step('q1', 1)))
    render(<LalappPlacementQuiz language="en-GB" onResult={vi.fn()} />)

    fireEvent.click(await screen.findByText('retry'))

    await screen.findByText('Question q1')
    expect(mockApiFetch.mock.calls[1][0]).toBe('/api/lalapp/placement/start')
  })
})
