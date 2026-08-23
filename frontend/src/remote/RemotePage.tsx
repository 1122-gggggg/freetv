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

interface GestureState {
  mode: 'none' | 'move' | 'scroll'
  x: number
  y: number
  startX: number
  startY: number
  moved: boolean
}

function idleGesture(): GestureState {
  return { mode: 'none', x: 0, y: 0, startX: 0, startY: 0, moved: false }
}

function clampPointerDelta(value: number): number {
  return Math.max(-100, Math.min(100, Math.round(value)))
}

function removePairingCodeFromAddressBar(): void {
  const url = new URL(window.location.href)
  if (!url.searchParams.has('code')) return
  url.searchParams.delete('code')
  const query = url.searchParams.toString()
  window.history.replaceState(
    window.history.state,
    '',
    `${url.pathname}${query ? `?${query}` : ''}${url.hash}`,
  )
}

export function RemotePage({
  token,
  onPaired,
  onForget,
  onAuthenticationFailed,
}: RemotePageProps): ReactElement {
  useEffect(() => {
    document.title = 'MY TV Remote'
  }, [])

  if (!token) return <PairingScreen onPaired={onPaired} />
  return <RemoteControl token={token} onForget={onForget} onAuthenticationFailed={onAuthenticationFailed} />
}

function PairingScreen({ onPaired }: Pick<RemotePageProps, 'onPaired'>): ReactElement {
  const [code, setCode] = useState(() => {
    if (typeof window !== 'undefined') {
      const urlCode = new URLSearchParams(window.location.search).get('code')
      if (urlCode && /^\d{6}$/.test(urlCode)) {
        return urlCode
      }
    }
    return ''
  })
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
      removePairingCodeFromAddressBar()
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
        <p>Scan the QR code on the TV or enter its current six-digit code.</p>
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
          <button className="pairing-submit" disabled={submitting || code.length !== 6} type="submit">
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
  const gesture = useRef<GestureState>(idleGesture())
  const pendingPointer = useRef<PendingPointer | null>(null)
  const pointerFrame = useRef<number | null>(null)
  const tapTimer = useRef<number | null>(null)
  const controlsDisabled = status !== 'connected'

  useEffect(() => {
    if (lastError?.code === 'authentication_failed') onAuthenticationFailed()
  }, [lastError, onAuthenticationFailed])

  useEffect(() => () => {
    if (pointerFrame.current !== null) cancelAnimationFrame(pointerFrame.current)
    if (tapTimer.current !== null) window.clearTimeout(tapTimer.current)
  }, [])

  const command = (value: Command) => {
    if (!sendCommand(value)) navigator.vibrate?.([16, 35, 16])
  }

  const queuePointer = (action: PointerAction, dx = 0, dy = 0) => {
    if (controlsDisabled) return
    if (action === 'tap' || action === 'double_tap') {
      sendPointer(action)
      return
    }
    const pending = pendingPointer.current
    pendingPointer.current = pending?.action === action
      ? { action, dx: pending.dx + dx, dy: pending.dy + dy }
      : { action, dx, dy }
    if (pointerFrame.current !== null) return
    pointerFrame.current = requestAnimationFrame(() => {
      pointerFrame.current = null
      const pending = pendingPointer.current
      pendingPointer.current = null
      if (!pending) return
      const pointerDx = clampPointerDelta(pending.dx)
      const pointerDy = clampPointerDelta(pending.dy)
      if (pointerDx !== 0 || pointerDy !== 0) sendPointer(pending.action, pointerDx, pointerDy)
    })
  }

  const flushPendingPointer = () => {
    if (pointerFrame.current !== null) {
      cancelAnimationFrame(pointerFrame.current)
      pointerFrame.current = null
    }
    const pending = pendingPointer.current
    pendingPointer.current = null
    if (!pending) return
    const pointerDx = clampPointerDelta(pending.dx)
    const pointerDy = clampPointerDelta(pending.dy)
    if (pointerDx !== 0 || pointerDy !== 0) sendPointer(pending.action, pointerDx, pointerDy)
  }

  const touchStart = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (controlsDisabled) return
    const touches = event.touches
    if (touches.length === 2) {
      const x = (touches[0].clientX + touches[1].clientX) / 2
      const y = (touches[0].clientY + touches[1].clientY) / 2
      gesture.current = {
        mode: 'scroll',
        x,
        y,
        startX: x,
        startY: y,
        moved: false,
      }
      return
    }
    if (touches.length === 1) {
      gesture.current = {
        mode: 'move',
        x: touches[0].clientX,
        y: touches[0].clientY,
        startX: touches[0].clientX,
        startY: touches[0].clientY,
        moved: false,
      }
    }
  }

  const touchMove = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (controlsDisabled) return
    const current = gesture.current
    if (current.mode === 'move' && event.touches.length === 1) {
      const touch = event.touches[0]
      const dx = touch.clientX - current.x
      const dy = touch.clientY - current.y
      current.x = touch.clientX
      current.y = touch.clientY
      current.moved ||= Math.abs(touch.clientX - current.startX) + Math.abs(touch.clientY - current.startY) > 3
      queuePointer('move', dx * 1.5, dy * 1.5)
      return
    }
    if (current.mode === 'scroll' && event.touches.length === 2) {
      const y = (event.touches[0].clientY + event.touches[1].clientY) / 2
      const dy = current.y - y
      current.y = y
      current.moved ||= Math.abs(y - current.startY) > 2
      queuePointer('scroll', 0, dy)
    }
  }

  const touchEnd = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (controlsDisabled) {
      gesture.current = idleGesture()
      return
    }
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
    if (current.mode === 'scroll' && event.touches.length === 1) {
      flushPendingPointer()
      gesture.current = {
        mode: 'move',
        x: event.touches[0].clientX,
        y: event.touches[0].clientY,
        startX: event.touches[0].clientX,
        startY: event.touches[0].clientY,
        moved: true,
      }
      return
    }
    if (event.touches.length === 0) gesture.current = idleGesture()
  }

  const touchCancel = (event: TouchEvent<HTMLDivElement>) => {
    event.preventDefault()
    gesture.current = idleGesture()
    pendingPointer.current = null
    if (pointerFrame.current !== null) {
      cancelAnimationFrame(pointerFrame.current)
      pointerFrame.current = null
    }
  }

  const submitText = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (controlsDisabled || text.length === 0) return
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
      <p className="remote-connection-note" aria-live="polite">
        {controlsDisabled
          ? 'Controls unlock automatically when the TV Box reconnects.'
          : 'Hold arrows, volume, or channel buttons to repeat.'}
      </p>

      <section className="remote-power-row" aria-label="Power controls">
        <CommandButton command="POWER_SLEEP" label="Sleep PC" onCommand={command} disabled={controlsDisabled} />
      </section>

      <section className="remote-direction-pad" aria-label="Navigation controls">
        <CommandButton command="NAV_UP" label="Up" onCommand={command} className="direction-up" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="NAV_LEFT" label="Left" onCommand={command} className="direction-left" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="OK" label="OK" onCommand={command} className="direction-ok" disabled={controlsDisabled} />
        <CommandButton command="NAV_RIGHT" label="Right" onCommand={command} className="direction-right" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="NAV_DOWN" label="Down" onCommand={command} className="direction-down" disabled={controlsDisabled} repeatOnHold />
      </section>

      <section className="remote-grid two-column" aria-label="Core controls">
        <CommandButton command="BACK" label="Back" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="HOME" label="Home" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="VOLUME_UP" label="Volume +" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="CHANNEL_UP" label="Channel +" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="VOLUME_DOWN" label="Volume −" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="CHANNEL_DOWN" label="Channel −" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="MUTE" label="Mute" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="PLAY_PAUSE" label="Play / Pause" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="PREVIOUS" label="Previous" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="NEXT" label="Next" onCommand={command} disabled={controlsDisabled} />
      </section>

      <section className="remote-grid two-column apps-grid" aria-label="Applications">
        <CommandButton command="OPEN_YOUTUBE" label="YouTube" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_NETFLIX" label="Netflix" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_LIVE_TV" label="Live TV" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_BROWSER" label="Browser" onCommand={command} disabled={controlsDisabled} />
      </section>

      <section className="touchpad-card" aria-labelledby="touchpad-title">
        <div>
          <p className="eyebrow">TOUCHPAD</p>
          <h2 id="touchpad-title">Move, tap, scroll</h2>
        </div>
        <div
          className={`touchpad ${controlsDisabled ? 'is-disabled' : ''}`}
          role="application"
          aria-label="Touchpad: drag to move, tap to click, two-finger drag to scroll"
          aria-disabled={controlsDisabled}
          onTouchStart={touchStart}
          onTouchMove={touchMove}
          onTouchEnd={touchEnd}
          onTouchCancel={touchCancel}
        >
          <span>{controlsDisabled ? 'Reconnect to use the touchpad.' : 'One finger: move · tap: click · two fingers: scroll'}</span>
        </div>
      </section>

      <section className="text-card" aria-labelledby="text-title">
        <p className="eyebrow">TEXT INPUT</p>
        <h2 id="text-title">Type into the active app</h2>
        <form onSubmit={submitText}>
          <input
            aria-label="Text to send to the active application"
            disabled={controlsDisabled}
            maxLength={256}
            value={text}
            onChange={(event) => setText(event.target.value.slice(0, 256))}
          />
          <button disabled={controlsDisabled || text.length === 0} type="submit">Send text</button>
        </form>
      </section>

      <footer className="remote-feedback" aria-live="polite">
        {forgetError ?? state?.error_message ?? state?.status_message ?? lastError?.message ?? lastAcknowledgement?.message ?? (lastAcknowledgement?.success ? 'Command accepted.' : 'Ready.')}
      </footer>
    </main>
  )
}
