import {
  type ButtonHTMLAttributes,
  type PointerEvent,
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
} from 'react'

import type { Command } from '../types/protocol'

const HOLD_DELAY_MS = 360
const REPEAT_INTERVAL_MS = 110

interface CommandButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'onClick' | 'onPointerDown' | 'onPointerUp' | 'onPointerCancel' | 'onLostPointerCapture'
> {
  command: Command
  label: string
  onCommand: (command: Command) => void
  compact?: boolean
  repeatOnHold?: boolean
}

export function CommandButton({
  command,
  label,
  children,
  onCommand,
  compact = false,
  repeatOnHold = false,
  className = '',
  disabled = false,
  ...props
}: CommandButtonProps): ReactElement {
  const holdTimer = useRef<number | null>(null)
  const repeatTimer = useRef<number | null>(null)
  const suppressClick = useRef(false)

  const emitCommand = useCallback(() => {
    navigator.vibrate?.(8)
    onCommand(command)
  }, [command, onCommand])

  const stopRepeating = useCallback(() => {
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current)
    if (repeatTimer.current !== null) window.clearInterval(repeatTimer.current)
    holdTimer.current = null
    repeatTimer.current = null
  }, [])

  useEffect(() => stopRepeating, [stopRepeating])

  useEffect(() => {
    if (!disabled) return
    stopRepeating()
    suppressClick.current = false
  }, [disabled, stopRepeating])

  const releasePointer = (event: PointerEvent<HTMLButtonElement>) => {
    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
    } catch {
      // Pointer capture is an enhancement; command dispatch does not depend on it.
    }
  }

  const handlePointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (!repeatOnHold || disabled || event.button !== 0) return
    suppressClick.current = false
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Some embedded browsers do not expose pointer capture.
    }
    holdTimer.current = window.setTimeout(() => {
      suppressClick.current = true
      emitCommand()
      repeatTimer.current = window.setInterval(emitCommand, REPEAT_INTERVAL_MS)
    }, HOLD_DELAY_MS)
  }

  const handlePointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    stopRepeating()
    releasePointer(event)
  }

  const handlePointerCancel = (event: PointerEvent<HTMLButtonElement>) => {
    stopRepeating()
    suppressClick.current = false
    releasePointer(event)
  }

  const handleClick = () => {
    if (suppressClick.current) {
      suppressClick.current = false
      return
    }
    emitCommand()
  }

  return (
    <button
      {...props}
      aria-label={label}
      className={`remote-button ${compact ? 'is-compact' : ''} ${className}`.trim()}
      disabled={disabled}
      type="button"
      onClick={handleClick}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onLostPointerCapture={() => stopRepeating()}
    >
      {children ?? label}
    </button>
  )
}
