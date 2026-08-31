import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TVLauncher } from './TVLauncher'

const socketState = vi.hoisted(() => ({
  statusMessage: null as string | null,
  updateAvailable: null as string | null,
}))

vi.mock('../api/useControllerSocket', () => ({
  useControllerSocket: () => ({
    status: 'connected',
    state: {
      version: 1,
      type: 'state',
      active_app: 'launcher',
      focused_tile: 'youtube',
      volume: 50,
      muted: false,
      brightness: 100,
      channel_number: null,
      channel_name: null,
      status_message: socketState.statusMessage,
      error_message: null,
      update_available: socketState.updateAvailable,
    },
    lastAcknowledgement: null,
    lastError: null,
    sendCommand: () => 'request-id',
    sendPointer: () => 'request-id',
    sendText: () => 'request-id',
    sendSearch: () => 'request-id',
  }),
}))
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => <output data-testid="pairing-qr">{value}</output>,
}))

function pairingResponse(
  code: string,
  expiresAt: string,
  remoteUrl?: string,
  lanRemoteUrl?: string,
): Response {
  return new Response(
    JSON.stringify({
      code,
      expires_at: expiresAt,
      remote_url: remoteUrl ?? null,
      lan_remote_url: lanRemoteUrl ?? null,
    }),
    { status: 200 },
  )
}

describe('TVLauncher pairing code', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-13T00:00:00.000Z'))
  })

  afterEach(() => {
    socketState.statusMessage = null
    socketState.updateAvailable = null
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('refreshes the displayed pairing code before it expires', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(pairingResponse('111111', '2026-08-13T00:01:00.000Z'))
      .mockResolvedValueOnce(pairingResponse('222222', '2026-08-13T00:02:00.000Z'))
    vi.stubGlobal('fetch', fetchMock)

    render(<TVLauncher />)
    await act(async () => {})
    expect(screen.getByText('111111')).toBeTruthy()
    expect(screen.getByText('目前無法產生遙控器連結。')).toBeTruthy()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(55_000)
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('222222')).toBeTruthy()
  })

  it('shows the controller URL and encodes the one-time code in the pairing QR', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        pairingResponse(
          '111111',
          '2026-08-13T00:01:00.000Z',
          'https://abc.trycloudflare.com/remote',
          'http://192.168.1.42:8765/remote',
        ),
      ),
    )

    render(<TVLauncher />)
    await act(async () => {})

    expect(screen.getByText('https://abc.trycloudflare.com/remote')).toBeTruthy()
    expect(screen.getByText('http://192.168.1.42:8765/remote')).toBeTruthy()
    expect(screen.getByTestId('pairing-qr').textContent).toBe(
      'https://abc.trycloudflare.com/remote?code=111111',
    )
  })

  it('renders all tiles including the News tile', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(pairingResponse('111111', '2026-08-13T00:01:00.000Z')))

    render(<TVLauncher />)
    await act(async () => {})

    expect(document.title).toBe('我的電視')
    expect(screen.getByRole('heading', { name: '我的電視' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '開啟 YouTube' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '開啟 Netflix' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '開啟 新聞' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '開啟 設定' })).toBeNull()
    expect(screen.queryByRole('button', { name: '開啟 電視' })).toBeNull()
    expect(screen.queryByRole('button', { name: '開啟 瀏覽器' })).toBeNull()
  })

  it('shows a controller status in the transient HUD and then dismisses it', async () => {
    socketState.statusMessage = '音量 60%'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(pairingResponse('111111', '2026-08-13T00:01:00.000Z')),
    )

    const view = render(<TVLauncher />)
    await act(async () => {})
    expect(view.container.querySelector('.tv-hud-badge')?.textContent).toBe('音量 60%')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_200)
    })

    expect(view.container.querySelector('.tv-hud-badge')).toBeNull()
  })

  it('stages an advertised update and explains that restart is required', async () => {
    socketState.updateAvailable = 'v0.3.0'
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url === '/api/update/apply') {
        return new Response(
          JSON.stringify({
            success: true,
            message: '更新已下載。',
            version: 'v0.3.0',
            restart_required: true,
          }),
          { status: 200 },
        )
      }
      return pairingResponse('111111', '2026-08-13T00:01:00.000Z')
    })
    vi.stubGlobal('fetch', fetchMock)

    const view = render(<TVLauncher />)
    await act(async () => {})
    await act(async () => {
      screen.getByRole('button', { name: '立即更新' }).click()
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/update/apply', { method: 'POST' })
    expect(view.container.querySelector('.tv-hud-badge')?.textContent).toBe(
      '更新已下載，請重新啟動 FreeTV 完成安裝。',
    )
  })
})
