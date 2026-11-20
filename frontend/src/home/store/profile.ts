import { useEffect } from 'react'
import { create } from 'zustand'
import { apiFetch } from '@/lib/api'

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
// The hook starts at most one automatic load; a failed one is not retried on
// every render. An explicit load() call always tries again.
let autoLoadStarted = false

export const useHomeProfileStore = create<HomeProfileStore>((set, get) => ({
  isChild: false,
  taggedLanguages: [],
  loaded: false,

  load: () => {
    if (inflight) return inflight
    inflight = (async () => {
      try {
        const res = await apiFetch('/api/home/profile')
        if (!res.ok) return
        const data: HomeProfile = await res.json()
        set({
          isChild: data.is_child === true,
          taggedLanguages: data.tagged_languages ?? [],
          loaded: true,
        })
      } catch {
        // Keep the defaults: the learner is treated as not a child.
      } finally {
        inflight = null
      }
    })()
    return inflight
  },

  setChild: async (value) => {
    const previous = get().isChild
    set({ isChild: value })
    try {
      const res = await apiFetch('/api/home/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_child: value }),
      })
      if (!res.ok) throw new Error(`PUT /api/home/profile ${res.status}`)
      const data: HomeProfile = await res.json()
      set({
        isChild: data.is_child === true,
        taggedLanguages: data.tagged_languages ?? [],
        loaded: true,
      })
    } catch (err) {
      set({ isChild: previous })
      throw err
    }
  },
}))

// Loads the profile once, the first time any consumer needs it.
export function useEnsureHomeProfile(): void {
  const loaded = useHomeProfileStore((s) => s.loaded)
  useEffect(() => {
    if (loaded || autoLoadStarted) return
    autoLoadStarted = true
    void useHomeProfileStore.getState().load()
  }, [loaded])
}

// Tagged replies mix languages line by line, which one read-aloud voice cannot
// speak. The active language's code and the profile's tagged_languages are both
// target language codes such as "en-GB", so they compare directly.
export function useTaggedReplies(languageCode: string | null): boolean {
  useEnsureHomeProfile()
  return useHomeProfileStore(
    (s) => languageCode !== null && s.taggedLanguages.includes(languageCode)
  )
}
