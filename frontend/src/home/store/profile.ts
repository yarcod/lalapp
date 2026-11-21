import { useEffect } from 'react'
import { create } from 'zustand'
import { apiFetch } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { useLanguageStore } from '@/store/language'

interface HomeProfile {
  is_child: boolean
  tagged_languages: string[]
}

interface HomeProfileStore {
  isChild: boolean
  taggedLanguages: string[]
  loaded: boolean
  load: () => Promise<void>
  setChild: (value: boolean) => Promise<void>
}

let inflight: Promise<void> | null = null
// The hook starts at most one automatic load at a time; a failed load clears
// the flag so the next mount retries. An explicit load() call always tries.
let autoLoadStarted = false
// Last value the server confirmed, the rollback target for a failed save.
let confirmedChild = false
let pendingSaves = 0

// The session the store content belongs to, and a counter that invalidates
// requests started under an earlier session.
let trackedVersion: number | undefined
let epoch = 0
// The learner's languages the profile was last checked against. A plan change
// (new language, new level) refreshes them, and with them tagged_languages.
const UNTRACKED = Symbol('untracked')
let trackedLanguages: unknown = UNTRACKED

export const useHomeProfileStore = create<HomeProfileStore>((set, get) => ({
  isChild: false,
  taggedLanguages: [],
  loaded: false,

  load: () => {
    if (inflight) return inflight
    const version = epoch
    inflight = (async () => {
      try {
        const res = await apiFetch('/api/home/profile')
        if (!res.ok) return
        const data: HomeProfile = await res.json()
        if (version !== epoch) return
        confirmedChild = data.is_child === true
        set({
          isChild: confirmedChild,
          taggedLanguages: data.tagged_languages ?? [],
          loaded: true,
        })
      } catch {
        // Keep the defaults: the learner is treated as not a child.
      } finally {
        if (version === epoch) inflight = null
        if (!get().loaded && version === epoch) {
          autoLoadStarted = false
        }
      }
    })()
    return inflight
  },

  setChild: async (value) => {
    const version = epoch
    if (pendingSaves++ === 0) confirmedChild = get().isChild
    set({ isChild: value })
    try {
      const res = await apiFetch('/api/home/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_child: value }),
      })
      if (!res.ok) throw new Error(`PUT /api/home/profile ${res.status}`)
      const data: HomeProfile = await res.json()
      if (version !== epoch) return
      confirmedChild = data.is_child === true
      set({
        isChild: confirmedChild,
        taggedLanguages: data.tagged_languages ?? [],
        loaded: true,
      })
    } catch (err) {
      if (version === epoch) set({ isChild: confirmedChild })
      throw err
    } finally {
      if (version === epoch) pendingSaves -= 1
    }
  },
}))

// The profile belongs to one session: a login, logout or user switch drops it,
// and responses still in flight from the old session are discarded.
function resetForNewSession(): void {
  epoch += 1
  inflight = null
  autoLoadStarted = false
  confirmedChild = false
  pendingSaves = 0
  useHomeProfileStore.setState({
    isChild: false,
    taggedLanguages: [],
    loaded: false,
  })
}

// Loads the profile the first time an enabled consumer needs it, and again when
// the learner's languages change so tagged_languages follows plan changes. The
// app layout runs it for every signed-in page (see useHomeSession).
export function useEnsureHomeProfile(enabled = true): void {
  const loaded = useHomeProfileStore((s) => s.loaded)
  const version = useAuthStore((s) => s.sessionVersion)
  const languages = useLanguageStore((s) => s.userLanguages)
  useEffect(() => {
    if (trackedVersion !== version) {
      if (trackedVersion !== undefined) resetForNewSession()
      trackedVersion = version
    }
    if (!enabled) return
    if (trackedLanguages !== languages) {
      const changed = trackedLanguages !== UNTRACKED
      trackedLanguages = languages
      if (changed && loaded) {
        void useHomeProfileStore.getState().load()
        return
      }
    }
    if (loaded || autoLoadStarted) return
    autoLoadStarted = true
    void useHomeProfileStore.getState().load()
  }, [enabled, loaded, version, languages])
}

// Tagged replies mix languages line by line, which one read-aloud voice cannot
// speak. The active language's code and the profile's tagged_languages are both
// target language codes such as "en-GB", so they compare directly. It only reads
// the store: the layout's useHomeSession loads the profile.
export function useTaggedReplies(languageCode: string | null): boolean {
  return useHomeProfileStore(
    (s) => languageCode !== null && s.taggedLanguages.includes(languageCode)
  )
}
