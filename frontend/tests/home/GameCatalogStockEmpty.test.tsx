import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const { push } = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('next-intl', () => {
  const translate = (key: string) => key
  return { useTranslations: () => translate }
})
vi.mock('@/lib/detective', async (original) => ({
  ...(await original<typeof import('@/lib/detective')>()),
  gameRequest: vi.fn(),
}))
vi.mock('@/components/billing/FreemiumQuotaBanner', () => ({
  FreemiumQuotaBanner: () => null,
}))
vi.mock('@/components/billing/PaywallBanner', () => ({
  PaywallBanner: () => <div>paywall</div>,
}))

import CatalogPage from '@/app/(app)/games/error-detective/page'
import { gameRequest } from '@/lib/detective'
import { useLanguageStore } from '@/store/language'
import { useFreemiumStore } from '@/store/freemium'
import { getLanguageByCode } from '@/lib/target-languages'

const catalog = {
  study_plan_id: 9,
  target_language: 'en-GB',
  level: 'A1',
  limited: false,
  quota: { remaining: 3, limit: 3 },
  total: 0,
  history: [],
  modes: {
    review: { available: false },
    prepare: { available: false },
    free: { available: true },
  },
}
const empty = {
  status: 'empty',
  first_games_pending: false,
  replayable: [
    {
      id: 'old-1',
      mode: 'free',
      completed_at: '2026-11-01T10:00:00',
      score: 4,
      total: 5,
      xp_earned: 13,
    },
  ],
}

async function showNote() {
  render(<CatalogPage />)
  fireEvent.click((await screen.findAllByRole('button', { name: 'start' }))[2])
  await screen.findByText('stockEmpty')
}

describe('GameCatalog stock-empty note', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useLanguageStore.setState({
      activeLanguage: getLanguageByCode('en-GB'),
      needsRefresh: false,
      isSwitching: false,
    })
    useFreemiumStore.setState({
      fetchStatus: vi.fn().mockResolvedValue(undefined),
    })
  })

  it('shows the note without an alert or paywall and does not navigate', async () => {
    vi.mocked(gameRequest)
      .mockResolvedValueOnce(catalog)
      .mockResolvedValueOnce(empty)
    await showNote()
    expect(screen.getByRole('status')).toHaveTextContent('stockEmpty')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('paywall')).not.toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it('blocks starts while a replay is in flight', async () => {
    let resolve!: (v: unknown) => void
    vi.mocked(gameRequest)
      .mockResolvedValueOnce(catalog)
      .mockResolvedValueOnce(empty)
      .mockReturnValueOnce(new Promise((r) => (resolve = r)))
    await showNote()
    fireEvent.click(screen.getByRole('button', { name: 'replay' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'replay' })).toBeDisabled()
    )
    for (const b of screen.getAllByRole('button', { name: 'loading' }))
      expect(b).toBeDisabled()
    resolve({ id: 'new-1' })
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith('/games/error-detective/new-1')
    )
  })

  it('shows the shared alert with retry when a replay fails', async () => {
    vi.mocked(gameRequest)
      .mockResolvedValueOnce(catalog)
      .mockResolvedValueOnce(empty)
      .mockRejectedValueOnce(new Error('boom'))
    await showNote()
    fireEvent.click(screen.getByRole('button', { name: 'replay' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('errorMessage')
    expect(screen.getByRole('button', { name: 'retry' })).toBeInTheDocument()
  })
})
