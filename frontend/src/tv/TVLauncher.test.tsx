import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TVLauncher } from './TVLauncher'

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
      channel_number: null,
      channel_name: null,
      status_message: null,
      error_message: null,
    },
    lastAcknowledgement: null,
    lastError: null,
    sendCommand: () => 'request-id',
    sendPointer: () => 'request-id',
    sendText: () => 'request-id',
  }),
}))
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => <output data-testid="pairing-qr">{value}</output>,
}))


function pairingResponse(code: string, expiresAt: string, remoteUrl?: string): Response {
  return new Response(
    JSON.stringify({ code, expires_at: expiresAt, remote_url: remoteUrl ?? null }),
    { status: 200 },
  )
}


describe('TVLauncher pairing code', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-13T00:00:00.000Z'))
  })

  afterEach(() => {
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

    await act(async () => {
      await vi.advanceTimersByTimeAsync(55_000)
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('222222')).toBeTruthy()
  })

  it('encodes the controller LAN URL in the pairing QR code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        pairingResponse('111111', '2026-08-13T00:01:00.000Z', 'https://192.168.1.42:8765/remote'),
      ),
    )

    render(<TVLauncher />)
    await act(async () => {})

    expect(screen.getByTestId('pairing-qr').textContent).toBe(
      'https://192.168.1.42:8765/remote?code=111111',
    )
  })
})
