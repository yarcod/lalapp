import { apiFetch } from '@/lib/api'

export interface Milestone {
  id: number
  key: string
  data: Record<string, string | number>
  created_at: string
}

export interface Rhythm {
  target_language: string
  days_per_week: number
  week_start: string
  active_days: string[]
  weeks_kept: number
  weeks_counted: number
  turns_this_week: number
  stretch_turns_this_week: number
  milestones: Milestone[]
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(String(response.status))
  return (await response.json()) as T
}

export async function fetchRhythm(): Promise<Rhythm> {
  return json(await apiFetch('/api/lalapp/rhythm'))
}

export async function setRhythmGoal(daysPerWeek: number): Promise<Rhythm> {
  return json(
    await apiFetch('/api/lalapp/rhythm', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days_per_week: daysPerWeek }),
    })
  )
}

export async function markMilestoneSeen(id: number): Promise<void> {
  const response = await apiFetch(`/api/lalapp/milestones/${id}/seen`, {
    method: 'POST',
  })
  if (!response.ok) throw new Error(String(response.status))
}
