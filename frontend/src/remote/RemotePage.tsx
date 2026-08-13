import { type FormEvent, type ReactElement, type TouchEvent, useEffect, useRef, useState } from 'react'

import { useControllerSocket } from '../api/useControllerSocket'
import { CommandButton } from '../components/CommandButton'
import type { Command, PointerAction } from '../types/protocol'
import { rememberRemoteToken } from './tokenStorage'

const TAP_DELAY_MS = 260

interface PairResponse {
  token: string
}

interface RemotePageProps {
  token: string | null
  onPaired: (token: string) => void
  onForget: () => Promise<void>
  onAuthenticationFailed: () => void
}

interface RemoteControlProps {
  token: string
  onForget: () => Promise<void>
  onAuthenticationFailed: () => void
}


interface PendingPointer {
  action: PointerAction
  dx: number
  dy: number
}

export function RemotePage({
  token,
  onPaired,
  onForget,
  onAuthenticationFailed,
}: RemotePageProps): ReactElement {
  if (!token) return <PairingScreen onPaired={onPaired} />
  return <RemoteControl token={token} onForget={onForget} onAuthenticationFailed={onAuthenticationFailed} />
}

function PairingScreen({ onPaired }: Pick<RemotePageProps, 'onPaired'>): ReactElement {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the six-digit code shown on the TV.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await fetch('/api/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      const payload = (await response.json()) as Partial<PairResponse> & { detail?: string }
      if (!response.ok || typeof payload.token !== 'string') {
        throw new Error(payload.detail ?? 'Pairing was not accepted.')
      }
      rememberRemoteToken(payload.token)
      onPaired(payload.token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Pairing was not accepted.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="remote-shell pairing-shell">
      <section className="pairing-form-card" aria-labelledby="pairing-title">
        <p className="eyebrow">MY TV REMOTE</p>
        <h1 id="pairing-title">Pair this phone</h1>
        <p>Enter the six-digit code currently visible on the TV Launcher.</p>
        <form onSubmit={submit}>
          <label htmlFor="pairing-code">Pairing code</label>
          <input
            id="pairing-code"
            autoComplete="one-time-code"
            inputMode="numeric"
            maxLength={6}
            pattern="[0-9]{6}"
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
          />
          <button className="pairing-submit" disabled={submitting} type="submit">
            {submitting ? 'Pairing…' : 'Pair remote'}
          </button>
        </form>
        <p className="form-status" aria-live="polite">{error ?? 'This remote controls only the paired PC TV Box.'}</p>
      </section>
    </main>
  )
}

function RemoteControl({ token, onForget, onAuthenticationFailed }: RemoteControlProps): ReactElement {
  const { status, state, lastAcknowledgement, lastError, sendCommand, sendPointer, sendText } = useControllerSocket('/ws/remote', token)
  const [text, setText] = useState('')
  const [forgetError, setForgetError] = useState<string | null>(null)
  const [forgetting, setForgetting] = useState(false)
  const gesture = useRef({ mode: 'none' as 'none' | 'move' | 'scroll', x: 0, y: 0, moved: false })
  const pendingPointer = useRef<PendingPointer | null>(null)
  const pointerFrame = useRef<number | null>(null)
  const tapTimer = useRef<number | null>(null)

  useEffect(() => {
    if (lastError?.code === 'authentication_failed') onAuthenticationFailed()
  }, [lastError, onAuthenticationFailed])

  useEffect(() => () => {
    if (pointerFrame.current !== null) cancelAnimationFrame(pointerFrame.current)
    if (tapTimer.current !== null) window.clearTimeout(tapTimer.current)
  }, [])

  const command = (value: Command) => {
    if (!sendCommand(value)) navigator.vibrate?.(16)
  }

  const queuePointer = (action: PointerAction, dx = 0, dy = 0) => {
    if (action === 'tap' || action === 'double_tap') {
      sendPointer(action)
      return
    }
    pendingPointer.current = { action, dx: Math.max(-100, Math.min(100, Math.round(dx))), dy: Math.max(-100, Math.min(100, Math.round(dy))) }
    if (pointerFrame.current !== null) return
    pointerFrame.current = requestAnimationFrame(() => {
      pointerFrame.current = null
      const pending = pendingPointer.current
      pendingPointer.current = null
      if (pending && (pending.dx !== 0 || pending.dy !== 0)) sendPointer(pending.action, pending.dx, pending.dy)
    })
  }

  const touchStart = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    const touches = event.touches
    if (touches.length === 2) {
      gesture.current = {
        mode: 'scroll',
        x: (touches[0].clientX + touches[1].clientX) / 2,
        y: (touches[0].clientY + touches[1].clientY) / 2,
        moved: false,
      }
      return
    }
    if (touches.length === 1) {
      gesture.current = { mode: 'move', x: touches[0].clientX, y: touches[0].clientY, moved: false }
    }
  }

  const touchMove = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    const current = gesture.current
    if (current.mode === 'move' && event.touches.length === 1) {
      const touch = event.touches[0]
      const dx = touch.clientX - current.x
      const dy = touch.clientY - current.y
      current.x = touch.clientX
      current.y = touch.clientY
      current.moved ||= Math.abs(dx) + Math.abs(dy) > 3
      queuePointer('move', dx * 1.5, dy * 1.5)
      return
    }
    if (current.mode === 'scroll' && event.touches.length === 2) {
      const y = (event.touches[0].clientY + event.touches[1].clientY) / 2
      const dy = current.y - y
      current.y = y
      current.moved ||= Math.abs(dy) > 2
      queuePointer('scroll', 0, dy)
    }
  }

  const touchEnd = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    const current = gesture.current
    if (current.mode === 'move' && !current.moved && event.touches.length === 0) {
      if (tapTimer.current !== null) {
        window.clearTimeout(tapTimer.current)
        tapTimer.current = null
        queuePointer('double_tap')
      } else {
        tapTimer.current = window.setTimeout(() => {
          tapTimer.current = null
          queuePointer('tap')
        }, TAP_DELAY_MS)
      }
    }
    if (event.touches.length === 0) gesture.current = { mode: 'none', x: 0, y: 0, moved: false }
  }

  const submitText = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (text.length === 0) return
    if (sendText(text)) setText('')
  }

  const forget = async () => {
    setForgetting(true)
    setForgetError(null)
    try {
      await onForget()
    } catch (reason) {
      setForgetError(reason instanceof Error ? reason.message : 'Could not unpair this remote.')
      setForgetting(false)
    }
  }

  return (
    <main className="remote-shell" aria-label="MY TV remote">
      <header className="remote-header">
        <div>
          <p className="eyebrow">MY TV REMOTE</p>
          <h1>Control room</h1>
        </div>
        <button className="forget-button" disabled={forgetting} type="button" onClick={() => void forget()}>
          {forgetting ? 'Forgetting…' : 'Forget'}
        </button>
      </header>

      <div className={`connection-chip connection-${status}`} aria-live="polite">
        <span className="status-dot" aria-hidden="true" />
        {status === 'connected' ? 'Connected' : status === 'authenticating' ? 'Authenticating' : status}
      </div>

      <section className="remote-power-row" aria-label="Power controls">
        <CommandButton command="POWER_SLEEP" label="Sleep PC" onCommand={command} />
      </section>

      <section className="remote-direction-pad" aria-label="Navigation controls">
        <CommandButton command="NAV_UP" label="Up" onCommand={command} className="direction-up" />
        <CommandButton command="NAV_LEFT" label="Left" onCommand={command} className="direction-left" />
        <CommandButton command="OK" label="OK" onCommand={command} className="direction-ok" />
        <CommandButton command="NAV_RIGHT" label="Right" onCommand={command} className="direction-right" />
        <CommandButton command="NAV_DOWN" label="Down" onCommand={command} className="direction-down" />
      </section>

      <section className="remote-grid two-column" aria-label="Core controls">
        <CommandButton command="BACK" label="Back" onCommand={command} />
        <CommandButton command="HOME" label="Home" onCommand={command} />
        <CommandButton command="VOLUME_UP" label="Volume +" onCommand={command} />
        <CommandButton command="CHANNEL_UP" label="Channel +" onCommand={command} />
        <CommandButton command="VOLUME_DOWN" label="Volume −" onCommand={command} />
        <CommandButton command="CHANNEL_DOWN" label="Channel −" onCommand={command} />
        <CommandButton command="MUTE" label="Mute" onCommand={command} />
        <CommandButton command="PLAY_PAUSE" label="Play / Pause" onCommand={command} />
        <CommandButton command="PREVIOUS" label="Previous" onCommand={command} />
        <CommandButton command="NEXT" label="Next" onCommand={command} />
      </section>

      <section className="remote-grid two-column apps-grid" aria-label="Applications">
        <CommandButton command="OPEN_YOUTUBE" label="YouTube" onCommand={command} />
        <CommandButton command="OPEN_NETFLIX" label="Netflix" onCommand={command} />
        <CommandButton command="OPEN_LIVE_TV" label="Live TV" onCommand={command} />
        <CommandButton command="OPEN_BROWSER" label="Browser" onCommand={command} />
      </section>

      <section className="touchpad-card" aria-labelledby="touchpad-title">
        <div>
          <p className="eyebrow">TOUCHPAD</p>
          <h2 id="touchpad-title">Move, tap, scroll</h2>
        </div>
        <div
          className="touchpad"
          role="application"
          aria-label="Touchpad: drag to move, tap to click, two-finger drag to scroll"
          onTouchStart={touchStart}
          onTouchMove={touchMove}
          onTouchEnd={touchEnd}
          onTouchCancel={touchEnd}
        >
          <span>One finger: move · tap: click · two fingers: scroll</span>
        </div>
      </section>

      <section className="text-card" aria-labelledby="text-title">
        <p className="eyebrow">TEXT INPUT</p>
        <h2 id="text-title">Type into the active app</h2>
        <form onSubmit={submitText}>
          <input
            aria-label="Text to send to the active application"
            maxLength={256}
            value={text}
            onChange={(event) => setText(event.target.value.slice(0, 256))}
          />
          <button type="submit">Send text</button>
        </form>
      </section>

      <footer className="remote-feedback" aria-live="polite">
        {forgetError ?? state?.error_message ?? state?.status_message ?? lastError?.message ?? lastAcknowledgement?.message ?? (lastAcknowledgement?.success ? 'Command accepted.' : 'Ready.')}
      </footer>
    </main>
  )
}
