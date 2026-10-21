import { apiFetch } from '@/lib/api'
import type { Persona } from '@/lalapp/personas/api'

export interface Mission {
  id: string
  goal: Record<string, string>
  done: boolean
  evidence: string | null
}

export type SceneStatus = 'locked' | 'available' | 'active' | 'done'

export interface Scene {
  id: string
  title: string
  summary: Record<string, string>
  level: string
  arc: string
  order: number
  npc: Persona
  status: SceneStatus
  conversation_id: number | null
  missions: Mission[]
}

export interface SceneList {
  target_language: string
  plan_level: string | null
  scenarios: Scene[]
}

export interface SceneRun {
  conversation_id: number
  newly_done: string[]
  scenario: Scene
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(String(response.status))
  return (await response.json()) as T
}

export async function fetchScenes(): Promise<SceneList> {
  return json(await apiFetch('/api/lalapp/scenarios'))
}

export async function startScene(id: string): Promise<SceneRun> {
  return json(
    await apiFetch(`/api/lalapp/scenarios/${encodeURIComponent(id)}/start`, {
      method: 'POST',
    })
  )
}

/** The scene played in a conversation, or null when it is an ordinary conversation. */
export async function fetchRun(
  conversationId: number
): Promise<SceneRun | null> {
  const response = await apiFetch(
    `/api/lalapp/scenarios/runs/${conversationId}`
  )
  if (response.status === 404) return null
  return json(response)
}

export async function checkRun(conversationId: number): Promise<SceneRun> {
  return json(
    await apiFetch(`/api/lalapp/scenarios/runs/${conversationId}/check`, {
      method: 'POST',
    })
  )
}

/** Chat page link that opens a specific conversation. */
export function chatHref(conversationId: number) {
  return `/chat?conversation=${conversationId}`
}

/** The conversation requested through `chatHref`, if it is among the loaded ones. */
export function requestedConversation(
  conversations: { id: number }[]
): number | null {
  if (typeof window === 'undefined') return null
  const raw = new URLSearchParams(window.location.search).get('conversation')
  const id = raw ? Number(raw) : NaN
  return conversations.some((c) => c.id === id) ? id : null
}
