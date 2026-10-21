'use client'

import { useEffect, useState } from 'react'
import { LALAPP_PERSONAS_ENABLED } from '@/lalapp/config'
import { useLalappT, type LalappMessageKey } from '@/lalapp/i18n'
import { choosePeer, fetchCast, type PersonaCast } from './api'

/** Settings card: pick the conversation partner for the active language. */
export function PersonaSection() {
  return LALAPP_PERSONAS_ENABLED ? <PersonaPicker /> : null
}

function PersonaPicker() {
  const t = useLalappT()
  const [cast, setCast] = useState<PersonaCast | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

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

  async function select(personaId: string) {
    if (!cast || saving || personaId === cast.preferred_peer_id) return
    setSaving(personaId)
    setFailed(false)
    try {
      setCast(await choosePeer(personaId))
    } catch {
      setFailed(true)
    } finally {
      setSaving(null)
    }
  }

  if (!cast || cast.personas.length === 0) return null
  const peers = cast.personas.filter((p) => p.role === 'peer')
  const guide = cast.personas.find((p) => p.role === 'guide')

  return (
    <div className="border-fl-border bg-fl-surface border p-6">
      <div className="border-fl-border mb-5 flex items-center gap-2 border-b pb-4">
        <span className="text-fl-label text-fl-muted-2">●</span>
        <span className="text-fl-label text-fl-muted-2 font-mono tracking-widest uppercase">
          {t('personaCardTitle')}
        </span>
      </div>
      <p className="text-fl-hint text-fl-muted-3 mb-4 font-mono">
        {t('personaHint')}
      </p>
      <div className="space-y-2" role="radiogroup">
        {peers.map((persona) => {
          const selected = persona.id === cast.preferred_peer_id
          return (
            <button
              key={persona.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={saving !== null}
              onClick={() => void select(persona.id)}
              className={`w-full border px-4 py-3 text-left transition-colors disabled:opacity-60 ${
                selected
                  ? 'border-fl-border-2 bg-fl-surface-2 text-fl-fg'
                  : 'border-fl-border text-fl-muted-1 hover:border-fl-border-2 hover:text-fl-fg'
              }`}
            >
              <span className="block font-mono text-sm tracking-widest uppercase">
                {persona.name} ·{' '}
                {t(`dialect_${persona.dialect}` as LalappMessageKey)} ·{' '}
                {t('age', { age: persona.age })}
              </span>
              <span className="text-fl-hint text-fl-muted-3 mt-1 block">
                {persona.backstory}
              </span>
            </button>
          )
        })}
      </div>
      {guide && (
        <p className="text-fl-hint text-fl-muted-3 mt-4 font-mono">
          {t('personaGuideNote', { name: guide.name })}
        </p>
      )}
      {failed && (
        <p role="alert" className="text-fl-error mt-3 text-sm">
          {t('saveError')}
        </p>
      )}
    </div>
  )
}
