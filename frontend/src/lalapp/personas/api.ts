import { apiFetch } from '@/lib/api'

export interface Persona {
  id: string
  name: string
  role: 'guide' | 'peer' | 'examiner'
  dialect: string
  age: number
  backstory: string
  personality: string[]
}

export interface PersonaCast {
  target_language: string
  preferred_peer_id: string | null
  personas: Persona[]
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(String(response.status))
  return (await response.json()) as T
}

export async function fetchCast(): Promise<PersonaCast> {
  return json(await apiFetch('/api/lalapp/personas'))
}

export async function choosePeer(personaId: string): Promise<PersonaCast> {
  return json(
    await apiFetch('/api/lalapp/personas/peer', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona_id: personaId }),
    })
  )
}

export async function fetchConversationPersona(
  conversationId: number
): Promise<Persona> {
  return json(
    await apiFetch(`/api/lalapp/conversations/${conversationId}/persona`)
  )
}

export async function setConversationPersona(
  conversationId: number,
  personaId: string
): Promise<Persona> {
  return json(
    await apiFetch(`/api/lalapp/conversations/${conversationId}/persona`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona_id: personaId }),
    })
  )
}
