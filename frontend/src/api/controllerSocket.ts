import {
  PROTOCOL_VERSION,
  type Acknowledgement,
  type Command,
  type ControllerState,
  type PointerAction,
  type PointerMessage,
  type ProtocolError,
  type ServerMessage,
} from '../types/protocol'

export type ConnectionStatus = 'connecting' | 'authenticating' | 'connected' | 'disconnected' | 'error'

type StateListener = (state: ControllerState) => void
type StatusListener = (status: ConnectionStatus) => void
type AcknowledgementListener = (acknowledgement: Acknowledgement) => void
type ErrorListener = (error: ProtocolError) => void

const MAX_RECONNECT_DELAY_MS = 10_000
const MAX_RECONNECT_ATTEMPTS = 8
const NON_RETRYABLE_CLOSE_CODES = new Set([1000, 1008, 4401])
let fallbackRequestSequence = 0

function createFallbackRequestId(cryptoApi: Crypto | undefined): string {
  fallbackRequestSequence = fallbackRequestSequence >= Number.MAX_SAFE_INTEGER ? 1 : fallbackRequestSequence + 1

  const randomWords = new Uint32Array(2)
  if (typeof cryptoApi?.getRandomValues === 'function') {
    cryptoApi.getRandomValues(randomWords)
  } else {
    for (let index = 0; index < randomWords.length; index += 1) {
      randomWords[index] = Math.floor(Math.random() * 0x1_0000_0000)
    }
  }

  const entropy = Array.from(randomWords, (word) => word.toString(16).padStart(8, '0')).join('')
  return `req-${Date.now().toString(36)}-${fallbackRequestSequence.toString(36)}-${entropy}`
}

export class ControllerSocket {
  private readonly url: string
  private readonly token?: string
  private socket?: WebSocket
  private authenticationRequestId?: string
  private reconnectTimer?: number
  private reconnectAttempt = 0
  private closed = false
  private readonly stateListeners = new Set<StateListener>()
  private readonly statusListeners = new Set<StatusListener>()
  private readonly acknowledgementListeners = new Set<AcknowledgementListener>()
  private readonly errorListeners = new Set<ErrorListener>()

  constructor(path: '/ws/remote' | '/ws/tv', token?: string) {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    this.url = `${scheme}//${window.location.host}${path}`
    this.token = token
  }

  connect(): void {
    if (this.closed || this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) {
      return
    }
    this.setStatus('connecting')
    const socket = new WebSocket(this.url)
    this.socket = socket

    socket.addEventListener('open', () => {
      if (socket !== this.socket || this.closed) return
      if (this.token) {
        const requestId = this.requestId()
        this.authenticationRequestId = requestId
        this.sendRaw({
          version: PROTOCOL_VERSION,
          type: 'authenticate',
          request_id: requestId,
          token: this.token,
        })
        this.setStatus('authenticating')
      } else {
        this.reconnectAttempt = 0
        this.setStatus('connected')
      }
    })

    socket.addEventListener('message', (event) => {
      if (socket !== this.socket) return
      this.handleMessage(event.data)
    })

    socket.addEventListener('error', () => {
      if (socket === this.socket) this.setStatus('error')
    })

    socket.addEventListener('close', (event) => {
      if (socket !== this.socket) return
      this.socket = undefined
      if (this.closed) return
      if (NON_RETRYABLE_CLOSE_CODES.has(event.code)) {
        this.setStatus('error')
        return
      }
      this.setStatus('disconnected')
      if (!this.scheduleReconnect()) this.setStatus('error')
    })
  }

  close(): void {
    this.closed = true
    if (this.reconnectTimer !== undefined) window.clearTimeout(this.reconnectTimer)
    this.socket?.close()
    this.socket = undefined
  }

  sendCommand(command: Command): string | null {
    return this.sendRaw({ version: PROTOCOL_VERSION, type: 'command', request_id: this.requestId(), command })
  }

  sendPointer(action: PointerAction, dx = 0, dy = 0): string | null {
    const message: PointerMessage = {
      version: PROTOCOL_VERSION,
      type: 'pointer',
      request_id: this.requestId(),
      action,
      dx,
      dy,
    }
    return this.sendRaw(message)
  }

  sendText(text: string): string | null {
    return this.sendRaw({ version: PROTOCOL_VERSION, type: 'text_input', request_id: this.requestId(), text })
  }

  sendSearch(query: string): string | null {
    return this.sendRaw({ version: PROTOCOL_VERSION, type: 'search_video', request_id: this.requestId(), query })
  }

  onState(listener: StateListener): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  onAcknowledgement(listener: AcknowledgementListener): () => void {
    this.acknowledgementListeners.add(listener)
    return () => this.acknowledgementListeners.delete(listener)
  }

  onError(listener: ErrorListener): () => void {
    this.errorListeners.add(listener)
    return () => this.errorListeners.delete(listener)
  }

  private sendRaw(message: object): string | null {
    if (this.socket?.readyState !== WebSocket.OPEN) return null
    const requestId = 'request_id' in message && typeof message.request_id === 'string' ? message.request_id : null
    this.socket.send(JSON.stringify(message))
    return requestId
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== 'string') return
    let message: unknown
    try {
      message = JSON.parse(raw)
    } catch {
      return
    }
    if (!isServerMessage(message)) return

    if (message.type === 'state') {
      this.stateListeners.forEach((listener) => listener(message))
      return
    }
    if (message.type === 'ack') {
      if (message.request_id === this.authenticationRequestId) {
        this.authenticationRequestId = undefined
        if (message.success) this.reconnectAttempt = 0
        this.setStatus(message.success ? 'connected' : 'error')
      }
      this.acknowledgementListeners.forEach((listener) => listener(message))
      return
    }
    this.errorListeners.forEach((listener) => listener(message))
  }

  private scheduleReconnect(): boolean {
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) return false
    const delay = Math.min(500 * 2 ** this.reconnectAttempt, MAX_RECONNECT_DELAY_MS)
    this.reconnectAttempt += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined
      this.connect()
    }, delay)
    return true
  }

  private requestId(): string {
    const cryptoApi = globalThis.crypto
    return typeof cryptoApi?.randomUUID === 'function' ? cryptoApi.randomUUID() : createFallbackRequestId(cryptoApi)
  }

  private setStatus(status: ConnectionStatus): void {
    this.statusListeners.forEach((listener) => listener(status))
  }
}

function isServerMessage(value: unknown): value is ServerMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as { version?: unknown; type?: unknown }
  return candidate.version === PROTOCOL_VERSION && ['state', 'ack', 'error'].includes(String(candidate.type))
}
