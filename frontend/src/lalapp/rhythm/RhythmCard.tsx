'use client'

import { useEffect, useState } from 'react'
import { useLocale } from 'next-intl'
import { LALAPP_RHYTHM_ENABLED } from '@/lalapp/config'
import { useLalappT, type LalappMessageKey } from '@/lalapp/i18n'
import { useLanguageStore } from '@/store/language'
import {
  fetchRhythm,
  markMilestoneSeen,
  setRhythmGoal,
  type Milestone,
  type Rhythm,
} from './api'

/**
 * Dashboard card: this week against the learner's own goal, without a streak to lose, plus
 * informational milestones that are shown once.
 */
export function RhythmCard() {
  return LALAPP_RHYTHM_ENABLED ? <Card /> : null
}

function addDays(iso: string, days: number) {
  const day = new Date(`${iso}T00:00:00Z`)
  day.setUTCDate(day.getUTCDate() + days)
  return day.toISOString().slice(0, 10)
}

function Card() {
  const t = useLalappT()
  const locale = useLocale()
  const languageCode = useLanguageStore((s) => s.activeLanguage?.code)
  const [rhythm, setRhythm] = useState<Rhythm | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    setRhythm(null)
    fetchRhythm()
      .then((data) => {
        if (!cancelled) setRhythm(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [languageCode])

  async function changeGoal(days: number) {
    setSaving(true)
    try {
      setRhythm(await setRhythmGoal(days))
    } catch {
      /* the previous goal stays shown */
    } finally {
      setSaving(false)
    }
  }

  function dismiss(milestone: Milestone) {
    setRhythm((current) =>
      current
        ? {
            ...current,
            milestones: current.milestones.filter((m) => m.id !== milestone.id),
          }
        : current
    )
    void markMilestoneSeen(milestone.id).catch(() => {})
  }

  function milestoneText(milestone: Milestone) {
    const kind = milestone.key.split(':')[0]
    const data = { ...milestone.data }
    if (kind === 'skill_level' && typeof data.skill === 'string') {
      data.skill = t(`skill_${data.skill}` as LalappMessageKey)
    }
    return t(`milestone_${kind}` as LalappMessageKey, data)
  }

  if (!rhythm) return null
  const week = Array.from({ length: 7 }, (_, i) =>
    addDays(rhythm.week_start, i)
  )
  const weekday = new Intl.DateTimeFormat(locale, {
    weekday: 'narrow',
    timeZone: 'UTC',
  })
  const done = rhythm.active_days.length

  return (
    <div className="bg-fl-surface p-5 sm:col-span-2">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-fl-label text-fl-muted-2">●</span>
          <span className="text-fl-label text-fl-muted-2 font-mono tracking-widest uppercase">
            {t('rhythmTitle')}
          </span>
        </div>
        <label className="text-fl-hint text-fl-muted-2 flex items-center gap-2 font-mono tracking-widest uppercase">
          {t('rhythmGoalLabel')}
          <select
            value={rhythm.days_per_week}
            disabled={saving}
            onChange={(e) => void changeGoal(Number(e.target.value))}
            className="bg-fl-bg border-fl-border text-fl-fg border px-2 py-1 font-mono text-xs"
          >
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      <ol
        className="flex gap-2"
        aria-label={t('rhythmThisWeek', { done, goal: rhythm.days_per_week })}
      >
        {week.map((day) => {
          const active = rhythm.active_days.includes(day)
          return (
            <li
              key={day}
              className={`flex size-8 items-center justify-center border font-mono text-xs ${
                active
                  ? 'bg-fl-fg text-fl-bg border-fl-fg'
                  : 'border-fl-border text-fl-muted-3'
              }`}
            >
              {weekday.format(new Date(`${day}T00:00:00Z`))}
            </li>
          )
        })}
      </ol>
      <p className="text-fl-fg mt-3 font-mono text-sm">
        {t('rhythmThisWeek', { done, goal: rhythm.days_per_week })}
        {done >= rhythm.days_per_week && (
          <span className="text-fl-muted-2"> · {t('rhythmMet')}</span>
        )}
      </p>
      <p className="text-fl-muted-2 mt-1 font-mono text-xs">
        {t('rhythmKept', {
          kept: rhythm.weeks_kept,
          weeks: rhythm.weeks_counted,
        })}
      </p>
      <p className="text-fl-muted-2 mt-1 font-mono text-xs">
        {t('rhythmTurns', { turns: rhythm.turns_this_week })}
        {rhythm.stretch_turns_this_week > 0 &&
          ` · ${t('rhythmStretch', { count: rhythm.stretch_turns_this_week })}`}
      </p>

      {rhythm.milestones.length > 0 && (
        <ul className="border-fl-border mt-4 space-y-2 border-t pt-4">
          {rhythm.milestones.map((milestone) => (
            <li
              key={milestone.id}
              className="flex flex-wrap items-center justify-between gap-2"
            >
              <span className="text-fl-fg font-mono text-sm">
                {milestoneText(milestone)}
              </span>
              <button
                type="button"
                onClick={() => dismiss(milestone)}
                className="text-fl-hint text-fl-muted-2 hover:text-fl-fg font-mono tracking-widest uppercase"
              >
                {t('dismiss')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
