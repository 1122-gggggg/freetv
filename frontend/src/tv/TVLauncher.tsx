import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useControllerSocket } from '../api/useControllerSocket'
import type { Command } from '../types/protocol'
import { tileCommand, type TileId } from './navigation'

const TILES: ReadonlyArray<{ id: TileId; label: string; detail: string; badge: string }> = [
  { id: 'youtube', label: 'YouTube', detail: '用現有設定檔開啟', badge: 'YT' },
  { id: 'netflix', label: 'Netflix', detail: '用現有 Chrome 設定檔開啟', badge: 'N' },
  { id: 'news', label: '新聞', detail: '觀看 YouTube 直播新聞', badge: '新聞' },
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
  remote_url?: string | null
  lan_remote_url?: string | null
}

interface LocalHudMessage {
  id: number
  text: string
}

interface TransientHudProps {
  localMessageId: number | null
  message: string
  onDismissLocal: (id: number | null) => void
}

function TransientHud({
  localMessageId,
  message,
  onDismissLocal,
}: TransientHudProps): ReactElement | null {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setVisible(false)
      onDismissLocal(localMessageId)
    }, 2_200)
    return () => window.clearTimeout(timer)
  }, [localMessageId, onDismissLocal])

  if (!visible) return null
  return (
    <div className="tv-hud-overlay" role="status" aria-live="assertive">
      <span className="tv-hud-badge">{message}</span>
    </div>
  )
}

function pairingQrValue(pairing: PairingInfo): string | null {
  if (!pairing.remote_url) return null
  try {
    const remoteUrl = new URL(pairing.remote_url)
    remoteUrl.searchParams.set('code', pairing.code)
    return remoteUrl.toString()
  } catch {
    return null
  }
}

function isTileId(value: string): value is TileId {
  return TILES.some((tile) => tile.id === value)
}

export function TVLauncher(): ReactElement {
  const { status, state, lastError, sendCommand } = useControllerSocket('/ws/tv')
  const [pairing, setPairing] = useState<PairingInfo | null>(null)
  const [localHudMessage, setLocalHudMessage] = useState<LocalHudMessage | null>(null)
  const [isUpdating, setIsUpdating] = useState(false)
  const [stagedUpdateVersion, setStagedUpdateVersion] = useState<string | null>(null)
  const localHudSequenceRef = useRef(0)
  const tileRefs = useRef<Partial<Record<TileId, HTMLButtonElement>>>({})
  const focusedTile = state && isTileId(state.focused_tile) ? state.focused_tile : 'youtube'
  const pairingQr = pairing ? pairingQrValue(pairing) : null
  useEffect(() => {
    document.title = '我的電視'
    let cancelled = false
    let refreshTimer: number | undefined
    const fetchPairing = () => {
      fetch('/api/pairing')
        .then(async (response) => {
          if (!response.ok) throw new Error('目前無法取得配對碼。')
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

  const applyUpdate = () => {
    if (isUpdating) return
    setIsUpdating(true)
    fetch('/api/update/apply', { method: 'POST' })
      .then(async (res) => {
        let payload: {
          success?: boolean
          message?: string
          detail?: string
          restart_required?: boolean
        }
        try {
          payload = (await res.json()) as typeof payload
        } catch {
          throw new Error(
            res.ok
              ? '更新服務回應格式錯誤。'
              : `更新服務暫時無法使用（HTTP ${res.status}）。`,
          )
        }
        if (!res.ok || !payload.success) {
          throw new Error(payload.detail ?? payload.message ?? '更新失敗')
        }
        localHudSequenceRef.current += 1
        setLocalHudMessage({
          id: localHudSequenceRef.current,
          text: payload.restart_required
            ? '更新已下載，請重新啟動 FreeTV 完成安裝。'
            : (payload.message ?? '更新完成。'),
        })
        setStagedUpdateVersion(state?.update_available ?? null)
        setIsUpdating(false)
      })
      .catch(() => {
        localHudSequenceRef.current += 1
        setLocalHudMessage({
          id: localHudSequenceRef.current,
          text: '更新失敗，請檢查網路。',
        })
        setIsUpdating(false)
      })
  }
  const renderedState = state ?? {
    active_app: 'launcher',
    volume: 50,
    muted: false,
    brightness: 100,
    channel_number: null,
    channel_name: null,
    status_message: null,
    error_message: null,
    update_available: null,
  }

  const dismissLocalHud = useCallback((id: number | null) => {
    if (id === null) return
    setLocalHudMessage((current) => (current?.id === id ? null : current))
  }, [])
  const controllerHudMessage = renderedState.status_message || renderedState.error_message
  const updateStaged =
    stagedUpdateVersion !== null && stagedUpdateVersion === renderedState.update_available
  const displayedHudMessage = localHudMessage?.text ?? controllerHudMessage
  const hudCacheKey = localHudMessage
    ? `local-${localHudMessage.id}`
    : [
        controllerHudMessage,
        renderedState.volume,
        renderedState.muted,
        renderedState.brightness,
      ].join(':')
  return (
    <main className="tv-shell" aria-label="電視主畫面">
      <header className="tv-header">
        <div>
          <p className="eyebrow">電腦電視盒</p>
          <h1>我的電視</h1>
        </div>
        <div className={`connection-chip connection-${status}`} aria-live="polite">
          <span className="status-dot" aria-hidden="true" />
          {status === 'connected' ? '主畫面已連線' : status === 'authenticating' ? '主畫面驗證中' : status === 'connecting' ? '主畫面連線中' : status === 'disconnected' ? '主畫面已斷線' : '主畫面連線失敗'}
        </div>
      </header>

      {renderedState.update_available && (
        <div className="update-banner" role="alert">
          <span>🚀 發現新版本 FreeTV ({renderedState.update_available})</span>
          <button
            className="update-action-btn"
            type="button"
            disabled={isUpdating || updateStaged}
            onClick={applyUpdate}
          >
            {isUpdating ? '正在更新…' : updateStaged ? '已下載' : '立即更新'}
          </button>
        </div>
      )}

      <section className="tv-content" aria-label="應用程式">
        <div className="tv-grid">
          {TILES.map((tile) => (
            <button
              key={tile.id}
              ref={(element) => {
                if (element) tileRefs.current[tile.id] = element
              }}
              className={`tv-tile ${focusedTile === tile.id ? 'is-focused' : ''}`}
              type="button"
              aria-label={`開啟 ${tile.label}`}
              onClick={() => selectTile(tile.id)}
            >
              <span className="tile-badge" aria-hidden="true">{tile.badge}</span>
              <span className="tile-label">{tile.label}</span>
              <span className="tile-detail">{tile.detail}</span>
            </button>
          ))}
        </div>

        <aside className="tv-status-panel" aria-label="控制器狀態">
          <div>
            <p className="eyebrow">目前控制</p>
            <strong>
              {renderedState.active_app === 'youtube' ? 'YouTube'
                : renderedState.active_app === 'netflix' ? 'Netflix'
                : renderedState.active_app === 'news' ? '新聞'
                : renderedState.active_app === 'live_tv' ? '電視'
                : renderedState.active_app === 'browser' ? '瀏覽器'
                : '主畫面'}
            </strong>
            {renderedState.channel_name && (
              <p>頻道 {String(renderedState.channel_number).padStart(2, '0')} · {renderedState.channel_name}</p>
            )}
          </div>
          <div className="volume-readout" aria-label={`系統音量 ${renderedState.volume}${renderedState.muted ? '，已靜音' : ''}`}>
            <span>音量</span>
            <strong>{renderedState.muted ? '靜音' : `${renderedState.volume}%`}</strong>
          </div>
          <div className="volume-readout" aria-label={`螢幕亮度 ${renderedState.brightness}%`}>
            <span>亮度</span>
            <strong>{renderedState.brightness}%</strong>
          </div>
        </aside>
      </section>

      <footer className="tv-footer">
        <section className="pairing-card" aria-label="配對手機網頁遙控器">
          <div className="pairing-card-content">
            {pairingQr ? (
              <div className="pairing-qr-wrapper" aria-label="配對 QR 碼">
                <QRCodeSVG
                  value={pairingQr}
                  size={108}
                  bgColor="#1b2434"
                  fgColor="#f7d488"
                  level="M"
                />
              </div>
            ) : null}
            <div className="pairing-text-wrapper">
              <p className="eyebrow">手機網頁遙控器 · 穩定外網連線</p>
              <strong className="pairing-code">{pairing?.code ?? '------'}</strong>
              <p className="pairing-instructions">掃描 QR 碼後即可連線：</p>
              {pairing?.remote_url ? (
                <code className="pairing-url">{pairing.remote_url}</code>
              ) : (
                <p className="pairing-url-unavailable">目前無法產生遙控器連結。</p>
              )}
              {pairing?.lan_remote_url && pairing.lan_remote_url !== pairing.remote_url ? (
                <p className="pairing-instructions">
                  同 Wi-Fi 低延遲備用：<code className="pairing-url">{pairing.lan_remote_url}</code>
                </p>
              ) : null}
            </div>
          </div>
        </section>
        <section className="tv-help" aria-label="鍵盤操作">
          <span>方向鍵移動</span>
          <span>Enter 選取</span>
          <span>Home 回到這裡</span>
        </section>
      </footer>

      {displayedHudMessage && (
        <TransientHud
          key={hudCacheKey}
          localMessageId={localHudMessage?.id ?? null}
          message={displayedHudMessage}
          onDismissLocal={dismissLocalHud}
        />
      )}

      <div className="live-region" aria-live="polite" role="status">
        {renderedState.error_message ?? renderedState.status_message ?? lastError?.message ?? ''}
      </div>
    </main>
  )
}
