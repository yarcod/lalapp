import { describe, expect, it } from 'vitest'
import {
  dropLastUserTurn,
  joinAudioFrames,
  PROVISIONAL_SILENCE_MS,
  provisionalTurnsEnabled,
  turnControl,
} from '@/home/lib/conversation'

describe('turnControl', () => {
  it.each(['provisional', 'confirm', 'abort'] as const)(
    'encodes %s as a typed control frame',
    (type) => {
      expect(JSON.parse(turnControl(type))).toEqual({ type })
    }
  )
})

describe('provisional turn helpers', () => {
  it('sends provisionally 800 ms into the silence', () => {
    expect(PROVISIONAL_SILENCE_MS).toBe(800)
  })

  it.each([
    [1000, false],
    [1001, true],
    [2000, true],
  ])('enables provisional turns for a %i ms pause: %s', (ms, enabled) => {
    expect(provisionalTurnsEnabled(ms)).toBe(enabled)
  })

  it('joins audio frames in order', () => {
    const audio = joinAudioFrames([
      Float32Array.from([1, 2]),
      Float32Array.from([3]),
    ])
    expect(Array.from(audio)).toEqual([1, 2, 3])
  })

  it('drops the latest user turn and everything after it', () => {
    const turns = [
      { role: 'user', text: 'a' },
      { role: 'assistant', text: 'b' },
      { role: 'user', text: 'c' },
      { role: 'assistant', text: 'd' },
    ]
    expect(dropLastUserTurn(turns)).toEqual(turns.slice(0, 2))
    expect(dropLastUserTurn(turns.slice(1, 2))).toEqual(turns.slice(1, 2))
  })
})
