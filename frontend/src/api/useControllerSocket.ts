import { useCallback, useEffect, useRef, useState } from 'react'

import { ControllerSocket, type ConnectionStatus } from './controllerSocket'
import type { Acknowledgement, Command, ControllerState, PointerAction, ProtocolError } from '../types/protocol'

export interface ControllerConnection {
  status: ConnectionStatus
  state: ControllerState | null
  lastAcknowledgement: Acknowledgement | null
  lastError: ProtocolError | null
  sendCommand: (command: Command) => string | null
  sendPointer: (action: PointerAction, dx?: number, dy?: number) => string | null
  sendText: (text: string) => string | null
}

export function useControllerSocket(path: '/ws/remote' | '/ws/tv', token?: string): ControllerConnection {
  const socketRef = useRef<ControllerSocket | null>(null)
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [state, setState] = useState<ControllerState | null>(null)
  const [lastAcknowledgement, setLastAcknowledgement] = useState<Acknowledgement | null>(null)
  const [lastError, setLastError] = useState<ProtocolError | null>(null)

  useEffect(() => {
    const socket = new ControllerSocket(path, token)
    socketRef.current = socket
    const unsubscribeStatus = socket.onStatus(setStatus)
    const unsubscribeState = socket.onState(setState)
    const unsubscribeAcknowledgement = socket.onAcknowledgement(setLastAcknowledgement)
    const unsubscribeError = socket.onError(setLastError)
    socket.connect()

    return () => {
      unsubscribeStatus()
      unsubscribeState()
      unsubscribeAcknowledgement()
      unsubscribeError()
      socket.close()
      if (socketRef.current === socket) socketRef.current = null
    }
  }, [path, token])

  const sendCommand = useCallback((command: Command) => socketRef.current?.sendCommand(command) ?? null, [])
  const sendPointer = useCallback(
    (action: PointerAction, dx = 0, dy = 0) => socketRef.current?.sendPointer(action, dx, dy) ?? null,
    [],
  )
  const sendText = useCallback((text: string) => socketRef.current?.sendText(text) ?? null, [])

  return { status, state, lastAcknowledgement, lastError, sendCommand, sendPointer, sendText }
}
