import { beforeEach } from 'vitest'
import { useSpeechSessionStore } from '@/home/store/speech-session'

// Upstream tests start voice sessions without a speech gateway: open it for them.
beforeEach(() => {
  useSpeechSessionStore.setState({ state: 'ready' })
})
