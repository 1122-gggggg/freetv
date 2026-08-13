import type { ButtonHTMLAttributes, ReactElement } from 'react'

import type { Command } from '../types/protocol'

interface CommandButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick'> {
  command: Command
  label: string
  onCommand: (command: Command) => void
  compact?: boolean
}

export function CommandButton({ command, label, onCommand, compact = false, className = '', ...props }: CommandButtonProps): ReactElement {
  return (
    <button
      {...props}
      className={`remote-button ${compact ? 'is-compact' : ''} ${className}`.trim()}
      type="button"
      onClick={() => {
        navigator.vibrate?.(8)
        onCommand(command)
      }}
    >
      {label}
    </button>
  )
}
