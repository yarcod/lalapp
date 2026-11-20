// Silence after which the whole utterance so far goes to the backend provisionally.
export const PROVISIONAL_SILENCE_MS = 800

// At or below this pause the head start over the end of the turn is too short.
const PROVISIONAL_MIN_REDEMPTION_MS = 1000

export function provisionalTurnsEnabled(redemptionMs: number): boolean {
  return redemptionMs > PROVISIONAL_MIN_REDEMPTION_MS
}

export function joinAudioFrames(frames: Float32Array[]): Float32Array {
  const audio = new Float32Array(
    frames.reduce((total, frame) => total + frame.length, 0)
  )
  let offset = 0
  for (const frame of frames) {
    audio.set(frame, offset)
    offset += frame.length
  }
  return audio
}

// ─── Provisional turn control frames (client to server) ──────────────────────

export type TurnControl = 'provisional' | 'confirm' | 'abort'

export function turnControl(type: TurnControl): string {
  return JSON.stringify({ type })
}

// ─── Redo ─────────────────────────────────────────────────────────────────────

// Redo: drop what Lingu heard and everything after it, stop any reply in
// progress, and let the child speak again. The backend forgets the turn.
export function discardLastTurn(ws: WebSocket | null) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(
      JSON.stringify({ type: 'client_event', event: 'discard_last_turn' })
    )
  }
}

// Drops the latest user entry and everything after it from a transcript.
export function dropLastUserTurn<T extends { role: string }>(prev: T[]): T[] {
  const last = prev.map((e) => e.role).lastIndexOf('user')
  return last === -1 ? prev : prev.slice(0, last)
}
