import { create } from 'zustand'

export type SpeechSessionState =
  'off' | 'switching' | 'ready' | 'busy' | 'shared' | 'away'

interface SpeechSessionStore {
  state: SpeechSessionState | null
  setState: (state: SpeechSessionState | null) => void
}

export const useSpeechSessionStore = create<SpeechSessionStore>((set) => ({
  state: null,
  setState: (state) => set({ state }),
}))
