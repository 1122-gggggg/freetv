import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ControllerState, NetflixContext } from '../types/protocol'
import { RemotePage } from './RemotePage'

const socketMock = vi.hoisted(() => ({
  status: 'connected' as 'connecting' | 'authenticating' | 'connected' | 'disconnected' | 'error',
  state: null as ControllerState | null,
  lastAcknowledgement: null as {
    request_id: string
    success: boolean
    error_code: string | null
    message: string | null
  } | null,
  sendCommand: vi.fn<(command: string) => string>(() => 'request-id'),
  sendPointer: vi.fn(() => 'request-id'),
  sendText: vi.fn<(text: string, submit?: boolean) => string | null>(() => 'request-id'),
  sendSearch: vi.fn(() => 'request-id'),
}))

vi.mock('../api/useControllerSocket', () => ({
  useControllerSocket: () => ({
    status: socketMock.status,
    state: socketMock.state,
    lastAcknowledgement: socketMock.lastAcknowledgement,
    lastError: null,
    sendCommand: socketMock.sendCommand,
    sendPointer: socketMock.sendPointer,
    sendText: socketMock.sendText,
    sendSearch: socketMock.sendSearch,
  }),
}))

const remoteElement = () => (
  <RemotePage
    token="paired-token-value-that-is-long-enough"
    onPaired={vi.fn()}
    onForget={vi.fn()}
    onAuthenticationFailed={vi.fn()}
  />
)

const netflixState = (context: NetflixContext | null): ControllerState => ({
  version: 1,
  type: 'state',
  active_app: 'netflix',
  focused_tile: 'netflix',
  volume: 50,
  muted: false,
  channel_number: null,
  channel_name: null,
  status_message: null,
  error_message: null,
  netflix_context: context,
})

describe('RemotePage', () => {
  beforeEach(() => {
    socketMock.status = 'connected'
    socketMock.state = null
    socketMock.lastAcknowledgement = null
    socketMock.sendCommand.mockClear()
    socketMock.sendPointer.mockClear()
    socketMock.sendText.mockClear()
    socketMock.sendSearch.mockClear()
    window.localStorage.clear()
    window.history.replaceState(null, '', '/remote')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/remote')
  })

  it('keeps the paired remote visible and reports a failed server-side revocation', async () => {
    const onForget = vi.fn().mockRejectedValue(new Error('無法解除這支遙控器的配對。'))

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={onForget}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '解除配對' }))

    await waitFor(() => expect(onForget).toHaveBeenCalledOnce())
    expect(await screen.findByText('無法解除這支遙控器的配對。')).toBeTruthy()
    expect((screen.getByRole('button', { name: '解除配對' }) as HTMLButtonElement).disabled).toBe(false)
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
    expect(document.title).toBe('我的電視遙控器')
    expect(screen.getByRole('button', { name: 'YouTube' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Netflix' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '新聞' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '返回' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '主畫面' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '頻道 +' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '音量 +' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '語音' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '搜片' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Live TV' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Browser' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sleep PC' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^電視$/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '瀏覽器' })).toBeNull()
    expect(screen.queryByRole('button', { name: '休眠電腦' })).toBeNull()
    expect(screen.queryByLabelText(/Touchpad/i)).toBeNull()
    expect(screen.queryByLabelText(/觸控板/)).toBeNull()
  })

  it('sends the existing Netflix navigation and 256-character text contracts', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    for (const label of ['上', '下', '左', '右', '確定', '返回', '播放／暫停']) {
      fireEvent.click(screen.getByRole('button', { name: label }))
    }
    const text = 'x'.repeat(256)
    fireEvent.change(screen.getByLabelText('遙控輸入'), { target: { value: text } })
    fireEvent.click(screen.getByRole('button', { name: '送出' }))

    expect(socketMock.sendCommand.mock.calls.map(([command]) => command)).toEqual([
      'NAV_UP',
      'NAV_DOWN',
      'NAV_LEFT',
      'NAV_RIGHT',
      'OK',
      'BACK',
      'PLAY_PAUSE',
    ])
    expect(socketMock.sendText).toHaveBeenCalledWith(text, false)
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

  it('types into Netflix from the remote keyboard', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('遙控輸入'), { target: { value: 'user@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '送出' }))
    expect(socketMock.sendText).toHaveBeenCalledWith('user@example.com', false)

    fireEvent.click(screen.getByRole('button', { name: '下一欄' }))
    expect(socketMock.sendCommand).toHaveBeenCalledWith('TAB')
  })


  it.each([
    {
      inputKind: 'email',
      stage: 'login',
      type: 'email',
      inputMode: 'email',
      autoComplete: 'username',
      placeholder: '請輸入 Netflix 電子郵件或手機號碼',
    },
    {
      inputKind: 'password',
      stage: 'login',
      type: 'password',
      inputMode: 'text',
      autoComplete: 'current-password',
      placeholder: '請輸入 Netflix 密碼',
    },
    {
      inputKind: 'code',
      stage: 'verification',
      type: 'text',
      inputMode: 'numeric',
      autoComplete: 'one-time-code',
      placeholder: '請輸入驗證碼 (OTP)',
    },
  ] as const)(
    'renders a safe Netflix $inputKind context input',
    ({ inputKind, stage, type, inputMode, autoComplete, placeholder }) => {
      socketMock.state = netflixState({
        stage,
        input_kind: inputKind,
        has_error: false,
        can_submit: true,
        focused_title: null,
      })

      render(remoteElement())

      const input = screen.getByLabelText('Netflix 情境輸入')
      expect(input.getAttribute('type')).toBe(type)
      expect(input.getAttribute('inputmode')).toBe(inputMode)
      expect(input.getAttribute('autocapitalize')).toBe('none')
      expect(input.getAttribute('autocomplete')).toBe(autoComplete)
      expect(input.getAttribute('placeholder')).toBe(placeholder)
      expect(input.getAttribute('maxlength')).toBe('256')
      expect(screen.queryByLabelText('遙控輸入')).toBeNull()
    },
  )
  it('keeps sensitive context text when socket send returns null and shows retry', () => {
    socketMock.state = netflixState({
      stage: 'login',
      input_kind: 'password',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    socketMock.sendText.mockReturnValueOnce(null)
    render(remoteElement())
    const input = screen.getByLabelText('Netflix 情境輸入') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'secret' } })

    fireEvent.click(screen.getByRole('button', { name: '送出 Netflix 輸入' }))

    expect(socketMock.sendText).toHaveBeenCalledWith('secret', true)
    expect(input.value).toBe('secret')
    expect(screen.getByText('無法送出，請重試')).toBeTruthy()
    expect(screen.queryByText('等待電視端回應...')).toBeNull()
  })

  it('uses a keyboard-specific description without connection-note overlap styles', () => {
    render(remoteElement())

    const description = screen.getByText(
      '先開啟 Netflix 或 YouTube，點選輸入欄，再從這裡輸入。',
    )
    expect(description.className).toBe('keyboard-description')
    expect(description.className).not.toContain('remote-connection-note')
  })


  it('submits once, clears immediately, and waits only until context changes', () => {
    const passwordContext: NetflixContext = {
      stage: 'login',
      input_kind: 'password',
      has_error: false,
      can_submit: true,
      focused_title: null,
    }
    socketMock.state = netflixState(passwordContext)
    const view = render(remoteElement())
    const input = screen.getByLabelText('Netflix 情境輸入') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'secret' } })

    fireEvent.click(screen.getByRole('button', { name: '送出 Netflix 輸入' }))

    expect(socketMock.sendText).toHaveBeenCalledOnce()
    expect(socketMock.sendText).toHaveBeenCalledWith('secret', true)
    expect(input.value).toBe('')
    expect(screen.getByText('等待電視端回應...')).toBeTruthy()

    socketMock.state = netflixState({
      stage: 'browse',
      input_kind: 'none',
      has_error: false,
      can_submit: false,
      focused_title: 'Example',
    })
    view.rerender(remoteElement())
    expect(screen.queryByText('等待電視端回應...')).toBeNull()
    expect(screen.queryByLabelText('Netflix 情境輸入')).toBeNull()
  })

  it('stops waiting on acknowledgement failure without restoring the secret', () => {
    socketMock.state = netflixState({
      stage: 'login',
      input_kind: 'password',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    const view = render(remoteElement())
    const input = screen.getByLabelText('Netflix 情境輸入') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'secret' } })
    fireEvent.click(screen.getByRole('button', { name: '送出 Netflix 輸入' }))
    expect(screen.getByText('等待電視端回應...')).toBeTruthy()

    socketMock.lastAcknowledgement = {
      request_id: 'request-id',
      success: false,
      error_code: 'netflix_controller_unavailable',
      message: 'failed',
    }
    view.rerender(remoteElement())

    expect(screen.queryByText('等待電視端回應...')).toBeNull()
    expect(input.value).toBe('')
    expect(screen.getByText('無法送出，請重試')).toBeTruthy()
    expect(input.disabled).toBe(false)
    expect(document.body.textContent).not.toContain('secret')
    fireEvent.change(input, { target: { value: 'retry' } })
    fireEvent.click(screen.getByRole('button', { name: '送出 Netflix 輸入' }))
    expect(socketMock.sendText).toHaveBeenLastCalledWith('retry', true)
  })

  it('shows only generic Netflix errors and browse-safe navigation context', () => {
    socketMock.state = netflixState({
      stage: 'login',
      input_kind: 'password',
      has_error: true,
      can_submit: true,
      focused_title: null,
    })
    const view = render(remoteElement())
    expect(
      screen.getByText('登入或驗證失敗，請檢查電視畫面後重試'),
    ).toBeTruthy()
    expect(document.body.textContent).not.toContain('password')

    socketMock.state = netflixState({
      stage: 'browse',
      input_kind: 'none',
      has_error: false,
      can_submit: false,
      focused_title: 'Example',
    })
    view.rerender(remoteElement())
    expect(screen.getByText('目前選取：Example')).toBeTruthy()
    expect(screen.getByText('左右換片、上下換列，按確定播放。')).toBeTruthy()
    expect(screen.queryByLabelText('Netflix 情境輸入')).toBeNull()
    expect(screen.queryByLabelText('遙控輸入')).toBeNull()
  })

  it.each(['details', 'watch'] as const)(
    'does not expose browse title or an input during %s',
    (stage) => {
      socketMock.state = netflixState({
        stage,
        input_kind: 'none',
        has_error: false,
        can_submit: false,
        focused_title: null,
      })

      render(remoteElement())

      expect(screen.queryByText(/目前選取：/)).toBeNull()
      expect(screen.queryByLabelText('Netflix 情境輸入')).toBeNull()
      expect(screen.queryByLabelText('遙控輸入')).toBeNull()
    },
  )

  it('unmounts on null, clears secrets, and leaves unknown on general controls', () => {
    socketMock.state = netflixState({
      stage: 'login',
      input_kind: 'password',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    const view = render(remoteElement())
    fireEvent.change(screen.getByLabelText('Netflix 情境輸入'), {
      target: { value: 'secret' },
    })

    socketMock.state = netflixState(null)
    view.rerender(remoteElement())
    expect(screen.queryByLabelText('Netflix 情境輸入')).toBeNull()
    expect(screen.getByLabelText('遙控輸入')).toBeTruthy()

    socketMock.state = netflixState({
      stage: 'unknown',
      input_kind: 'none',
      has_error: false,
      can_submit: false,
      focused_title: null,
    })
    view.rerender(remoteElement())
    expect(screen.queryByLabelText('Netflix 情境輸入')).toBeNull()
    expect(screen.getByLabelText('遙控輸入')).toBeTruthy()
    expect(screen.getByRole('button', { name: '確定' })).toBeTruthy()

    socketMock.state = netflixState({
      stage: 'login',
      input_kind: 'password',
      has_error: false,
      can_submit: true,
      focused_title: null,
    })
    view.rerender(remoteElement())
    expect((screen.getByLabelText('Netflix 情境輸入') as HTMLInputElement).value).toBe('')
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

    expect((screen.getByLabelText('配對碼') as HTMLInputElement).value).toBe('123456')
    fireEvent.click(screen.getByRole('button', { name: '配對遙控器' }))

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

    expect((screen.getByRole('button', { name: '音量 +' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('搜片') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '搜片' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: '語音' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('電視盒重新連線後，按鍵會自動解鎖。')).toBeTruthy()
  })

})
