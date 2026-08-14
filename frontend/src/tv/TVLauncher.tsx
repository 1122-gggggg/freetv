import { type ReactElement, useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useControllerSocket } from '../api/useControllerSocket'
import type { Command } from '../types/protocol'
import { tileCommand, type TileId } from './navigation'

const TILES: ReadonlyArray<{ id: TileId; label: string; detail: string; badge: string }> = [
  { id: 'youtube', label: 'YouTube', detail: 'Open Brave with your existing profile', badge: 'YT' },
  { id: 'netflix', label: 'Netflix', detail: 'Open Microsoft Edge with your existing profile', badge: 'N' },
  { id: 'live_tv', label: 'Live TV', detail: 'Play configured channels through mpv', badge: 'TV' },
  { id: 'browser', label: 'Browser', detail: 'Open your configured browser start page', badge: 'WEB' },
  { id: 'settings', label: 'Settings', detail: 'Configure this box from settings.json', badge: 'SET' },
]

const PAIRING_REFRESH_INTERVAL_MS = 30_000
const PAIRING_REFRESH_LEEWAY_MS = 5_000

function pairingRefreshDelay(expiresAt: string): number {
  const expiresAtMilliseconds = Date.parse(expiresAt)
  if (Number.isNaN(expiresAtMilliseconds)) return PAIRING_REFRESH_INTERVAL_MS
  return Math.max(1_000, Math.min(PAIRING_REFRESH_INTERVAL_MS, expiresAtMilliseconds - Date.now() - PAIRING_REFRESH_LEEWAY_MS))
}


const KEY_COMMANDS: Record<string, Command> = {
  ArrowUp: 'NAV_UP',
  ArrowDown: 'NAV_DOWN',
  ArrowLeft: 'NAV_LEFT',
  ArrowRight: 'NAV_RIGHT',
  Enter: 'OK',
  Escape: 'BACK',
  Home: 'HOME',
  ' ': 'PLAY_PAUSE',
}

interface PairingInfo {
  code: string
  expires_at: string
}

function isTileId(value: string): value is TileId {
  return TILES.some((tile) => tile.id === value)
}

export function TVLauncher(): ReactElement {
  const { status, state, lastError, sendCommand } = useControllerSocket('/ws/tv')
  const [pairing, setPairing] = useState<PairingInfo | null>(null)
  const tileRefs = useRef<Partial<Record<TileId, HTMLButtonElement>>>({})
  const focusedTile = state && isTileId(state.focused_tile) ? state.focused_tile : 'youtube'

  useEffect(() => {
    document.title = 'MY TV • PC TV Box'
    let cancelled = false
    let refreshTimer: number | undefined
    const fetchPairing = () => {
      fetch('/api/pairing')
        .then(async (response) => {
          if (!response.ok) throw new Error('Pairing code is unavailable.')
          return (await response.json()) as PairingInfo
        })
        .then((info) => {
          if (cancelled) return
          setPairing(info)
          refreshTimer = window.setTimeout(fetchPairing, pairingRefreshDelay(info.expires_at))
        })
        .catch(() => {
          if (cancelled) return
          setPairing(null)
          refreshTimer = window.setTimeout(fetchPairing, PAIRING_REFRESH_INTERVAL_MS)
        })
    }
    fetchPairing()
    return () => {
      cancelled = true
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer)
    }
  }, [])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const command = KEY_COMMANDS[event.key]
      if (!command) return
      event.preventDefault()
      sendCommand(command)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [sendCommand])

  useEffect(() => {
    if (state?.active_app === 'launcher') tileRefs.current[focusedTile]?.focus()
  }, [focusedTile, state?.active_app])

  const selectTile = (tile: TileId) => {
    const command = tileCommand(tile)
    if (command) sendCommand(command)
  }

  const renderedState = state ?? {
    active_app: 'launcher',
    volume: 50,
    muted: false,
    channel_number: null,
    channel_name: null,
    status_message: null,
    error_message: null,
  }

  return (
    <main className="tv-shell" aria-label="MY TV launcher">
      <header className="tv-header">
        <div>
          <p className="eyebrow">PC TV BOX</p>
          <h1>MY TV</h1>
        </div>
        <div className={`connection-chip connection-${status}`} aria-live="polite">
          <span className="status-dot" aria-hidden="true" />
          {status === 'connected' ? 'Launcher connected' : `Launcher ${status}`}
        </div>
      </header>

      <section className="tv-content" aria-label="Applications">
        <div className="tv-grid">
          {TILES.map((tile) => (
            <button
              key={tile.id}
              ref={(element) => {
                if (element) tileRefs.current[tile.id] = element
              }}
              className={`tv-tile ${focusedTile === tile.id ? 'is-focused' : ''}`}
              type="button"
              aria-label={`Open ${tile.label}`}
              onClick={() => selectTile(tile.id)}
            >
              <span className="tile-badge" aria-hidden="true">{tile.badge}</span>
              <span className="tile-label">{tile.label}</span>
              <span className="tile-detail">{tile.detail}</span>
            </button>
          ))}
        </div>

        <aside className="tv-status-panel" aria-label="Controller status">
          <div>
            <p className="eyebrow">NOW CONTROLLING</p>
            <strong>{renderedState.active_app.replace('_', ' ')}</strong>
            {renderedState.channel_name && (
              <p>CH {String(renderedState.channel_number).padStart(2, '0')} · {renderedState.channel_name}</p>
            )}
          </div>
          <div className="volume-readout" aria-label={`System volume ${renderedState.volume}${renderedState.muted ? ', muted' : ''}`}>
            <span>VOL</span>
            <strong>{renderedState.muted ? 'MUTED' : renderedState.volume}</strong>
          </div>
        </aside>
      </section>

      <footer className="tv-footer">
        <section className="pairing-card" aria-label="Pair a phone remote">
          <div className="pairing-card-content">
            {pairing?.code ? (
              <div className="pairing-qr-wrapper" aria-label="Pairing QR Code">
                <QRCodeSVG
                  value={`https://${window.location.hostname}:${window.location.port || '8765'}/remote?code=${pairing.code}`}
                  size={92}
                  bgColor="#1b2434"
                  fgColor="#f7d488"
                  level="M"
                />
              </div>
            ) : null}
            <div className="pairing-text-wrapper">
              <p className="eyebrow">PAIR REMOTE / SCAN QR</p>
              <strong className="pairing-code">{pairing?.code ?? '------'}</strong>
              <p>Scan QR or enter this code in the Remote app.</p>
            </div>
          </div>
        </section>
        <section className="tv-help" aria-label="Keyboard controls">
          <span>Arrow keys navigate</span>
          <span>Enter selects</span>
          <span>Home returns here</span>
        </section>
      </footer>

      <div className="live-region" aria-live="polite" role="status">
        {renderedState.error_message ?? renderedState.status_message ?? lastError?.message ?? ''}
      </div>
    </main>
  )
}
