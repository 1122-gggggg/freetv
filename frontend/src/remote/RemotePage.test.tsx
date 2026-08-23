import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RemotePage } from './RemotePage'

const TAP_DELAY_MS = 260

const socketMock = vi.hoisted(() => ({
  status: 'connected' as 'connecting' | 'authenticating' | 'connected' | 'disconnected' | 'error',
  sendCommand: vi.fn(() => 'request-id'),
  sendPointer: vi.fn(() => 'request-id'),
  sendText: vi.fn(() => 'request-id'),
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
  }),
}))

describe('RemotePage', () => {
  beforeEach(() => {
    socketMock.status = 'connected'
    socketMock.sendCommand.mockClear()
    socketMock.sendPointer.mockClear()
    socketMock.sendText.mockClear()
    window.localStorage.clear()
    window.history.replaceState(null, '', '/remote')
  })

  afterEach(() => {
    vi.useRealTimers()
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

  it('exposes previous and next media controls', () => {
    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Previous' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next' })).toBeTruthy()
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
    expect((screen.getByLabelText('Text to send to the active application') as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText('Controls unlock automatically when the TV Box reconnects.')).toBeTruthy()
  })

  it('accumulates and clamps multiple touchpad moves queued in one animation frame', () => {
    const frames: FrameRequestCallback[] = []
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    })
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    const touchpad = screen.getByRole('application', { name: /Touchpad:/ })

    fireEvent.touchStart(touchpad, { touches: [{ clientX: 0, clientY: 0 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 40, clientY: 0 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 80, clientY: 0 }] })

    expect(requestFrame).toHaveBeenCalledOnce()
    expect(socketMock.sendPointer).not.toHaveBeenCalled()
    frames[0](0)
    expect(socketMock.sendPointer).toHaveBeenCalledOnce()
    expect(socketMock.sendPointer).toHaveBeenCalledWith('move', 100, 0)
  })

  it('does not turn accumulated small movements into a tap', () => {
    vi.useFakeTimers()
    const frames: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    const touchpad = screen.getByRole('application', { name: /Touchpad:/ })

    fireEvent.touchStart(touchpad, { touches: [{ clientX: 10, clientY: 10 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 12, clientY: 10 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 14, clientY: 10 }] })
    fireEvent.touchEnd(touchpad, { touches: [] })
    frames[0](0)
    vi.advanceTimersByTime(TAP_DELAY_MS + 1)

    expect(socketMock.sendPointer).toHaveBeenCalledOnce()
    expect(socketMock.sendPointer).toHaveBeenCalledWith('move', 6, 0)
  })

  it('cancels queued touchpad movement without dispatching a move or tap', () => {
    vi.useFakeTimers()
    const frames: FrameRequestCallback[] = []
    const cancelFrame = vi.fn()
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    }))
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    const touchpad = screen.getByRole('application', { name: /Touchpad:/ })

    fireEvent.touchStart(touchpad, { touches: [{ clientX: 10, clientY: 10 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 11, clientY: 10 }] })
    fireEvent.touchCancel(touchpad, { touches: [] })

    expect(cancelFrame).toHaveBeenCalledWith(1)
    frames[0](0)
    vi.advanceTimersByTime(TAP_DELAY_MS + 1)
    expect(socketMock.sendPointer).not.toHaveBeenCalled()
  })

  it('continues as pointer movement when a two-finger scroll drops to one finger', () => {
    vi.useFakeTimers()
    const frames: FrameRequestCallback[] = []
    const cancelFrame = vi.fn()
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      frames.push(callback)
      return frames.length
    }))
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)

    render(
      <RemotePage
        token="paired-token-value-that-is-long-enough"
        onPaired={vi.fn()}
        onForget={vi.fn()}
        onAuthenticationFailed={vi.fn()}
      />,
    )
    const touchpad = screen.getByRole('application', { name: /Touchpad:/ })

    fireEvent.touchStart(touchpad, {
      touches: [{ clientX: 10, clientY: 20 }, { clientX: 20, clientY: 20 }],
    })
    fireEvent.touchMove(touchpad, {
      touches: [{ clientX: 10, clientY: 10 }, { clientX: 20, clientY: 10 }],
    })
    fireEvent.touchEnd(touchpad, { touches: [{ clientX: 20, clientY: 10 }] })
    fireEvent.touchMove(touchpad, { touches: [{ clientX: 30, clientY: 10 }] })
    fireEvent.touchEnd(touchpad, { touches: [] })
    frames[1](0)
    vi.advanceTimersByTime(TAP_DELAY_MS + 1)

    expect(cancelFrame).toHaveBeenCalledWith(1)
    expect(socketMock.sendPointer).toHaveBeenNthCalledWith(1, 'scroll', 0, 10)
    expect(socketMock.sendPointer).toHaveBeenNthCalledWith(2, 'move', 15, 0)
  })
})
