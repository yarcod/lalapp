'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { gameRequest, type DetectiveSession } from '@/lib/detective'
import type { GameStockEmpty } from '@/home/lib/games'

const button =
  'border-fl-border hover:border-fl-border-2 text-fl-fg border px-4 py-2 text-sm disabled:opacity-40'

export function StockEmptyNote({
  empty,
  gamePath,
  disabled,
  onStart,
  onBusyChange,
  onError,
}: {
  empty: GameStockEmpty
  gamePath: string
  disabled: boolean
  onStart?: () => void
  onBusyChange?: (busy: boolean) => void
  onError: () => void
}) {
  const t = useTranslations('detective')
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const operation = useRef<AbortController | null>(null)
  const pending = useRef<string | null>(null)

  useEffect(() => () => operation.current?.abort(), [])

  // On success busy and pending stay set until the page navigates away, so no
  // second replay or catalog start can begin in between.
  async function replay(id: string) {
    if (busy || disabled || pending.current) return
    const controller = new AbortController()
    operation.current?.abort()
    operation.current = controller
    pending.current = id
    setBusy(true)
    onStart?.()
    onBusyChange?.(true)
    try {
      const session = await gameRequest<Pick<DetectiveSession, 'id'>>(
        `/sessions/${id}/replay`,
        { method: 'POST', signal: controller.signal }
      )
      if (controller.signal.aborted) pending.current = null
      else router.push(`/games/${gamePath}/${session.id}`)
    } catch {
      pending.current = null
      if (controller.signal.aborted) return
      setBusy(false)
      onBusyChange?.(false)
      onError()
    }
  }

  return (
    <section
      role="status"
      className="border-fl-border bg-fl-surface space-y-3 border p-5"
    >
      <p className="text-fl-fg text-sm leading-relaxed font-semibold">
        {empty.first_games_pending ? t('firstGamesPending') : t('stockEmpty')}
      </p>
      {empty.replayable.length > 0 && (
        <div className="space-y-2">
          <p className="text-fl-muted-2 text-sm">{t('replayHeading')}</p>
          <div className="flex flex-wrap gap-2">
            {empty.replayable.map((g) => (
              <button
                key={g.id}
                className={button}
                disabled={busy || disabled}
                onClick={() => void replay(g.id)}
              >
                {t('replay', {
                  score: g.score,
                  total: g.total,
                  date: (g.completed_at ?? '').slice(0, 10),
                })}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
