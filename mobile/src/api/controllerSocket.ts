import type {
  Acknowledgement,
  ClientMessage,
  Command,
  ControllerState,
  PointerAction,
  ProtocolError,
  ServerMessage,
} from '../types/protocol'
import { controllerOrigin } from './controllerEndpoint'
interface NativeWebSocketConstructor {
  new (
    uri: string,
    protocols: string | string[] | null,
    options: { headers: Record<string, string> },
  ): WebSocket
}



export type SocketStatus = 'disconnected' | 'connecting' | 'authenticated' | 'failed'

export interface SocketOptions {
  host: string
  port: number
  token: string
  onStatusChange?: (status: SocketStatus) => void
  onStateChange?: (state: ControllerState) => void
  onAcknowledgement?: (ack: Acknowledgement) => void
  onError?: (error: ProtocolError | Error) => void
  onAuthenticationFailed?: () => void
}

const INITIAL_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 5000
const MAX_POINTER_QUEUE_SIZE = 16
const POINTER_ACK_TIMEOUT_MS = 5000

interface QueuedPointer {
  action: PointerAction
  dx: number
  dy: number
}

function clampDelta(value: number): number {
  if (!Number.isFinite(value)) return 0
  const truncated = Math.trunc(value)
  return Math.max(-100, Math.min(100, truncated))
}

export class ControllerSocket {
  private socket: WebSocket | null = null
  private status: SocketStatus = 'disconnected'
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private backoffMs = INITIAL_BACKOFF_MS
  private isDisposed = false
  private pendingAcks = new Map<string, {
    handler: (ack: Acknowledgement) => void
    reject: (error: Error) => void
    timeout: ReturnType<typeof setTimeout>
  }>()
  private authenticationFailureReported = false
  private pointerQueue: QueuedPointer[] = []
  private inFlightPointerRequestId: string | null = null
  private pointerAckTimeout: ReturnType<typeof setTimeout> | null = null
  private socketGeneration = 0

  constructor(private options: SocketOptions) {}

  public connect(): void {
    this.isDisposed = false
    this.createSocket()
  }

  public disconnect(): void {
    this.isDisposed = true
    this.clearReconnect()
    this.clearPointerState()
    this.clearPendingAcks()
    this.socketGeneration++
    if (this.socket) {
      this.socket.close(1000, 'User disconnect')
      this.socket = null
    }
    this.updateStatus('disconnected')
  }

  public sendCommand(command: Command): Promise<Acknowledgement> {
    const requestId = this.generateRequestId()
    const message: ClientMessage = {
      version: 1,
      type: 'command',
      request_id: requestId,
      command,
    }
    return this.sendWithAck(requestId, message)
  }

  public sendPointer(action: PointerAction, dx: number, dy: number): void {
    if (this.status !== 'authenticated' || !this.socket || this.isDisposed) return

    const sanitizedDx = clampDelta(action === 'move' || action === 'scroll' ? dx : 0)
    const sanitizedDy = clampDelta(action === 'move' || action === 'scroll' ? dy : 0)

    if (this.inFlightPointerRequestId) {
      this.enqueuePointer(action, sanitizedDx, sanitizedDy)
      return
    }

    this.sendPointerDirect(action, sanitizedDx, sanitizedDy)
  }

  public sendTextInput(text: string): Promise<Acknowledgement> {
    const requestId = this.generateRequestId()
    const message: ClientMessage = {
      version: 1,
      type: 'text_input',
      request_id: requestId,
      text,
    }
    return this.sendWithAck(requestId, message)
  }

  private sendWithAck(requestId: string, message: ClientMessage): Promise<Acknowledgement> {
    return new Promise((resolve, reject) => {
      if (this.status !== 'authenticated' || !this.socket) {
        reject(new Error('Socket is not connected or authenticated'))
        return
      }

      const timeout = setTimeout(() => {
        this.pendingAcks.delete(requestId)
        reject(new Error('Command acknowledgement timed out'))
      }, 5000)

      this.pendingAcks.set(requestId, {
        handler: (ack) => {
          clearTimeout(timeout)
          resolve(ack)
        },
        reject,
        timeout,
      })

      try {
        this.socket.send(JSON.stringify(message))
      } catch (err) {
        clearTimeout(timeout)
        this.pendingAcks.delete(requestId)
        reject(err)
      }
    })
  }

  private createSocket(): void {
    this.authenticationFailureReported = false
    if (this.isDisposed) return
    this.clearReconnect()
    this.clearPointerState()
    this.socketGeneration++
    this.updateStatus('connecting')
    const { host, port, token } = this.options
    let origin: string
    try {
      origin = controllerOrigin(host, port)
    } catch (error) {
      this.updateStatus('failed')
      this.options.onError?.(error instanceof Error ? error : new Error('Invalid controller endpoint'))
      return
    }
    const url = `${origin.replace(/^https:/, 'wss:')}/ws/remote`

    try {
      this.socket = new (WebSocket as unknown as NativeWebSocketConstructor)(url, null, { headers: { origin } })

      this.socket.onopen = () => {
        const authMessage: ClientMessage = {
          version: 1,
          type: 'authenticate',
          request_id: this.generateRequestId(),
          token,
        }
        this.socket?.send(JSON.stringify(authMessage))
      }

      this.socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as ServerMessage
          this.handleMessage(message)
        } catch {
          // ignore malformed frame
        }
      }

      this.socket.onclose = (event) => {
        this.clearPendingAcks()
        this.clearPointerState()
        this.socketGeneration++
        this.socket = null
        if (event.code === 4401 || this.authenticationFailureReported) {
          this.updateStatus('failed')
          this.options.onAuthenticationFailed?.()
        } else if (event.code === 1008) {
          this.updateStatus('failed')
          this.options.onError?.(
            new Error('The PC TV Box rejected this connection. Check its address and local CA trust.'),
          )
        } else {
          this.updateStatus('disconnected')
          if (!this.isDisposed) {
            this.scheduleReconnect()
          }
        }
      }

      this.socket.onerror = () => {
        if (this.socket) {
          this.socket.close()
        }
      }
    } catch {
      this.updateStatus('disconnected')
      this.scheduleReconnect()
    }
  }

  private handleMessage(message: ServerMessage): void {
    if (message.type === 'state') {
      if (this.status !== 'authenticated') {
        this.updateStatus('authenticated')
        this.backoffMs = INITIAL_BACKOFF_MS
      }
      this.options.onStateChange?.(message)
    } else if (message.type === 'ack') {
      if (this.inFlightPointerRequestId && message.request_id === this.inFlightPointerRequestId) {
        if (this.pointerAckTimeout) {
          clearTimeout(this.pointerAckTimeout)
          this.pointerAckTimeout = null
        }
        this.inFlightPointerRequestId = null

        if (!message.success) {
          const errMessage = message.message || message.error_code || 'Pointer action failed'
          this.options.onError?.(new Error(errMessage))
        }

        this.pumpPointerQueue()
      }

      const pending = this.pendingAcks.get(message.request_id)
      if (pending) {
        this.pendingAcks.delete(message.request_id)
        pending.handler(message)
      }
      this.options.onAcknowledgement?.(message)
    } else if (message.type === 'error') {
      if (message.code === 'authentication_failed') {
        this.authenticationFailureReported = true
      }
      this.options.onError?.(message)
    }
  }

  private updateStatus(status: SocketStatus): void {
    this.status = status
    this.options.onStatusChange?.(status)
  }

  private scheduleReconnect(): void {
    if (this.isDisposed || this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.backoffMs = Math.min(this.backoffMs * 1.5, MAX_BACKOFF_MS)
      this.createSocket()
    }, this.backoffMs)
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private generateRequestId(): string {
    return `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  }

  private enqueuePointer(action: PointerAction, dx: number, dy: number): void {
    const last = this.pointerQueue[this.pointerQueue.length - 1]
    if (last && last.action === action && (action === 'move' || action === 'scroll')) {
      last.dx = clampDelta(last.dx + dx)
      last.dy = clampDelta(last.dy + dy)
      return
    }

    if (this.pointerQueue.length >= MAX_POINTER_QUEUE_SIZE) {
      this.options.onError?.(new Error('Touchpad input is temporarily busy'))
      return
    }

    this.pointerQueue.push({ action, dx, dy })
  }

  private sendPointerDirect(action: PointerAction, dx: number, dy: number): void {
    if (this.status !== 'authenticated' || !this.socket || this.isDisposed) return

    const requestId = this.generateRequestId()
    this.inFlightPointerRequestId = requestId
    const generation = this.socketGeneration

    const message: ClientMessage = {
      version: 1,
      type: 'pointer',
      request_id: requestId,
      action,
      dx: clampDelta(dx),
      dy: clampDelta(dy),
    }

    this.pointerAckTimeout = setTimeout(() => {
      if (this.socketGeneration !== generation) return
      if (this.inFlightPointerRequestId === requestId) {
        this.inFlightPointerRequestId = null
        this.pointerAckTimeout = null
        this.options.onError?.(new Error('Pointer acknowledgement timed out'))
        this.pumpPointerQueue()
      }
    }, POINTER_ACK_TIMEOUT_MS)

    try {
      this.socket.send(JSON.stringify(message))
    } catch (err) {
      if (this.pointerAckTimeout) {
        clearTimeout(this.pointerAckTimeout)
        this.pointerAckTimeout = null
      }
      this.inFlightPointerRequestId = null
      this.options.onError?.(err instanceof Error ? err : new Error('Failed to send pointer message'))
      this.pumpPointerQueue()
    }
  }

  private pumpPointerQueue(): void {
    if (this.status !== 'authenticated' || !this.socket || this.isDisposed || this.inFlightPointerRequestId) {
      return
    }

    const next = this.pointerQueue.shift()
    if (!next) return

    this.sendPointerDirect(next.action, next.dx, next.dy)
  }

  private clearPointerState(): void {
    if (this.pointerAckTimeout) {
      clearTimeout(this.pointerAckTimeout)
      this.pointerAckTimeout = null
    }
    this.inFlightPointerRequestId = null
    this.pointerQueue = []
  }
  private clearPendingAcks(): void {
    for (const [, pending] of this.pendingAcks) {
      clearTimeout(pending.timeout)
      pending.reject(new Error('Socket disconnected before acknowledgement'))
    }
    this.pendingAcks.clear()
  }
}
