import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RemotePage } from './RemotePage'

const socketMock = vi.hoisted(() => ({
  status: 'connected' as 'connecting' | 'authenticating' | 'connected' | 'disconnected' | 'error',
  sendCommand: vi.fn(() => 'request-id'),
  sendPointer: vi.fn(() => 'request-id'),
  sendText: vi.fn(() => 'request-id'),
  sendSearch: vi.fn(() => 'request-id'),
}))

vi.mock('../api/useControllerSocket', () => ({
  useControllerSocket: () => ({
    status: socketMock.status,
    state: null,
    lastAcknowledgement: null,
    lastError: null,
    sendCommand: socketMock.sendCommand,
    sendPointer: socketMock.sendPointer,
    sendText: socketMock.sendText,
    sendSearch: socketMock.sendSearch,
  }),
}))

describe('RemotePage', () => {
  beforeEach(() => {
    socketMock.status = 'connected'
    socketMock.sendCommand.mockClear()
    socketMock.sendPointer.mockClear()
    socketMock.sendText.mockClear()
    socketMock.sendSearch.mockClear()
    window.localStorage.clear()
    window.history.replaceState(null, '', '/remote')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/remote')
  })

  it('keeps the paired remote visible and reports a failed server-side revocation', async () => {
    const onForget = vi.fn().mockRejectedValue(new Error('Could not unpair this remote.'))

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={onForget}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Forget' }))

    await waitFor(() => expect(onForget).toHaveBeenCalledOnce())
    expect(await screen.findByText('Could not unpair this remote.')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Forget' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('is a handset with YouTube, Netflix, news, voice, and search', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'YouTube' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Netflix' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '新聞' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '語音' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '搜片' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Live TV' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Browser' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sleep PC' })).toBeNull()
    expect(screen.queryByLabelText(/Touchpad/i)).toBeNull()
  })

  it('sends search_video for 搜片', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('搜片'), { target: { value: 'cat videos' } })
    fireEvent.click(screen.getByRole('button', { name: '搜片' }))
    expect(socketMock.sendSearch).toHaveBeenCalledWith('cat videos')
  })

  it('uses speech recognition when 語音 is clicked', async () => {
    interface FakeSpeechRecognitionEvent {
      results: { [index: number]: { [index: number]: { transcript: string } } }
    }
    interface FakeSpeechRecognition {
      lang: string
      interimResults: boolean
      maxAlternatives: number
      onresult: ((event: FakeSpeechRecognitionEvent) => void) | null
      onerror: ((event: unknown) => void) | null
      onend: (() => void) | null
      start: () => void
      stop: () => void
    }
    const instances: FakeSpeechRecognition[] = []
    class MockSpeechRecognition implements FakeSpeechRecognition {
      lang = ''
      interimResults = false
      maxAlternatives = 1
      onresult: ((event: FakeSpeechRecognitionEvent) => void) | null = null
      onerror: ((event: unknown) => void) | null = null
      onend: (() => void) | null = null
      start = vi.fn()
      stop = vi.fn()
      constructor() {
        instances.push(this)
      }
    }
    vi.stubGlobal('SpeechRecognition', MockSpeechRecognition)

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    const voiceBtn = screen.getByRole('button', { name: '語音' })
    fireEvent.click(voiceBtn)
    expect(screen.getByText('聆聽中…')).toBeTruthy()
    expect(instances.length).toBe(1)
    expect(instances[0].start).toHaveBeenCalledOnce()
    expect(instances[0].lang).toBe('zh-TW')

    instances[0].onresult?.({
      results: [[{ transcript: '台灣新聞' }]],
    })

    expect(socketMock.sendSearch).toHaveBeenCalledWith('台灣新聞')
    await waitFor(() => {
      expect((screen.getByLabelText('搜片') as HTMLInputElement).value).toBe('台灣新聞')
    })
  })
  it('disables 語音 button when speech recognition API is missing', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect((screen.getByRole('button', { name: '語音' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('prefills a QR pairing code and removes it from the address bar after pairing', async () => {
    const onPaired = vi.fn()
    window.history.replaceState(null, '', '/remote?code=123456')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: 'paired-token-value-that-is-long-enough' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    render(
      <RemotePage
        token={null}
        onPaired={onPaired}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect((screen.getByLabelText('Pairing code') as HTMLInputElement).value).toBe('123456')
    fireEvent.click(screen.getByRole('button', { name: 'Pair remote' }))

    await waitFor(() => expect(onPaired).toHaveBeenCalledWith('paired-token-value-that-is-long-enough'))
    expect(window.location.pathname).toBe('/remote')
    expect(window.location.search).toBe('')
  })

  it('locks controls while the WebSocket is disconnected', () => {
    socketMock.status = 'disconnected'

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect((screen.getByRole('button', { name: 'Volume +' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('搜片') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '搜片' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '語音' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('Controls unlock automatically when the TV Box reconnects.')).toBeTruthy()
  })
})
