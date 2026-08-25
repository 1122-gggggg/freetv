import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ControllerSocket } from './controllerSocket'

const requestIdPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/
const sockets: MockWebSocket[] = []

class MockWebSocket extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly sent: string[] = []
  readyState = MockWebSocket.CONNECTING

  constructor(readonly url: string | URL) {
    super()
    sockets.push(this)
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN
    this.dispatchEvent(new Event('open'))
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED
    this.dispatchEvent(new CloseEvent('close', { code: 1000 }))
  }

  serverClose(code = 1006): void {
    this.readyState = MockWebSocket.CLOSED
    this.dispatchEvent(new CloseEvent('close', { code }))
  }

  receive(payload: object): void {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }
}

describe('ControllerSocket request IDs', () => {
  beforeEach(() => {
    sockets.length = 0
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('creates valid, distinct authenticate and command IDs without crypto.randomUUID', () => {
    const getRandomValues = vi.fn((values: Uint32Array) => {
      values.fill(0x1234_5678)
      return values
    })
    vi.stubGlobal('crypto', {
      getRandomValues,
    })
    vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000)

    const controller = new ControllerSocket('/ws/remote', 'paired-token')
    controller.connect()

    const socket = sockets[0]
    expect(socket).toBeDefined()
    socket.open()
    const commandRequestId = controller.sendCommand('NAV_UP')

    const messages = socket.sent.map(
      (raw) => JSON.parse(raw) as { type: string; request_id: string; command?: string; token?: string },
    )
    expect(messages).toHaveLength(2)
    expect(messages[0]).toMatchObject({ type: 'authenticate', token: 'paired-token' })
    expect(messages[1]).toMatchObject({ type: 'command', command: 'NAV_UP' })
    expect(commandRequestId).toBe(messages[1].request_id)

    const requestIds = messages.map((message) => message.request_id)
    for (const requestId of requestIds) {
      expect(requestId).toMatch(requestIdPattern)
      expect(requestId.length).toBeLessThanOrEqual(64)
    }
    expect(new Set(requestIds).size).toBe(requestIds.length)
    expect(getRandomValues).toHaveBeenCalledTimes(2)

    controller.close()
  })

  it('bounds reconnect attempts when TCP opens but authentication never succeeds', () => {
    vi.useFakeTimers()
    const controller = new ControllerSocket('/ws/remote', 'paired-token')
    controller.connect()

    for (let index = 0; index <= 8; index += 1) {
      const socket = sockets[index]
      socket.open()
      socket.serverClose()
      if (index < 8) vi.runOnlyPendingTimers()
    }
    vi.runAllTimers()

    expect(sockets).toHaveLength(9)
    controller.close()
  })

  it('resets reconnect backoff only after successful authentication', () => {
    vi.useFakeTimers()
    const controller = new ControllerSocket('/ws/remote', 'paired-token')
    controller.connect()

    const first = sockets[0]
    first.open()
    const authentication = JSON.parse(first.sent[0]) as { request_id: string }
    first.receive({
      version: 1,
      type: 'ack',
      request_id: authentication.request_id,
      success: true,
      error_code: null,
      message: null,
    })
    first.serverClose()
    vi.advanceTimersByTime(500)

    const second = sockets[1]
    second.open()
    second.serverClose()
    vi.advanceTimersByTime(999)
    expect(sockets).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(3)

    controller.close()
  })

  it('does not reconnect after policy or authentication rejection', () => {
    vi.useFakeTimers()
    const controller = new ControllerSocket('/ws/remote', 'paired-token')
    controller.connect()
    sockets[0].serverClose(4401)

    vi.runAllTimers()

    expect(sockets).toHaveLength(1)
    controller.close()
  })

  it('keeps Netflix command and text input on the existing version 1 wire messages', () => {
    const controller = new ControllerSocket('/ws/remote', 'paired-token')
    controller.connect()
    const socket = sockets[0]
    socket.open()

    controller.sendCommand('PLAY_PAUSE')
    controller.sendText('x'.repeat(256))
    const messages = socket.sent
      .map((raw) => JSON.parse(raw) as Record<string, unknown>)
      .filter((message) => message.type !== 'authenticate')

    expect(messages.map(({ type }) => type)).toEqual(['command', 'text_input'])
    expect(messages[0]).toMatchObject({ version: 1, command: 'PLAY_PAUSE' })
    expect(messages[1]).toMatchObject({ version: 1, text: 'x'.repeat(256) })
    expect(Object.keys(messages[0]).sort()).toEqual([
      'command',
      'request_id',
      'type',
      'version',
    ])
    expect(Object.keys(messages[1]).sort()).toEqual([
      'request_id',
      'text',
      'type',
      'version',
    ])
    controller.close()
  })
})
