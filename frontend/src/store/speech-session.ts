import { create } from 'zustand'

export const SPEECH_SESSION_STATES = [
  'off',
  'switching',
  'ready',
  'busy',
  'shared',
  'away',
] as const

export type SpeechSessionState = (typeof SPEECH_SESSION_STATES)[number]

interface SpeechSessionStore {
  state: SpeechSessionState | null
  setState: (state: SpeechSessionState | null) => void
}

export const useSpeechSessionStore = create<SpeechSessionStore>((set) => ({
  state: null,
  setState: (state) => set({ state }),
}))
