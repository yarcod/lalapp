import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { useMicVAD } from '@ricky0123/vad-react'
import {
  defaultFrameProcessorOptions,
  FrameProcessor,
  type FrameProcessorEvent,
} from '@ricky0123/vad-web/dist/frame-processor'
import { Message } from '@ricky0123/vad-web/dist/messages'

const mocks = vi.hoisted(() => ({
  options: {} as Parameters<typeof useMicVAD>[0],
  start: vi.fn(),
  pause: vi.fn(),
  getUserMedia: vi.fn(),
  apiFetch: vi.fn(),
  enqueue: vi.fn(),
  cancel: vi.fn(),
  closeAudio: vi.fn(),
  onAudioIdle: null as (() => void) | null,
  starters: [] as string[],
}))

vi.mock('@ricky0123/vad-react', () => ({
  useMicVAD: (options: Parameters<typeof useMicVAD>[0]) => {
    mocks.options = options
    return {
      loading: false,
      errored: false,
      start: mocks.start,
      pause: mocks.pause,
    }
  },
}))
vi.mock('next-intl', async (importOriginal) => {
  const { createTranslator } =
    await importOriginal<typeof import('next-intl')>()
  const { default: messages } = await import('../../../messages/en.json')
  const practice = createTranslator({
    locale: 'en',
    messages,
    namespace: 'lessonPractice',
  })
  return {
    useLocale: () => 'en',
    useTranslations: () =>
      Object.assign(
        (key: string, values?: { seconds?: number }) => {
          if (key === 'warningTimeout') return `${key}:${values?.seconds}`
          return key
        },
        {
          raw: () => mocks.starters,
          rich: practice.rich,
        }
      ),
  }
})
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('@/lib/audio', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/audio')>()),
  createAudioQueue: (_ctx: AudioContext, onIdle?: () => void) => {
    mocks.onAudioIdle = onIdle ?? null
    return { enqueue: mocks.enqueue, cancel: mocks.cancel }
  },
}))
vi.mock('@/components/reviews/ReviewPrompt', () => ({
  ReviewPrompt: () => null,
  getReviewPromptDismissal: () => null,
}))
vi.mock('@/lib/review-prompt-triggers', () => ({
  shouldShowVoiceReviewPrompt: () => false,
}))
vi.mock('@/components/conversation/StatusIndicator', async (importOriginal) => {
  const { default: StatusIndicator } =
    await importOriginal<
      typeof import('@/components/conversation/StatusIndicator')
    >()
  return {
    default: (props: Parameters<typeof StatusIndicator>[0]) => (
      <>
        <div data-testid="speaking">{String(props.userSpeaking)}</div>
        <StatusIndicator {...props} />
      </>
    ),
  }
})

import ConversationMode from '@/components/conversation/ConversationMode'
import { useAuthStore } from '@/store/auth'
import { useSpeechSessionStore } from '@/home/store/speech-session'
import { mapUser } from '@/lib/mappers'

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []
  readyState = 1
  binaryType = ''
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number; reason: string }) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3
  })

  constructor() {
    MockWebSocket.instances.push(this)
  }

  message(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

function microphone() {
  const stop = vi.fn()
  return {
    stream: { getTracks: () => [{ stop }] } as unknown as MediaStream,
    stop,
  }
}

async function start(label = 'start') {
  const count = MockWebSocket.instances.length
  fireEvent.click(screen.getByRole('button', { name: label }))
  await waitFor(() => expect(MockWebSocket.instances).toHaveLength(count + 1))
  const ws = MockWebSocket.instances[count]
  act(() => ws.onopen?.())
  ws.send.mockClear()
  return ws
}

function speak(audio = new Float32Array(24000).fill(0.05)) {
  mocks.options.onFrameProcessed?.({ isSpeech: 0.99, notSpeech: 0.01 }, audio)
  mocks.options.onSpeechStart?.()
  mocks.options.onSpeechEnd?.(audio)
}

beforeEach(() => {
  vi.clearAllMocks()
  MockWebSocket.instances = []
  mocks.starters = []
  mocks.onAudioIdle = null
  mocks.getUserMedia.mockReset().mockResolvedValue(microphone().stream)
  mocks.start.mockImplementation(async () => {
    await mocks.options.getStream?.()
  })
  mocks.pause.mockResolvedValue(undefined)
  mocks.closeAudio.mockResolvedValue(undefined)
  mocks.enqueue.mockResolvedValue(undefined)
  mocks.apiFetch.mockResolvedValue({ ok: true, json: async () => null })
  vi.stubGlobal('WebSocket', MockWebSocket)
  vi.stubGlobal(
    'AudioContext',
    class {
      state = 'running'
      close = mocks.closeAudio
    }
  )
  vi.stubGlobal('navigator', {
    mediaDevices: { getUserMedia: mocks.getUserMedia },
  })
  Element.prototype.scrollIntoView = vi.fn()
  useAuthStore.setState({ accessToken: 'token', user: null })
  useSpeechSessionStore.setState({ state: 'ready' })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const voiceFrame = new Float32Array(512).fill(0.05)
const quietFrame = new Float32Array(512).fill(0.04)
const silenceFrame = new Float32Array(512)

function vadProcessor() {
  const processor = new FrameProcessor(
    async (frame) => {
      const isSpeech =
        frame === voiceFrame ? 0.99 : frame === quietFrame ? 0.27 : 0.01
      return { isSpeech, notSpeech: 1 - isSpeech }
    },
    () => {},
    {
      ...defaultFrameProcessorOptions,
      positiveSpeechThreshold: mocks.options.positiveSpeechThreshold!,
      redemptionMs: mocks.options.redemptionMs!,
    },
    32
  )
  processor.resume()
  const handleEvent = (event: FrameProcessorEvent) => {
    if (event.msg === Message.FrameProcessed) {
      mocks.options.onFrameProcessed?.(event.probs, event.frame)
    }
    if (event.msg === Message.SpeechStart) mocks.options.onSpeechStart?.()
    if (event.msg === Message.VADMisfire) mocks.options.onVADMisfire?.()
    if (event.msg === Message.SpeechEnd) {
      mocks.options.onSpeechEnd?.(event.audio)
    }
  }
  return async (frames: Float32Array, count: number) => {
    await act(async () => {
      for (let i = 0; i < count; i++) {
        await processor.process(frames, handleEvent)
      }
    })
  }
}

function sentKinds(ws: MockWebSocket) {
  return ws.send.mock.calls.map(([sent]) =>
    typeof sent === 'string' ? JSON.parse(sent).type : 'wav'
  )
}

function renderWithPause(speechPause: number) {
  useAuthStore.setState({
    user: mapUser({
      id: 1,
      username: 'voice-test',
      display_name: 'Voice Test',
      role: 'user',
      native_language: 'es',
      target_language: 'en-GB',
      conversation_speech_pause: speechPause,
    }),
  })
  render(<ConversationMode />)
}

describe('ConversationMode provisional turns', () => {
  it('test_vad_sends_provisional_at_800ms_and_confirms_at_redemption', async () => {
    renderWithPause(2000)
    const ws = await start()
    expect(mocks.options.redemptionMs).toBe(2000)
    const feed = vadProcessor()

    await feed(voiceFrame, 40)
    await feed(silenceFrame, 24)
    expect(ws.send).not.toHaveBeenCalled()

    await feed(silenceFrame, 1) // 25 x 32 ms = 800 ms
    expect(sentKinds(ws)).toEqual(['provisional', 'wav'])
    const wav = ws.send.mock.calls[1][0] as ArrayBuffer
    expect(wav.byteLength).toBe(44 + (40 + 25) * 512 * 2)

    await feed(silenceFrame, 36) // 61 x 32 ms: the VAD ends the turn at 62 frames
    expect(sentKinds(ws)).toEqual(['provisional', 'wav'])

    await feed(silenceFrame, 1)
    expect(sentKinds(ws)).toEqual(['provisional', 'wav', 'confirm'])
  })

  it('aborts when the child continues and restarts from the longer utterance', async () => {
    renderWithPause(2000)
    const ws = await start()
    const feed = vadProcessor()

    await feed(voiceFrame, 40)
    await feed(silenceFrame, 25)
    await feed(voiceFrame, 1)
    expect(sentKinds(ws)).toEqual(['provisional', 'wav', 'abort'])

    await feed(voiceFrame, 19)
    await feed(silenceFrame, 25)
    expect(sentKinds(ws)).toEqual([
      'provisional',
      'wav',
      'abort',
      'provisional',
      'wav',
    ])
    const longer = ws.send.mock.calls[4][0] as ArrayBuffer
    expect(longer.byteLength).toBe(44 + (40 + 25 + 20 + 25) * 512 * 2)

    await feed(silenceFrame, 37)
    expect(sentKinds(ws).slice(-1)).toEqual(['confirm'])
  })

  it('sends the full turn instead of confirm when quiet speech followed the provisional', async () => {
    renderWithPause(2000)
    const ws = await start()
    const feed = vadProcessor()

    await feed(voiceFrame, 40)
    await feed(silenceFrame, 25)
    expect(sentKinds(ws)).toEqual(['provisional', 'wav'])
    const provisional = ws.send.mock.calls[1][0] as ArrayBuffer

    await feed(quietFrame, 4)
    await feed(silenceFrame, 62)

    expect(sentKinds(ws)).toEqual(['provisional', 'wav', 'abort', 'wav'])
    const final = ws.send.mock.calls[3][0] as ArrayBuffer
    expect(final.byteLength).toBeGreaterThan(provisional.byteLength)
  })

  it('does not send the audio again when the turn is confirmed', async () => {
    renderWithPause(2000)
    const ws = await start()
    const feed = vadProcessor()
    await feed(voiceFrame, 40)
    await feed(silenceFrame, 62)
    const wavs = ws.send.mock.calls.filter(
      ([sent]) => sent instanceof ArrayBuffer
    )
    expect(wavs).toHaveLength(1)
  })

  it('stays quiet while provisional and ignores speech after confirmation as before', async () => {
    renderWithPause(2000)
    const ws = await start()
    const feed = vadProcessor()
    await feed(voiceFrame, 40)
    await feed(silenceFrame, 63)
    expect(sentKinds(ws)).toEqual(['provisional', 'wav', 'confirm'])
    ws.send.mockClear()

    await feed(voiceFrame, 40)
    await feed(silenceFrame, 63)

    expect(ws.send).not.toHaveBeenCalled()
  })

  it('does not send provisional audio when the utterance is too quiet', async () => {
    renderWithPause(2000)
    const ws = await start()
    const quietFrame = new Float32Array(512).fill(0.005)
    const processor = new FrameProcessor(
      async (frame) => ({
        isSpeech: frame === quietFrame ? 0.99 : 0.01,
        notSpeech: frame === quietFrame ? 0.01 : 0.99,
      }),
      () => {},
      {
        ...defaultFrameProcessorOptions,
        positiveSpeechThreshold: mocks.options.positiveSpeechThreshold!,
        redemptionMs: mocks.options.redemptionMs!,
      },
      32
    )
    processor.resume()
    const handleEvent = (event: FrameProcessorEvent) => {
      if (event.msg === Message.FrameProcessed) {
        mocks.options.onFrameProcessed?.(event.probs, event.frame)
      }
      if (event.msg === Message.SpeechStart) mocks.options.onSpeechStart?.()
      if (event.msg === Message.SpeechEnd)
        mocks.options.onSpeechEnd?.(event.audio)
    }
    await act(async () => {
      for (let i = 0; i < 40; i++) {
        await processor.process(quietFrame, handleEvent)
      }
      for (let i = 0; i < 70; i++) {
        await processor.process(silenceFrame, handleEvent)
      }
    })
    expect(ws.send).not.toHaveBeenCalled()
  })

  it('aborts a sent provisional when the VAD discards the speech', async () => {
    renderWithPause(2000)
    const ws = await start()
    act(() => {
      mocks.options.onFrameProcessed?.(
        { isSpeech: 0.99, notSpeech: 0.01 },
        new Float32Array(512).fill(0.05)
      )
      mocks.options.onSpeechStart?.()
    })
    await act(async () => {
      for (let i = 0; i < 40; i++)
        mocks.options.onFrameProcessed?.(
          { isSpeech: 0.99, notSpeech: 0.01 },
          voiceFrame
        )
      for (let i = 0; i < 25; i++)
        mocks.options.onFrameProcessed?.(
          { isSpeech: 0.01, notSpeech: 0.99 },
          silenceFrame
        )
    })
    expect(sentKinds(ws)).toEqual(['provisional', 'wav'])
    act(() => mocks.options.onVADMisfire?.())
    expect(sentKinds(ws)).toEqual(['provisional', 'wav', 'abort'])
  })

  it('test_short_user_pause_skips_provisional', async () => {
    renderWithPause(1000)
    const ws = await start()
    const feed = vadProcessor()
    await feed(voiceFrame, 40)
    await feed(silenceFrame, 30)
    expect(ws.send).not.toHaveBeenCalled()
    await feed(silenceFrame, 1)
    expect(sentKinds(ws)).toEqual(['wav'])
  })
})

describe('ConversationMode heard text and speech session', () => {
  it('shows what Lingu heard with a redo that discards the turn', async () => {
    render(<ConversationMode />)
    const ws = await start()
    act(() => speak())
    act(() =>
      ws.message({ type: 'transcript', role: 'user', text: 'I has a dog' })
    )
    act(() =>
      ws.message({
        type: 'transcript',
        role: 'assistant',
        text: 'Nice dog!',
        final: true,
      })
    )
    expect(screen.getByText('heardLabel')).toBeInTheDocument()
    expect(screen.getByText('I has a dog')).toBeInTheDocument()

    ws.send.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'redo' }))

    expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({
      type: 'client_event',
      event: 'discard_last_turn',
    })
    expect(mocks.cancel).toHaveBeenCalled()
    expect(screen.queryByText('I has a dog')).not.toBeInTheDocument()
    expect(screen.queryByText('Nice dog!')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'redo' })).toBeNull()
  })

  it('offers redo only on the latest heard text', async () => {
    render(<ConversationMode />)
    const ws = await start()
    for (const text of ['first', 'second']) {
      act(() => ws.message({ type: 'transcript', role: 'user', text }))
    }
    expect(screen.getAllByRole('button', { name: 'redo' })).toHaveLength(1)
  })

  it.each([
    ['switching', 'speechSwitching'],
    ['off', 'speechSwitching'],
    ['busy', 'speechBusy'],
    ['away', 'speechAway'],
  ])('explains the %s speech state and keeps text working', (state, key) => {
    useSpeechSessionStore.setState({ state: state as 'busy' })
    render(<ConversationMode />)
    expect(screen.getByText(key)).toBeInTheDocument()
    expect(screen.queryByText(/errorConnection/)).toBeNull()
  })

  it.each(['switching', 'off', 'busy', 'away', null])(
    'keeps Start disabled while the speech state is %s',
    async (state) => {
      useSpeechSessionStore.setState({ state: state as 'busy' | null })
      render(<ConversationMode />)
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'start' })).toBeDisabled()
      )
      fireEvent.click(screen.getByRole('button', { name: 'start' }))
      expect(MockWebSocket.instances).toHaveLength(0)
    }
  )

  it.each(['ready', 'shared'])('enables Start when %s', (state) => {
    useSpeechSessionStore.setState({ state: state as 'ready' })
    render(<ConversationMode />)
    expect(screen.getByRole('button', { name: 'start' })).not.toBeDisabled()
  })

  it('shows no speech notice when the voice is ready', () => {
    useSpeechSessionStore.setState({ state: 'ready' })
    render(<ConversationMode />)
    expect(screen.queryByText(/^speech(Switching|Busy|Away)$/)).toBeNull()
  })
})
