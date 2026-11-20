export interface ReplayableGame {
  id: string
  mode: 'review' | 'prepare' | 'free'
  completed_at: string | null
  score: number
  total: number
  xp_earned: number
}

export interface GameStockEmpty {
  status: 'empty'
  first_games_pending: boolean
  replayable: ReplayableGame[]
}

export function isStockEmpty(value: unknown): value is GameStockEmpty {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { status?: unknown }).status === 'empty'
  )
}
