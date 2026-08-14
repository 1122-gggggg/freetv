import { ControllerSocket } from './controllerSocket'
import type { PointerMessage } from '../types/protocol'

class FakeWebSocket {
  public static instances: FakeWebSocket[] = []
  public onopen: (() => void) | null = null
  public onmessage: ((event: { data: string }) => void) | null = null
  public onerror: (() => void) | null = null
  public onclose: ((event: { code: number }) => void) | null = null
  public sent: string[] = []
  public closed = false

  public constructor(
    public readonly url: string,
    public readonly protocols: string | string[] | null,
    public readonly options: { headers: Record<string, string> },
  ) {
    FakeWebSocket.instances.push(this)
  }

  public send(data: string): void {
    this.sent.push(data)
  }

  public close(): void {
    this.closed = true
  }
}

function authenticate(ws: FakeWebSocket): void {
  ws.onopen?.()
  ws.onmessage?.({
    data: JSON.stringify({
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
    }),
  })
}

function sendAck(
  ws: FakeWebSocket,
  requestId: string,
  success = true,
  errorCode: string | null = null,
  message: string | null = null,
): void {
  ws.onmessage?.({
    data: JSON.stringify({
      version: 1,
      type: 'ack',
      request_id: requestId,
      success,
      error_code: errorCode,
      message,
    }),
  })
}

function getPointerMessages(ws: FakeWebSocket): PointerMessage[] {
  return ws.sent
    .map((s) => JSON.parse(s))
    .filter((m) => m.type === 'pointer') as PointerMessage[]
}
describe('ControllerSocket', () => {
  const browserWebSocket = globalThis.WebSocket

  beforeEach(() => {
    FakeWebSocket.instances = []
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
  })

  afterEach(() => {
    globalThis.WebSocket = browserWebSocket
    jest.clearAllTimers()
    jest.useRealTimers()
  })

  it('sends the controller origin during the native WebSocket handshake', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })

    socket.connect()

    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0]).toMatchObject({
      url: 'wss://192.168.1.42:8765/ws/remote',
      options: { headers: { origin: 'https://192.168.1.42:8765' } },
    })
    socket.disconnect()
  })

  it('preserves pairing after a server policy rejection', () => {
    const onAuthenticationFailed = jest.fn()
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
      onAuthenticationFailed,
    })

    socket.connect()
    FakeWebSocket.instances[0].onclose?.({ code: 1008 })

    expect(onAuthenticationFailed).not.toHaveBeenCalled()
    socket.disconnect()
  })

  it('permits at most one pointer request in flight and drains on ACK', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 10, 20)
    let pointerMsgs = getPointerMessages(ws)
    expect(pointerMsgs).toHaveLength(1)
    expect(pointerMsgs[0]).toMatchObject({
      action: 'move',
      dx: 10,
      dy: 20,
    })

    // Send another move while the first is in flight
    socket.sendPointer('move', 15, 25)
    expect(getPointerMessages(ws)).toHaveLength(1) // Still 1 in flight

    // ACK the first request
    sendAck(ws, pointerMsgs[0].request_id)

    // Now the queued move is sent
    pointerMsgs = getPointerMessages(ws)
    expect(pointerMsgs).toHaveLength(2)
    expect(pointerMsgs[1]).toMatchObject({
      action: 'move',
      dx: 15,
      dy: 25,
    })

    // ACK the second request
    sendAck(ws, pointerMsgs[1].request_id)
    expect(getPointerMessages(ws)).toHaveLength(2)
    socket.disconnect()
  })

  it('coalesces rapid adjacent move actions and clamps wire deltas to [-100, 100]', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 10, 10)
    const firstReqId = getPointerMessages(ws)[0].request_id

    // Rapid moves while first is in flight
    for (let i = 0; i < 50; i++) {
      socket.sendPointer('move', 5, -5)
    }

    expect(getPointerMessages(ws)).toHaveLength(1) // Only first sent

    sendAck(ws, firstReqId)

    // Second message should be a single coalesced move with clamped deltas
    const pointerMsgs = getPointerMessages(ws)
    expect(pointerMsgs).toHaveLength(2)
    expect(pointerMsgs[1]).toMatchObject({
      action: 'move',
      dx: 100,
      dy: -100,
    })
    sendAck(ws, pointerMsgs[1].request_id)
    socket.disconnect()
  })

  it('coalesces rapid adjacent scroll actions', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 1, 1)
    const firstReqId = getPointerMessages(ws)[0].request_id

    socket.sendPointer('scroll', 0, -20)
    socket.sendPointer('scroll', 0, -30)

    sendAck(ws, firstReqId)

    const pointerMsgs = getPointerMessages(ws)
    expect(pointerMsgs).toHaveLength(2)
    expect(pointerMsgs[1]).toMatchObject({
      action: 'scroll',
      dx: 0,
      dy: -50,
    })
    sendAck(ws, pointerMsgs[1].request_id)
    socket.disconnect()
  })

  it('preserves movement-before-click ordering', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    // 1. Initial move in flight
    socket.sendPointer('move', 2, 2)
    const firstReqId = getPointerMessages(ws)[0].request_id

    // 2. Pre-click moves (coalesced)
    socket.sendPointer('move', 10, 15)
    socket.sendPointer('move', 5, 5)

    // 3. Click (tap)
    socket.sendPointer('tap', 0, 0)

    // 4. Post-click moves (coalesced)
    socket.sendPointer('move', 1, 2)
    socket.sendPointer('move', 3, 4)

    // ACK 1
    sendAck(ws, firstReqId)

    // Message 2 should be pre-click coalesced move
    let msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(2)
    expect(msgs[1]).toMatchObject({ action: 'move', dx: 15, dy: 20 })

    // ACK 2
    sendAck(ws, msgs[1].request_id)

    // Message 3 should be tap (click occurs after prior movement)
    msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(3)
    expect(msgs[2]).toMatchObject({ action: 'tap', dx: 0, dy: 0 })

    // ACK 3
    sendAck(ws, msgs[2].request_id)

    // Message 4 should be post-click coalesced move
    msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(4)
    expect(msgs[3]).toMatchObject({ action: 'move', dx: 4, dy: 6 })
    sendAck(ws, msgs[3].request_id)
    socket.disconnect()
  })

  it('clamps individual pointer wire deltas to [-100, 100]', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 300, -250)
    const msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(1)
    expect(msgs[0]).toMatchObject({
      action: 'move',
      dx: 100,
      dy: -100,
    })
    sendAck(ws, msgs[0].request_id)
    socket.disconnect()
  })

  it('surfaces failed pointer ACKs through onError and continues draining queue', () => {
    const onError = jest.fn()
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
      onError,
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 10, 10)
    socket.sendPointer('tap', 0, 0)

    const msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(1)

    // Send failed ACK for first move
    sendAck(ws, msgs[0].request_id, false, 'invalid_action', 'Touchpad disabled')

    expect(onError).toHaveBeenCalledWith(expect.any(Error))
    expect(onError.mock.calls[0][0].message).toBe('Touchpad disabled')

    // Next action (tap) is still pumped and sent
    const updatedMsgs = getPointerMessages(ws)
    expect(updatedMsgs).toHaveLength(2)
    expect(updatedMsgs[1]).toMatchObject({ action: 'tap', dx: 0, dy: 0 })
    sendAck(ws, updatedMsgs[1].request_id)
    socket.disconnect()
  })

  it('surfaces pointer ACK timeout through onError and pumps next queued action', () => {
    jest.useFakeTimers()
    const onError = jest.fn()
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
      onError,
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 10, 10)
    socket.sendPointer('tap', 0, 0)

    expect(getPointerMessages(ws)).toHaveLength(1)

    // Trigger ACK timeout
    jest.advanceTimersByTime(5000)

    expect(onError).toHaveBeenCalledWith(expect.any(Error))
    expect(onError.mock.calls[0][0].message).toBe('Pointer acknowledgement timed out')

    // Tap is now pumped
    const msgs = getPointerMessages(ws)
    expect(msgs).toHaveLength(2)
    expect(msgs[1]).toMatchObject({ action: 'tap', dx: 0, dy: 0 })
    sendAck(ws, msgs[1].request_id)
    socket.disconnect()
    jest.useRealTimers()
  })

  it('clears queue on disconnect and does not replay stale input on reconnect', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws1 = FakeWebSocket.instances[0]
    authenticate(ws1)

    socket.sendPointer('move', 10, 10)
    socket.sendPointer('move', 20, 20)
    socket.sendPointer('tap', 0, 0)

    expect(getPointerMessages(ws1)).toHaveLength(1)

    // User disconnects
    socket.disconnect()

    // Reconnect socket
    socket.connect()
    expect(FakeWebSocket.instances).toHaveLength(2)
    const ws2 = FakeWebSocket.instances[1]
    authenticate(ws2)

    // ws2 should NOT receive any stale queued pointer messages
    expect(getPointerMessages(ws2)).toHaveLength(0)

    // New pointer message works normally
    socket.sendPointer('move', 5, 5)
    expect(getPointerMessages(ws2)).toHaveLength(1)
    expect(getPointerMessages(ws2)[0]).toMatchObject({ action: 'move', dx: 5, dy: 5 })
    sendAck(ws2, getPointerMessages(ws2)[0].request_id)
    socket.disconnect()
  })

  it('clears queue on socket close and avoids pumps from obsolete socket generation', () => {
    jest.useFakeTimers()
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws1 = FakeWebSocket.instances[0]
    authenticate(ws1)

    socket.sendPointer('move', 10, 10)
    socket.sendPointer('tap', 0, 0)

    // Connection drops unexpectedly
    ws1.onclose?.({ code: 1006 })

    // Advance timer past timeout
    jest.advanceTimersByTime(5000)

    // Advance reconnect backoff timer to reconnect
    jest.advanceTimersByTime(500)
    expect(FakeWebSocket.instances).toHaveLength(2)
    const ws2 = FakeWebSocket.instances[1]
    authenticate(ws2)

    // Stale queued messages must not be replayed on ws2
    expect(getPointerMessages(ws2)).toHaveLength(0)
    socket.disconnect()
    jest.useRealTimers()
  })

  it('bounds queue size under heavy non-coalescing traffic', () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 1, 1)
    const firstReqId = getPointerMessages(ws)[0].request_id

    // Alternating tap and double_tap cannot be coalesced
    for (let i = 0; i < 30; i++) {
      socket.sendPointer(i % 2 === 0 ? 'tap' : 'double_tap', 0, 0)
    }

    // Drain the queue by ACKing each message
    sendAck(ws, firstReqId)
    let drainedCount = 0
    while (true) {
      const msgs = getPointerMessages(ws)
      if (msgs.length === drainedCount + 1) break
      drainedCount = msgs.length - 1
      sendAck(ws, msgs[msgs.length - 1].request_id)
    }

    // Total messages sent should be bounded: 1 initial + max queue size (16) = 17 messages
    expect(getPointerMessages(ws)).toHaveLength(17)
    socket.disconnect()
  })

  it('rejects overflow without reordering a queued movement and tap', () => {
    const onError = jest.fn()
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
      onError,
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    socket.sendPointer('move', 1, 1)
    const firstReqId = getPointerMessages(ws)[0].request_id
    socket.sendPointer('move', 40, 20)
    socket.sendPointer('tap', 0, 0)
    for (let i = 0; i < 14; i++) {
      socket.sendPointer(i % 2 === 0 ? 'double_tap' : 'tap', 0, 0)
    }
    socket.sendPointer('tap', 0, 0)

    sendAck(ws, firstReqId)
    let messages = getPointerMessages(ws)
    expect(messages[1]).toMatchObject({ action: 'move', dx: 40, dy: 20 })
    sendAck(ws, messages[1].request_id)

    messages = getPointerMessages(ws)
    expect(messages[2]).toMatchObject({ action: 'tap', dx: 0, dy: 0 })
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'Touchpad input is temporarily busy' }))
    socket.disconnect()
  })

  it('rejects pending command acknowledgements when the socket closes', async () => {
    const socket = new ControllerSocket({
      host: '192.168.1.42',
      port: 8765,
      token: 'token',
    })
    socket.connect()
    const ws = FakeWebSocket.instances[0]
    authenticate(ws)

    const pending = socket.sendCommand('NAV_RIGHT')
    ws.onclose?.({ code: 1006 })

    await expect(pending).rejects.toThrow('Socket disconnected before acknowledgement')
    socket.disconnect()
  })
})
