import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const { mockApiFetch, mockPush } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  mockPush: vi.fn(),
}))
vi.mock('next-intl', () => ({ useLocale: () => 'sv' }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }))
vi.mock('@/lib/api', () => ({ apiFetch: mockApiFetch }))
vi.mock('@/lalapp/config', () => ({
  LALAPP_SCENARIOS_ENABLED: true,
  LALAPP_PERSONAS_ENABLED: true,
}))
vi.mock('@/store/language', () => ({
  useLanguageStore: (select: (s: unknown) => unknown) =>
    select({ activeLanguage: { code: 'en-GB' } }),
}))

import { ScenarioList } from '@/lalapp/scenarios/ScenarioList'
import { ScenarioPanel } from '@/lalapp/scenarios/ScenarioPanel'
import { ConversationPersona } from '@/lalapp/personas/ConversationPersona'
import { requestedConversation } from '@/lalapp/scenarios/api'

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response
}

const sandra = {
  id: 'en-npc-sandra',
  name: 'Sandra',
  role: 'npc',
  dialect: 'en-GB',
  age: 56,
  backstory: '',
  personality: [],
}
const goal = (sv: string) => ({ en: sv, sv, es: sv })
const cafe = {
  id: 'en-leeds-1-cafe',
  title: "Breakfast at Sandra's",
  summary: goal('Din första morgon i Leeds.'),
  level: 'A1',
  arc: 'leeds',
  order: 1,
  npc: sandra,
  status: 'active',
  conversation_id: 5,
  missions: [
    { id: 'order', goal: goal('Beställ något'), done: true, evidence: '' },
    {
      id: 'price',
      goal: goal('Fråga vad det kostar'),
      done: false,
      evidence: null,
    },
  ],
}
const flat = {
  ...cafe,
  id: 'en-leeds-2-flat',
  title: 'Viewing the flat',
  order: 2,
  status: 'locked',
  conversation_id: null,
}
const interview = {
  ...cafe,
  id: 'en-portland-1-bike-shop',
  title: 'A job at the bike shop',
  arc: 'portland',
  status: 'available',
  conversation_id: null,
}

beforeEach(() => {
  mockApiFetch.mockReset()
  mockPush.mockReset()
  window.history.replaceState(null, '', '/')
})

describe('ScenarioList', () => {
  it('groups scenes by story and shows lock state and goals', async () => {
    mockApiFetch.mockResolvedValueOnce(
      json({
        target_language: 'en-GB',
        plan_level: 'A1',
        scenarios: [cafe, flat, interview],
      })
    )
    render(<ScenarioList />)

    expect(
      await screen.findByRole('region', { name: 'Leeds' })
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Portland' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Fortsätt' })).toHaveAttribute(
      'href',
      '/chat?conversation=5'
    )
    expect(
      screen.getByText('Gör klart föregående scen först')
    ).toBeInTheDocument()
    expect(screen.getAllByText('Beställ något')).toHaveLength(2) // not shown for the locked scene
  })

  it('starts a scene and opens its conversation', async () => {
    mockApiFetch
      .mockResolvedValueOnce(
        json({
          target_language: 'en-GB',
          plan_level: 'B1',
          scenarios: [interview],
        })
      )
      .mockResolvedValueOnce(
        json({ conversation_id: 9, newly_done: [], scenario: interview })
      )
    render(<ScenarioList />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Starta scenen' })
    )
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith('/chat?conversation=9')
    )
    expect(mockApiFetch).toHaveBeenLastCalledWith(
      '/api/lalapp/scenarios/en-portland-1-bike-shop/start',
      { method: 'POST' }
    )
  })
})

describe('ScenarioPanel', () => {
  it('checks goals when a reply finishes and announces new ones', async () => {
    const run = { conversation_id: 5, newly_done: [], scenario: cafe }
    const finished = {
      conversation_id: 5,
      newly_done: ['price'],
      scenario: {
        ...cafe,
        status: 'done',
        missions: cafe.missions.map((m) => ({ ...m, done: true })),
      },
    }
    mockApiFetch
      .mockResolvedValueOnce(json(run))
      .mockResolvedValueOnce(json(finished))
    const { rerender } = render(
      <ScenarioPanel conversationId={5} busy={false} />
    )
    expect(await screen.findByText('Dina mål')).toBeInTheDocument()
    expect(mockApiFetch).toHaveBeenCalledTimes(1)

    rerender(<ScenarioPanel conversationId={5} busy={true} />)
    rerender(<ScenarioPanel conversationId={5} busy={false} />)

    expect(
      await screen.findByText('Mål nått: Fråga vad det kostar')
    ).toBeInTheDocument()
    expect(screen.getByText(/Scenen är klar!/)).toBeInTheDocument()
    expect(mockApiFetch).toHaveBeenLastCalledWith(
      '/api/lalapp/scenarios/runs/5/check',
      { method: 'POST' }
    )
  })

  it('renders nothing for an ordinary conversation', async () => {
    mockApiFetch.mockResolvedValueOnce(json({ detail: 'x' }, 404))
    const { container } = render(
      <ScenarioPanel conversationId={3} busy={false} />
    )
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})

describe('scene conversations in chat', () => {
  it('opens the requested conversation only if it exists', () => {
    window.history.replaceState(null, '', '/chat?conversation=5')
    expect(requestedConversation([{ id: 7 }, { id: 5 }])).toBe(5)
    expect(requestedConversation([{ id: 7 }])).toBeNull()
  })

  it('names the NPC without offering to switch character', async () => {
    mockApiFetch.mockImplementation(async (url: string) =>
      url === '/api/lalapp/personas'
        ? json({
            target_language: 'en-GB',
            preferred_peer_id: null,
            personas: [],
          })
        : json(sandra)
    )
    render(<ConversationPersona conversationId={5} />)
    expect(await screen.findByText('Med Sandra')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })
})
