import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const { mockApiFetch, locale } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  locale: { current: 'sv' },
}))
vi.mock('next-intl', () => ({ useLocale: () => locale.current }))
vi.mock('@/lib/api', () => ({ apiFetch: mockApiFetch }))
vi.mock('@/lalapp/config', () => ({
  LALAPP_PERSONAS_ENABLED: true,
  LALAPP_PLACEMENT_ENABLED: true,
}))

import { PersonaSection } from '@/lalapp/personas/PersonaSection'
import { ConversationPersona } from '@/lalapp/personas/ConversationPersona'
import { lalappMessage } from '@/lalapp/i18n'

function json(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response
}

const dan = {
  id: 'en-peer-dan',
  name: 'Dan',
  role: 'peer',
  dialect: 'en-US',
  age: 52,
  backstory: 'Retired firefighter.',
  personality: ['warm'],
}
const amira = { ...dan, id: 'en-peer-amira', name: 'Amira', dialect: 'en-GB' }
const erik = { ...dan, id: 'en-guide-erik', name: 'Erik', role: 'guide' }
const cast = (preferred: string) => ({
  target_language: 'en-US',
  preferred_peer_id: preferred,
  personas: [erik, amira, dan],
})

beforeEach(() => {
  mockApiFetch.mockReset()
  locale.current = 'sv'
})

describe('PersonaSection', () => {
  it('lists partners and saves a new choice', async () => {
    mockApiFetch
      .mockResolvedValueOnce(json(cast('en-peer-dan')))
      .mockResolvedValueOnce(json(cast('en-peer-amira')))
    render(<PersonaSection />)

    const amiraOption = await screen.findByRole('radio', { name: /Amira/ })
    expect(screen.getByRole('radio', { name: /Dan/ })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    expect(screen.queryByRole('radio', { name: /Erik/ })).toBeNull()
    expect(screen.getByText(/Erik är din guide/)).toBeInTheDocument()
    expect(screen.getByText(/brittisk engelska/)).toBeInTheDocument()

    fireEvent.click(amiraOption)

    await waitFor(() =>
      expect(amiraOption).toHaveAttribute('aria-checked', 'true')
    )
    const [url, init] = mockApiFetch.mock.calls[1]
    expect(url).toBe('/api/lalapp/personas/peer')
    expect(JSON.parse(init.body)).toEqual({ persona_id: 'en-peer-amira' })
  })
})

describe('ConversationPersona', () => {
  it('names the preferred partner for a new conversation', async () => {
    mockApiFetch.mockResolvedValueOnce(json(cast('en-peer-dan')))
    render(<ConversationPersona conversationId={null} />)
    expect(await screen.findByText('Med Dan')).toBeInTheDocument()
  })

  it('switches the character of an existing conversation', async () => {
    mockApiFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/lalapp/personas') return json(cast('en-peer-dan'))
      if (init?.method === 'PUT') return json(erik)
      return json(amira)
    })
    render(<ConversationPersona conversationId={7} />)

    const select = await screen.findByRole('combobox')
    await waitFor(() => expect(select).toHaveValue('en-peer-amira'))
    fireEvent.change(select, { target: { value: 'en-guide-erik' } })

    await waitFor(() => expect(select).toHaveValue('en-guide-erik'))
    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/lalapp/conversations/7/persona',
      expect.objectContaining({ method: 'PUT' })
    )
  })
})

describe('lalappMessage', () => {
  it('falls back to English for other interface languages', () => {
    expect(lalappMessage('de', 'talkingWith', { name: 'Lucía' })).toBe(
      'With Lucía'
    )
    expect(lalappMessage('sv', 'age', { age: 24 })).toBe('24 år')
  })
})
