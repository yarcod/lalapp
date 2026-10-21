'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useLocale } from 'next-intl'
import { Check } from 'lucide-react'
import { LALAPP_SCENARIOS_ENABLED } from '@/lalapp/config'
import { localized, useLalappT } from '@/lalapp/i18n'
import { checkRun, fetchRun, type SceneRun } from './api'

interface Props {
  conversationId: number | null
  // True while the partner is replying; a finished reply triggers a mission check.
  busy: boolean
}

/** Chat strip for a role-play conversation: the learner's goals and their progress. */
export function ScenarioPanel(props: Props) {
  return LALAPP_SCENARIOS_ENABLED ? <Panel {...props} /> : null
}

function Panel({ conversationId, busy }: Props) {
  const t = useLalappT()
  const locale = useLocale()
  const [run, setRun] = useState<SceneRun | null>(null)
  const [reached, setReached] = useState<string[]>([])
  const [failed, setFailed] = useState(false)
  const wasBusy = useRef(busy)

  useEffect(() => {
    let cancelled = false
    setRun(null)
    setReached([])
    setFailed(false)
    if (conversationId === null) return
    fetchRun(conversationId)
      .then((data) => {
        if (!cancelled) setRun(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [conversationId])

  useEffect(() => {
    const replyFinished = wasBusy.current && !busy
    wasBusy.current = busy
    if (!replyFinished || !run || run.scenario.status !== 'active') return
    let cancelled = false
    checkRun(run.conversation_id)
      .then((data) => {
        if (cancelled) return
        setRun(data)
        setFailed(false)
        if (data.newly_done.length > 0) setReached(data.newly_done)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [busy, run])

  if (!run || run.conversation_id !== conversationId) return null
  const scene = run.scenario
  const goal = (id: string) =>
    localized(scene.missions.find((m) => m.id === id)?.goal ?? {}, locale)

  return (
    <div className="border-fl-border bg-fl-surface shrink-0 border-b px-5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-fl-hint text-fl-muted-2 font-mono tracking-widest uppercase">
          {t('missionsTitle')}
        </span>
        {scene.status === 'done' && (
          <span className="text-fl-hint text-fl-fg font-mono tracking-widest uppercase">
            {t('sceneComplete')}{' '}
            <Link href="/scenarios" className="underline">
              {t('moreScenes')}
            </Link>
          </span>
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        {scene.missions.map((mission) => (
          <li
            key={mission.id}
            className={`flex items-center gap-1.5 font-mono text-xs ${mission.done ? 'text-fl-fg' : 'text-fl-muted-2'}`}
          >
            {mission.done ? (
              <Check className="size-3.5" aria-hidden="true" />
            ) : (
              <span aria-hidden="true">○</span>
            )}
            {localized(mission.goal, locale)}
          </li>
        ))}
      </ul>
      <p
        className="text-fl-hint text-fl-muted-1 mt-1 font-mono"
        aria-live="polite"
      >
        {reached
          .map((id) => t('missionReached', { goal: goal(id) }))
          .join(' · ')}
      </p>
      {failed && (
        <p className="text-fl-hint text-fl-muted-3 font-mono">
          {t('missionCheckFailed')}
        </p>
      )}
    </div>
  )
}
