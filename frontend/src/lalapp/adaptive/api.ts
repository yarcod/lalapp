import { apiFetch } from '@/lib/api'

export interface NextLesson {
  id: number
  title: string
  lesson_type: string
  cefr_level: string
  reason: string
  focus: string[]
  predicted_success: number
}

export interface LevelUp {
  next_level: string
  goals: string[]
  duration_weeks: number
  days_per_week: number
  target_language: string
}

export interface NextUp {
  plan_id: number
  skill: string
  cefr_level: string
  reason: 'practice' | 'review' | 'preview'
  focus: string[]
  unit_title: string | null
  predicted_success: number
  lesson: NextLesson | null
  level_up: LevelUp | null
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(String(response.status))
  return (await response.json()) as T
}

export async function fetchNextUp(): Promise<NextUp | null> {
  return json(await apiFetch('/api/lalapp/next'))
}

export async function createNextLesson(): Promise<NextUp> {
  return json(await apiFetch('/api/lalapp/next', { method: 'POST' }))
}

/** Start the next level with upstream's own plan generator, keeping the current schedule. */
export async function startNextLevel(levelUp: LevelUp): Promise<void> {
  await json(
    await apiFetch('/api/study-plan/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cefr_level: levelUp.next_level,
        goals: levelUp.goals,
        duration_weeks: levelUp.duration_weeks,
        days_per_week: levelUp.days_per_week,
        target_language: levelUp.target_language,
      }),
    })
  )
}
