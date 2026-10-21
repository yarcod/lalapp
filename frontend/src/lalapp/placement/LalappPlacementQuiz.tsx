'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { apiFetch } from '@/lib/api'
import AdaptiveQuizCard from '@/components/assessment/AdaptiveQuizCard'
import { PageLoading } from '@/components/ui/page-loading'
import type { AssessmentQuestion } from '@/data/types'

export interface PlacementResult {
  cefr_level: string
  score: number
  skill_profile: Record<string, number>
  strengths: string[]
  weaknesses: string[]
}

interface PlacementStep {
  session_id: string
  question_number: number
  max_questions: number
  question: Omit<AssessmentQuestion, 'correct'> | null
  result: PlacementResult | null
}

interface Props {
  language: string
  languageCode?: string | null
  onResult: (result: PlacementResult) => void
}

/**
 * Adaptive placement scored on the server. It replaces only upstream's quiz step and hands
 * its result back in upstream's AssessmentResult shape, so the result and plan steps are reused.
 */
export default function LalappPlacementQuiz({
  language,
  languageCode,
  onResult,
}: Props) {
  const tCommon = useTranslations('common')
  const [step, setStep] = useState<PlacementStep | null>(null)
  const [failed, setFailed] = useState(false)
  const pending = useRef(false)
  const lastRequest = useRef<() => Promise<Response>>(null)
  // The parent passes an inline callback; keep it out of effect dependencies so a re-render
  // never starts a new placement session.
  const onResultRef = useRef(onResult)
  useEffect(() => {
    onResultRef.current = onResult
  }, [onResult])

  const send = useCallback(async (request: () => Promise<Response>) => {
    if (pending.current) return
    pending.current = true
    lastRequest.current = request
    setFailed(false)
    try {
      const res = await request()
      if (!res.ok) throw new Error(String(res.status))
      const next = (await res.json()) as PlacementStep
      if (next.result) onResultRef.current(next.result)
      else setStep(next)
    } catch {
      setFailed(true)
    } finally {
      pending.current = false
    }
  }, [])

  useEffect(() => {
    void send(() =>
      apiFetch('/api/lalapp/placement/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language }),
      })
    )
  }, [language, send])

  function answer(chosen: string) {
    if (!step?.question) return
    const body = JSON.stringify({
      question_id: step.question.id,
      answer: chosen,
    })
    void send(() =>
      apiFetch(`/api/lalapp/placement/${step.session_id}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })
    )
  }

  if (failed) {
    return (
      <div className="mx-auto max-w-md space-y-4 p-6 text-center">
        <p role="alert" className="text-fl-muted-1">
          {tCommon('errorMessage')}
        </p>
        <button
          className="border-fl-border text-fl-fg hover:bg-fl-surface-2 border px-4 py-2 text-sm"
          onClick={() => {
            if (lastRequest.current) void send(lastRequest.current)
          }}
        >
          {tCommon('retry')}
        </button>
      </div>
    )
  }

  if (!step?.question) return <PageLoading label={tCommon('loading')} />

  return (
    <AdaptiveQuizCard
      key={step.question.id}
      question={{ ...step.question, correct: '' }}
      questionNumber={step.question_number}
      totalQuestions={step.max_questions}
      onAnswer={answer}
      languageCode={languageCode}
    />
  )
}
