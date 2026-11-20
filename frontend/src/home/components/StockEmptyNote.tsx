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
}: {
  empty: GameStockEmpty
  gamePath: string
  disabled: boolean
}) {
  const t = useTranslations('detective')
  const common = useTranslations('common')
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const operation = useRef<AbortController | null>(null)
  const pending = useRef<string | null>(null)

  useEffect(() => () => operation.current?.abort(), [])

  async function replay(id: string) {
    if (busy || disabled || pending.current) return
    const controller = new AbortController()
    operation.current?.abort()
    operation.current = controller
    pending.current = id
    setBusy(true)
    setError('')
    try {
      const session = await gameRequest<Pick<DetectiveSession, 'id'>>(
        `/sessions/${id}/replay`,
        { method: 'POST', signal: controller.signal }
      )
      if (!controller.signal.aborted)
        router.push(`/games/${gamePath}/${session.id}`)
    } catch {
      if (controller.signal.aborted) return
      pending.current = null
      setError(common('errorMessage'))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return (
    <>
      {error && (
        <div role="alert" className="text-fl-error-fg space-y-3">
          <p>{error}</p>
        </div>
      )}
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
    </>
  )
}
