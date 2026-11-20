import { useEffect, useMemo, useRef, type RefObject } from 'react'
import { float32ToWav } from '@/lib/audio'
import { resolveVadRedemptionMs } from '@/lib/conversation-vad'
import {
  joinAudioFrames,
  PROVISIONAL_SILENCE_MS,
  provisionalTurnsEnabled,
  turnControl,
} from '@/home/lib/conversation'

// Mirrors ConversationMode's VAD_POSITIVE_SPEECH_THRESHOLD.
const VAD_POSITIVE_SPEECH_THRESHOLD = 0.3
// The VAD's own defaults, mirrored so the provisional window follows its silence.
const VAD_NEGATIVE_SPEECH_THRESHOLD = 0.25
const VAD_PRE_SPEECH_PAD_MS = 800
const VAD_SAMPLE_RATE = 16000

export interface ProvisionalTurnOptions {
  wsRef: RefObject<WebSocket | null>
  speechPause: number | null | undefined
  cefrLevel: string | null | undefined
  speechStartedAtRef: RefObject<number | null>
  assistantTurnActiveRef: RefObject<boolean>
  assistantSpeakingRef: RefObject<boolean>
  isLikelySpeech: (audio: Float32Array) => { isSpeech: boolean }
  logger: { info: (message: string, payload?: unknown) => void }
}

// What the speech end means for audio already sent provisionally: none was
// sent (null), the pause only confirms it, or quiet speech followed it and the
// full turn replaces it.
export type ProvisionalTurnEnd = 'confirm' | 'replace' | null

export interface ProvisionalTurn {
  onFrame(frame: Float32Array, isSpeech: number): void
  onSpeechEnd(isSpeech: boolean): ProvisionalTurnEnd
  settle(end: ProvisionalTurnEnd): 'sent' | 'failed' | 'closed' | null
  abort(): void
  reset(): void
  forget(): void
}

/**
 * Sends the utterance so far after PROVISIONAL_SILENCE_MS of silence, so the
 * backend can start before the VAD ends the turn. Further speech aborts it; the
 * end of the turn confirms or replaces it. Only used when the user's pause is
 * long enough (provisionalTurnsEnabled).
 */
export function useProvisionalTurn(
  options: ProvisionalTurnOptions
): ProvisionalTurn {
  const optionsRef = useRef(options)
  useEffect(() => {
    optionsRef.current = options
  })
  // The browser's own copy of the utterance, for sending it before the VAD ends it.
  const utteranceFramesRef = useRef<Float32Array[]>([])
  const silenceMsRef = useRef(0)
  const provisionalSentRef = useRef(false)
  const provisionalTailRef = useRef(false)

  return useMemo(() => {
    const resetProvisional = () => {
      utteranceFramesRef.current = []
      silenceMsRef.current = 0
      provisionalSentRef.current = false
      provisionalTailRef.current = false
    }

    const abortProvisional = () => {
      if (!provisionalSentRef.current) return
      provisionalSentRef.current = false
      provisionalTailRef.current = false
      const ws = optionsRef.current.wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(turnControl('abort'))
      }
    }

    const sendProvisional = () => {
      const { wsRef, assistantTurnActiveRef, assistantSpeakingRef } =
        optionsRef.current
      const ws = wsRef.current
      if (
        !ws ||
        ws.readyState !== WebSocket.OPEN ||
        assistantTurnActiveRef.current ||
        assistantSpeakingRef.current
      )
        return
      const audio = joinAudioFrames(utteranceFramesRef.current)
      if (!optionsRef.current.isLikelySpeech(audio).isSpeech) return
      try {
        ws.send(turnControl('provisional'))
        ws.send(float32ToWav(audio, VAD_SAMPLE_RATE))
        provisionalSentRef.current = true
        optionsRef.current.logger.info('sent provisional utterance', {
          samples: audio.length,
        })
      } catch {
        provisionalSentRef.current = false
      }
    }

    const trackProvisionalWindow = (speech: number, frame: Float32Array) => {
      const frames = utteranceFramesRef.current
      frames.push(frame)
      if (optionsRef.current.speechStartedAtRef.current === null) {
        // Before speech starts, keep only the VAD's pre-speech padding.
        const frameMs = (frame.length / VAD_SAMPLE_RATE) * 1000
        const padFrames = Math.floor(VAD_PRE_SPEECH_PAD_MS / frameMs)
        if (speech < VAD_POSITIVE_SPEECH_THRESHOLD) {
          while (frames.length > padFrames) frames.shift()
        }
        return
      }
      if (speech >= VAD_POSITIVE_SPEECH_THRESHOLD) {
        silenceMsRef.current = 0
        abortProvisional()
        return
      }
      if (speech >= VAD_NEGATIVE_SPEECH_THRESHOLD) {
        // Below the speech threshold but not silence: a quiet trailing word the
        // provisional audio does not contain.
        if (provisionalSentRef.current) provisionalTailRef.current = true
        return
      }
      const before = silenceMsRef.current
      const after = before + (frame.length / VAD_SAMPLE_RATE) * 1000
      silenceMsRef.current = after
      const { speechPause, cefrLevel } = optionsRef.current
      if (
        before < PROVISIONAL_SILENCE_MS &&
        after >= PROVISIONAL_SILENCE_MS &&
        provisionalTurnsEnabled(resolveVadRedemptionMs(speechPause, cefrLevel))
      ) {
        sendProvisional()
      }
    }

    return {
      // Every VAD frame while the session is active.
      onFrame: (frame, isSpeech) => trackProvisionalWindow(isSpeech, frame),
      // At the VAD's speech end, before acting on the utterance.
      onSpeechEnd: (isSpeech) => {
        const provisionalSent = provisionalSentRef.current
        const provisionalHasTail = provisionalTailRef.current
        if (!isSpeech) abortProvisional()
        resetProvisional()
        if (!isSpeech || !provisionalSent) return null
        return provisionalHasTail ? 'replace' : 'confirm'
      },
      // Once the turn is accepted: acts on audio already sent provisionally.
      // Returns null when the caller still has to send the full turn.
      settle: (end) => {
        const { wsRef, assistantTurnActiveRef } = optionsRef.current
        const ws = wsRef.current
        if (end === 'replace') {
          // Quiet speech followed it: drop the shorter audio and send the full turn.
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(turnControl('abort'))
          }
          return null
        }
        if (end !== 'confirm') return null
        // The audio already went out provisionally, so the pause only confirms it.
        if (!ws || ws.readyState !== WebSocket.OPEN) return 'closed'
        assistantTurnActiveRef.current = true
        try {
          ws.send(turnControl('confirm'))
          return 'sent'
        } catch {
          assistantTurnActiveRef.current = false
          return 'failed'
        }
      },
      // The VAD discarded the speech.
      abort: () => {
        abortProvisional()
        resetProvisional()
      },
      reset: resetProvisional,
      // Redo: the backend forgets the turn, so nothing is left to confirm.
      forget: () => {
        provisionalSentRef.current = false
      },
    }
  }, [])
}
