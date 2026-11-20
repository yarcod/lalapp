import { fireEvent, render, screen } from '@testing-library/react'
import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  fetchFreemium: vi.fn(),
  decrementFreemium: vi.fn(),
  dismissTooltip: vi.fn(),
  handleTextSelection: vi.fn(),
  audioPlayer: vi.fn(),
  activeCode: 'en-GB',
}))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('@/lib/api', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: (state: object) => unknown) =>
    selector({
      user: {
        username: 'learner',
        displayName: 'Learner',
        avatarUrl: null,
        subscription_status: 'active',
      },
    }),
  isSubscribed: () => true,
  isFreemiumTrialActive: () => false,
}))
vi.mock('@/store/language', () => ({
  useLanguageStore: (selector: (state: object) => unknown) =>
    selector({ activeLanguage: { code: mocks.activeCode } }),
}))
vi.mock('@/store/config', () => ({
  useConfigStore: (selector: (state: object) => unknown) =>
    selector({ stripeEnabled: false }),
}))
vi.mock('@/store/freemium', () => ({
  useFreemiumStore: (selector: (state: object) => unknown) =>
    selector({
      status: null,
      fetchStatus: mocks.fetchFreemium,
      decrement: mocks.decrementFreemium,
    }),
}))
vi.mock('@/components/billing/MaintenanceBanner', () => ({
  MaintenanceGate: ({ children }: { children: ReactNode }) => children,
}))
vi.mock('@/components/billing/PaywallBanner', () => ({
  PaywallBanner: () => null,
}))
vi.mock('@/components/billing/FreemiumQuotaBanner', () => ({
  FreemiumQuotaBanner: () => null,
}))
vi.mock('@/components/ui/AudioPlayer', () => ({
  AudioPlayer: (props: object) => {
    mocks.audioPlayer(props)
    return null
  },
}))
vi.mock('@/components/ui/confirm-dialog', () => ({
  ConfirmDialog: () => null,
}))
vi.mock('@/components/ui/WordTooltip', () => ({
  WordTooltip: () => null,
  useWordSave: () => ({
    selectedWord: null,
    tooltipPos: null,
    saveState: 'idle',
    handleTextSelection: mocks.handleTextSelection,
    handleSaveWord: vi.fn(),
    dismissTooltip: mocks.dismissTooltip,
  }),
}))
vi.mock('@/components/ui/page-loading', () => ({ PageLoading: () => null }))
vi.mock('@/components/TargetLanguageText', () => ({
  TargetLanguageText: ({
    children,
    as: Component = 'div',
    languageCode,
    reading,
    translation,
    ...props
  }: {
    children: ReactNode
    as?: ElementType
    languageCode?: string | null
    reading?: string | null
    translation?: string | null
  } & HTMLAttributes<HTMLElement>) => (
    <Component
      data-language-code={languageCode ?? undefined}
      data-reading={reading ?? undefined}
      data-translation={translation ?? undefined}
      {...props}
    >
      {children}
    </Component>
  ),
}))
vi.mock('@/components/AuthAvatarImage', () => ({
  AuthAvatarImage: () => null,
}))

import ChatPage from '@/app/(app)/chat/page'
import { useHomeProfileStore } from '@/home/store/profile'

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function chatStreamResponse(events: Array<Record<string, unknown>>) {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
          )
        }
        controller.close()
      },
    }),
    { status: 200 }
  )
}

describe('chat tagged replies', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    mocks.audioPlayer.mockReset()
    mocks.activeCode = 'sv-SE'
    Element.prototype.scrollIntoView = vi.fn()
    useHomeProfileStore.setState({
      isChild: true,
      taggedLanguages: ['sv-SE'],
      loaded: true,
    })
  })

  it('hides read-aloud when replies are tagged for the plan', async () => {
    mocks.apiFetch.mockImplementation((path: string) => {
      if (path === '/api/chat/conversations') {
        return Promise.resolve(
          jsonResponse([{ id: 7, title: 'Practice', source: 'chat' }])
        )
      }
      if (path === '/api/chat/conversations/7/messages') {
        return Promise.resolve(
          jsonResponse({
            messages: [{ role: 'assistant', content: 'Bra jobbat!' }],
          })
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    render(<ChatPage />)

    expect(await screen.findByText('Bra jobbat!')).toBeInTheDocument()
    expect(mocks.audioPlayer).not.toHaveBeenCalled()
  })

  it('says Lingu is away when the backend reports no LLM', async () => {
    mocks.apiFetch.mockImplementation((path: string) => {
      if (path === '/api/chat') {
        return Promise.resolve(
          chatStreamResponse([
            { conversation_id: 7 },
            {
              error: 'The AI service is currently unavailable.',
              error_code: 'llm_unavailable',
            },
          ])
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    render(<ChatPage />)

    const input = await screen.findByPlaceholderText('placeholder')
    fireEvent.change(input, { target: { value: 'Hej' } })
    fireEvent.click(screen.getByRole('button', { name: 'send' }))

    expect(await screen.findByText(/linguAway/)).toBeInTheDocument()
  })
})
