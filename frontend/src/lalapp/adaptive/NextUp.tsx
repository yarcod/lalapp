'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { LALAPP_ADAPTIVE_ENABLED } from '@/lalapp/config'
import { useLalappT, type LalappMessageKey } from '@/lalapp/i18n'
import { useLanguageStore } from '@/store/language'
import {
  createNextLesson,
  fetchNextUp,
  startNextLevel,
  type NextUp,
} from './api'

const primaryButton =
  'text-fl-bg bg-fl-fg hover:bg-fl-fg/90 focus-visible:outline-fl-fg px-4 py-2 font-mono text-sm font-bold tracking-widest uppercase transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60'
const secondaryButton =
  'text-fl-fg border-fl-border hover:border-fl-border-2 border px-4 py-2 font-mono text-sm tracking-widest uppercase transition-colors disabled:opacity-60'

/** Dashboard card: the lesson the learner model suggests next, and level-up when earned. */
export function LalappNextUp() {
  return LALAPP_ADAPTIVE_ENABLED ? <NextUpCard /> : null
}

function humanize(slug: string) {
  return slug.replace(/-/g, ' ')
}

function NextUpCard() {
  const t = useLalappT()
  const router = useRouter()
  const languageCode = useLanguageStore((s) => s.activeLanguage?.code)
  const [next, setNext] = useState<NextUp | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<'lesson' | 'level' | null>(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let cancelled = false
    setNext(null)
    fetchNextUp()
      .then((data) => {
        if (!cancelled) setNext(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [languageCode])

  async function create() {
    setBusy(true)
    setFailed(null)
    try {
      const data = await createNextLesson()
      setNext(data)
      if (data.lesson) router.push(`/lesson/${data.lesson.id}`)
    } catch {
      setFailed('lesson')
    } finally {
      setBusy(false)
    }
  }

  async function levelUp() {
    if (!next?.level_up) return
    setBusy(true)
    setFailed(null)
    try {
      await startNextLevel(next.level_up)
      router.push('/plan')
    } catch {
      setFailed('level')
      setBusy(false)
    }
  }

  if (!next) return null
  const lesson = next.lesson
  const skill = t(
    `skill_${lesson?.lesson_type ?? next.skill}` as LalappMessageKey
  )
  const reason = lesson?.reason ?? next.reason
  const focus = (lesson?.focus ?? next.focus).map(humanize).join(', ')
  const nextLevel = next.level_up?.next_level

  return (
    <div className="bg-fl-surface p-5 sm:col-span-2">
      <div className="mb-4 flex items-center gap-2">
        <span className="text-fl-label text-fl-muted-2">●</span>
        <span className="text-fl-label text-fl-muted-2 font-mono tracking-widest uppercase">
          {t('nextUpTitle')}
        </span>
      </div>

      {nextLevel && (
        <div className="border-fl-border mb-5 border-b pb-5">
          <h2 className="text-fl-fg font-mono text-xl font-bold tracking-tight">
            {t('levelUpTitle', { level: nextLevel })}
          </h2>
          <p className="text-fl-muted-2 mt-2 font-mono text-sm">
            {confirming
              ? t('levelUpConfirm', { level: nextLevel })
              : t('levelUpDesc')}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {confirming ? (
              <>
                <button
                  type="button"
                  className={primaryButton}
                  disabled={busy}
                  onClick={() => void levelUp()}
                >
                  {t('levelUpYes', { level: nextLevel })}
                </button>
                <button
                  type="button"
                  className={secondaryButton}
                  disabled={busy}
                  onClick={() => setConfirming(false)}
                >
                  {t('cancel')}
                </button>
              </>
            ) : (
              <button
                type="button"
                className={secondaryButton}
                onClick={() => setConfirming(true)}
              >
                {t('levelUpAction', { level: nextLevel })}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h3 className="text-fl-fg font-mono text-lg font-bold tracking-tight">
            {lesson ? lesson.title : (next.unit_title ?? skill)}
          </h3>
          <p className="text-fl-muted-2 mt-1 font-mono text-sm">
            {t(`nextUpReason_${reason}` as LalappMessageKey, {
              skill,
              focus,
              unit: next.unit_title ?? '',
            })}
          </p>
          <p className="text-fl-hint text-fl-muted-3 mt-1 font-mono tracking-widest uppercase">
            {t('nextUpExpected', {
              level: lesson?.cefr_level ?? next.cefr_level,
              percent: Math.round(
                (lesson?.predicted_success ?? next.predicted_success) * 100
              ),
            })}
          </p>
        </div>
        {lesson ? (
          <Link href={`/lesson/${lesson.id}`} className={primaryButton}>
            {t('nextUpStart')}
          </Link>
        ) : (
          <button
            type="button"
            className={primaryButton}
            disabled={busy}
            onClick={() => void create()}
          >
            {busy ? t('nextUpCreating') : t('nextUpCreate')}
          </button>
        )}
      </div>
      {failed && (
        <p className="text-fl-error mt-3 font-mono text-xs" role="alert">
          {t(failed === 'lesson' ? 'nextUpFailed' : 'saveError')}
        </p>
      )}
    </div>
  )
}
