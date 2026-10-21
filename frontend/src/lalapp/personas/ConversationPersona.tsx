'use client'

import { useEffect, useState } from 'react'
import { LALAPP_PERSONAS_ENABLED } from '@/lalapp/config'
import { useLalappT, type LalappMessageKey } from '@/lalapp/i18n'
import {
  fetchCast,
  fetchConversationPersona,
  setConversationPersona,
  type Persona,
  type PersonaCast,
} from './api'

/**
 * Shows who the learner is talking with. For an existing conversation the learner can switch
 * character; a new conversation starts with the preferred partner.
 */
export function ConversationPersona(props: { conversationId: number | null }) {
  return LALAPP_PERSONAS_ENABLED ? <PersonaSwitcher {...props} /> : null
}

function PersonaSwitcher({
  conversationId,
}: {
  conversationId: number | null
}) {
  const t = useLalappT()
  const [cast, setCast] = useState<PersonaCast | null>(null)
  const [current, setCurrent] = useState<Persona | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchCast()
      .then((data) => {
        if (!cancelled) setCast(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    if (conversationId === null) {
      setCurrent(null)
      return
    }
    fetchConversationPersona(conversationId)
      .then((persona) => {
        if (!cancelled) setCurrent(persona)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [conversationId])

  if (!cast) return null
  const shown =
    current ??
    cast.personas.find((p) => p.id === cast.preferred_peer_id) ??
    null
  if (!shown) return null

  // A role-play scene's character is fixed by the scene.
  if (conversationId === null || shown.role === 'npc') {
    return (
      <span className="text-fl-hint text-fl-muted-2 shrink-0 font-mono tracking-widest uppercase">
        {t('talkingWith', { name: shown.name })}
      </span>
    )
  }

  return (
    <select
      aria-label={t('switchCharacter')}
      value={shown.id}
      onChange={(e) =>
        void setConversationPersona(conversationId, e.target.value)
          .then(setCurrent)
          .catch(() => {})
      }
      className="bg-fl-bg border-fl-border text-fl-muted-1 hover:text-fl-fg shrink-0 appearance-none border px-2 py-1 font-mono text-xs tracking-widest uppercase focus:outline-none"
    >
      {cast.personas.map((persona) => (
        <option key={persona.id} value={persona.id}>
          {`${t('talkingWith', { name: persona.name })} (${t(`role_${persona.role}` as LalappMessageKey)})`}
        </option>
      ))}
    </select>
  )
}
