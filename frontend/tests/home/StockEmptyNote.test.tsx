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

import { gameRequest } from '@/lib/detective'
import { StockEmptyNote } from '@/home/components/StockEmptyNote'
import { isStockEmpty, type GameStockEmpty } from '@/home/lib/games'

const withReplay: GameStockEmpty = {
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

const onError = vi.fn()

describe('StockEmptyNote', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the happy note and no error or paywall', () => {
    render(
      <StockEmptyNote
        empty={withReplay}
        gamePath="error-detective"
        disabled={false}
        onError={onError}
      />
    )
    expect(screen.getByRole('status')).toHaveTextContent('stockEmpty')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it('says the first games are on the way when nothing was played yet', () => {
    render(
      <StockEmptyNote
        empty={{ status: 'empty', first_games_pending: true, replayable: [] }}
        gamePath="error-detective"
        disabled={false}
        onError={onError}
      />
    )
    expect(screen.getByText('firstGamesPending')).toBeInTheDocument()
    expect(screen.queryByText('stockEmpty')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'replay' })
    ).not.toBeInTheDocument()
  })

  it('replay button posts and navigates', async () => {
    vi.mocked(gameRequest).mockResolvedValueOnce({ id: 'new-1' })
    render(
      <StockEmptyNote
        empty={withReplay}
        gamePath="error-detective"
        disabled={false}
        onError={onError}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'replay' }))
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith('/games/error-detective/new-1')
    )
    const call = vi.mocked(gameRequest).mock.calls[0]
    expect(call[0]).toBe('/sessions/old-1/replay')
    expect(call[1]?.method).toBe('POST')
  })

  it('disables replay while the catalog is busy', () => {
    render(
      <StockEmptyNote
        empty={withReplay}
        gamePath="error-detective"
        disabled
        onError={onError}
      />
    )
    expect(screen.getByRole('button', { name: 'replay' })).toBeDisabled()
  })

  it('reports busy changes and calls onError on failure', async () => {
    const onBusyChange = vi.fn()
    vi.mocked(gameRequest).mockRejectedValueOnce(new Error('boom'))
    render(
      <StockEmptyNote
        empty={withReplay}
        gamePath="error-detective"
        disabled={false}
        onBusyChange={onBusyChange}
        onError={onError}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'replay' }))
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1))
    expect(onBusyChange.mock.calls).toEqual([[true], [false]])
    expect(screen.getByRole('button', { name: 'replay' })).toBeEnabled()
    expect(push).not.toHaveBeenCalled()
  })

  it('isStockEmpty recognises only the empty payload', () => {
    expect(isStockEmpty(withReplay)).toBe(true)
    expect(isStockEmpty({ id: 'x' })).toBe(false)
    expect(isStockEmpty(null)).toBe(false)
  })
})
