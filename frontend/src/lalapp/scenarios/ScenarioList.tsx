'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useLocale } from 'next-intl'
import { Check, Lock } from 'lucide-react'
import { LALAPP_SCENARIOS_ENABLED } from '@/lalapp/config'
import { localized, useLalappT, type LalappMessageKey } from '@/lalapp/i18n'
import { useLanguageStore } from '@/store/language'
import {
  chatHref,
  fetchScenes,
  startScene,
  type Scene,
  type SceneList,
} from './api'

const primaryButton =
  'text-fl-bg bg-fl-fg hover:bg-fl-fg/90 focus-visible:outline-fl-fg px-3 py-1 font-mono text-sm tracking-widest uppercase transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60'
const secondaryButton =
  'text-fl-fg border-fl-border hover:border-fl-border-2 border px-3 py-1 font-mono text-sm tracking-widest uppercase transition-colors disabled:opacity-60'

/** The role-play page: scenes grouped by story, with lock state and goals. */
export function ScenarioList() {
  return LALAPP_SCENARIOS_ENABLED ? <Scenes /> : null
}

function Scenes() {
  const t = useLalappT()
  const locale = useLocale()
  const router = useRouter()
  const languageCode = useLanguageStore((s) => s.activeLanguage?.code)
  const [list, setList] = useState<SceneList | null>(null)
  const [starting, setStarting] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchScenes()
      .then((data) => {
        if (!cancelled) setList(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [languageCode])

  async function start(scene: Scene) {
    setStarting(scene.id)
    setFailed(false)
    try {
      const run = await startScene(scene.id)
      router.push(chatHref(run.conversation_id))
    } catch {
      setFailed(true)
      setStarting(null)
    }
  }

  const arcs: [string, Scene[]][] = []
  for (const scene of list?.scenarios ?? []) {
    const group = arcs.find(([arc]) => arc === scene.arc)
    if (group) group[1].push(scene)
    else arcs.push([scene.arc, [scene]])
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="border-fl-border bg-fl-surface border px-6 py-4">
        <h1 className="text-fl-label text-fl-muted-2 font-mono tracking-widest uppercase">
          {t('navScenarios')}
        </h1>
        <p className="text-fl-muted-2 mt-2 font-mono text-sm">
          {t('scenariosIntro')}
        </p>
        {failed && (
          <p className="text-fl-error mt-2 font-mono text-xs" role="alert">
            {t('scenarioStartFailed')}
          </p>
        )}
      </div>

      {arcs.map(([arc, scenes]) => (
        <section
          key={arc}
          className="border-fl-border bg-fl-surface border"
          aria-label={t(`arc_${arc}` as LalappMessageKey)}
        >
          <h2 className="border-fl-border text-fl-label text-fl-muted-2 border-b px-6 py-3 font-mono tracking-widest uppercase">
            {t(`arc_${arc}` as LalappMessageKey)}
          </h2>
          <ol className="divide-fl-border divide-y">
            {scenes.map((scene) => (
              <li key={scene.id} className="space-y-2 px-6 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-fl-fg font-mono text-sm font-bold">
                      {scene.status === 'locked' && (
                        <Lock
                          className="mr-1 inline size-3.5"
                          aria-hidden="true"
                        />
                      )}
                      {scene.title}
                    </p>
                    <p className="text-fl-muted-2 mt-1 font-mono text-xs">
                      {localized(scene.summary, locale)}
                    </p>
                    <p className="text-fl-hint text-fl-muted-3 mt-1 font-mono tracking-widest uppercase">
                      {t('talkingWith', { name: scene.npc.name })} ·{' '}
                      {t('scenarioLevel', { level: scene.level })}
                    </p>
                  </div>
                  <SceneAction
                    scene={scene}
                    busy={starting !== null}
                    onStart={() => void start(scene)}
                  />
                </div>
                {scene.status !== 'locked' && (
                  <ul className="space-y-1">
                    {scene.missions.map((mission) => (
                      <li
                        key={mission.id}
                        className={`flex items-center gap-2 font-mono text-xs ${mission.done ? 'text-fl-fg' : 'text-fl-muted-2'}`}
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
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  )
}

function SceneAction({
  scene,
  busy,
  onStart,
}: {
  scene: Scene
  busy: boolean
  onStart: () => void
}) {
  const t = useLalappT()
  if (scene.status === 'locked') {
    return (
      <span className="text-fl-hint text-fl-muted-3 font-mono tracking-widest uppercase">
        {t('scenarioLocked')}
      </span>
    )
  }
  if (scene.status === 'active' && scene.conversation_id !== null) {
    return (
      <Link href={chatHref(scene.conversation_id)} className={primaryButton}>
        {t('scenarioContinue')}
      </Link>
    )
  }
  return (
    <div className="flex items-center gap-3">
      {scene.status === 'done' && (
        <span className="text-fl-hint text-fl-muted-2 font-mono tracking-widest uppercase">
          {t('scenarioDone')}
        </span>
      )}
      <button
        type="button"
        className={scene.status === 'done' ? secondaryButton : primaryButton}
        disabled={busy}
        onClick={onStart}
      >
        {scene.status === 'done' ? t('scenarioReplay') : t('scenarioStart')}
      </button>
    </div>
  )
}
