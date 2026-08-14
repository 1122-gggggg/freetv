import type {
  Acknowledgement,
  ClientMessage,
  Command,
  ControllerState,
  PointerAction,
  ProtocolError,
  ServerMessage,
} from '../types/protocol'

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

export class ControllerSocket {
  private socket: WebSocket | null = null
  private status: SocketStatus = 'disconnected'
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private backoffMs = INITIAL_BACKOFF_MS
  private isDisposed = false
  private pendingAcks = new Map<string, (ack: Acknowledgement) => void>()

  constructor(private options: SocketOptions) {}

  public connect(): void {
    this.isDisposed = false
    this.createSocket()
  }

  public disconnect(): void {
    this.isDisposed = true
    this.clearReconnect()
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
    if (this.status !== 'authenticated' || !this.socket) return
    const message: ClientMessage = {
      version: 1,
      type: 'pointer',
      request_id: this.generateRequestId(),
      action,
      dx,
      dy,
    }
    this.socket.send(JSON.stringify(message))
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

      this.pendingAcks.set(requestId, (ack) => {
        clearTimeout(timeout)
        resolve(ack)
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
    if (this.isDisposed) return
    this.clearReconnect()
    this.updateStatus('connecting')

    const { host, port, token } = this.options
    const url = `wss://${host}:${port}/ws/remote`

    try {
      this.socket = new WebSocket(url)

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
        this.socket = null
        if (event.code === 1008 || event.code === 4401) {
          this.updateStatus('failed')
          this.options.onAuthenticationFailed?.()
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
      const handler = this.pendingAcks.get(message.request_id)
      if (handler) {
        this.pendingAcks.delete(message.request_id)
        handler(message)
      }
      this.options.onAcknowledgement?.(message)
    } else if (message.type === 'error') {
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
}
