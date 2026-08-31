import {
  type FormEvent,
  type ReactElement,
  useEffect,
  useRef,
  useState,
} from 'react'

import { useControllerSocket } from '../api/useControllerSocket'
import { CommandButton } from '../components/CommandButton'
import type { Command, ControllerState, NetflixInputKind } from '../types/protocol'
import { rememberRemoteToken } from './tokenStorage'
import { YouTubeQualityPanel } from './YouTubeQualityPanel'
import './remote.css'


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



function activeAppLabel(app: ControllerState['active_app'] | undefined): string {
  const labels: Record<ControllerState['active_app'], string> = {
    launcher: '首頁',
    youtube: 'YouTube',
    netflix: 'Netflix',
    news: '新聞',
    live_tv: '電視',
    browser: '瀏覽器',
  }
  return app ? labels[app] : '等待電視盒'
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
    document.title = '我的電視遙控器'
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
      setError('請輸入電視上顯示的六位數配對碼。')
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
        throw new Error(payload.detail ?? '配對未被接受。')
      }
      rememberRemoteToken(payload.token)
      removePairingCodeFromAddressBar()
      onPaired(payload.token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '配對未被接受。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="remote-shell pairing-shell">
      <section className="pairing-form-card" aria-labelledby="pairing-title">
        <p className="eyebrow">電視遙控器</p>
        <h1 id="pairing-title">配對這支手機</h1>
        <p>掃描電視上的 QR 碼，或輸入目前的六位數配對碼。</p>
        <form onSubmit={submit}>
          <label htmlFor="pairing-code">配對碼</label>
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
            {submitting ? '配對中…' : '配對遙控器'}
          </button>
        </form>
        <p className="form-status" aria-live="polite">{error ?? '此遙控器只能控制已配對的電腦電視盒。'}</p>
      </section>
    </main>
  )
}

const NETFLIX_INPUT_PRESENTATION: Partial<
  Record<
    NetflixInputKind,
    {
      type: 'email' | 'password' | 'text'
      inputMode: 'email' | 'text' | 'numeric'
      autoComplete: 'username' | 'current-password' | 'one-time-code'
      placeholder: string
    }
  >
> = {
  email: {
    type: 'email',
    inputMode: 'email',
    autoComplete: 'username',
    placeholder: '請輸入 Netflix 電子郵件或手機號碼',
  },
  password: {
    type: 'password',
    inputMode: 'text',
    autoComplete: 'current-password',
    placeholder: '請輸入 Netflix 密碼',
  },
  code: {
    type: 'text',
    inputMode: 'numeric',
    autoComplete: 'one-time-code',
    placeholder: '請輸入驗證碼 (OTP)',
  },
}

function RemoteControl({ token, onForget, onAuthenticationFailed }: RemoteControlProps): ReactElement {
  const { status, state, lastAcknowledgement, lastError, sendCommand, sendSearch, sendText } = useControllerSocket('/ws/remote', token)
  const [query, setQuery] = useState('')
  const [typed, setTyped] = useState('')
  const [netflixTyped, setNetflixTyped] = useState('')
  const [pendingNetflixRequest, setPendingNetflixRequest] = useState<string | null>(null)
  const [netflixLocalSendFailed, setNetflixLocalSendFailed] = useState(false)
  const [hideSecret, setHideSecret] = useState(true)
  const [forgetError, setForgetError] = useState<string | null>(null)
  const [forgetting, setForgetting] = useState(false)
  const [updateStatus, setUpdateStatus] = useState<string | null>(null)
  const [updating, setUpdating] = useState(false)
  const [stagedUpdateVersion, setStagedUpdateVersion] = useState<string | null>(null)
  const liveTextTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const controlsDisabled = status !== 'connected'
  const canTypeIntoApp =
    state?.active_app === 'youtube' ||
    state?.active_app === 'netflix' ||
    state?.active_app === 'browser' ||
    state?.active_app === 'news'
  const netflixContext =
    state?.active_app === 'netflix' ? (state.netflix_context ?? null) : null
  const netflixInput = netflixContext
    ? NETFLIX_INPUT_PRESENTATION[netflixContext.input_kind]
    : undefined
  const repeatDirectionalNavigation = netflixContext?.stage !== 'browse'
  const netflixSemanticKey = JSON.stringify([
    status === 'connected' ? (state?.active_app ?? null) : status,
    netflixContext?.stage ?? null,
    netflixContext?.input_kind ?? null,
    netflixContext?.focused_title ?? null,
    netflixContext?.has_error ?? null,
  ])
  const [previousNetflixSemanticKey, setPreviousNetflixSemanticKey] =
    useState(netflixSemanticKey)
  const channelControlsVisible =
    state?.active_app === undefined ||
    state.active_app === 'news' ||
    state.active_app === 'live_tv'
  const fallbackKeyboardVisible =
    state?.active_app === 'netflix' &&
    (!netflixContext || netflixContext.stage === 'unknown')
  const videoSearchVisible = state?.active_app !== 'netflix'
  if (previousNetflixSemanticKey !== netflixSemanticKey) {
    setPreviousNetflixSemanticKey(netflixSemanticKey)
    setNetflixTyped('')
    setPendingNetflixRequest(null)
    setNetflixLocalSendFailed(false)
  }
  const netflixAcknowledgementFailed =
    pendingNetflixRequest !== null &&
    lastAcknowledgement?.request_id === pendingNetflixRequest &&
    !lastAcknowledgement.success
  const waitingForNetflix =
    pendingNetflixRequest !== null && !netflixAcknowledgementFailed

  const cancelLiveText = () => {
    if (liveTextTimerRef.current !== null) {
      clearTimeout(liveTextTimerRef.current)
      liveTextTimerRef.current = null
    }
  }

  const scheduleLiveText = (value: string) => {
    cancelLiveText()
    liveTextTimerRef.current = setTimeout(() => {
      liveTextTimerRef.current = null
      if (value.length > 0) sendText(value, false)
    }, 125)
  }

  useEffect(() => {
    cancelLiveText()
  }, [status, netflixSemanticKey])

  useEffect(() => cancelLiveText, [])




  useEffect(() => {
    if (lastError?.code === 'authentication_failed') onAuthenticationFailed()
  }, [lastError, onAuthenticationFailed])




  const command = (value: Command) => {
    if (!sendCommand(value)) navigator.vibrate?.([16, 35, 16])
  }


  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (controlsDisabled || trimmed.length === 0) return
    sendSearch(trimmed)
  }

  const submitTyped = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (controlsDisabled || typed.length === 0) return
    cancelLiveText()
    if (sendText(typed, false)) setTyped('')
  }

  const submitNetflix = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (
      controlsDisabled ||
      waitingForNetflix ||
      netflixTyped.length === 0 ||
      !netflixContext?.can_submit
    ) {
      return
    }
    cancelLiveText()
    setNetflixLocalSendFailed(false)
    const requestId = sendText(netflixTyped, true)
    if (!requestId) {
      setNetflixLocalSendFailed(true)
      return
    }
    setNetflixTyped('')
    setPendingNetflixRequest(requestId)
  }


  const forget = async () => {
    setForgetting(true)
    setForgetError(null)
    try {
      await onForget()
    } catch (reason) {
      setForgetError(reason instanceof Error ? reason.message : '無法解除這支遙控器的配對。')
      setForgetting(false)
    }
  }

  const applyUpdate = async () => {
    if (!state?.update_available || updating || controlsDisabled) return
    setUpdating(true)
    setUpdateStatus('正在下載更新…')
    try {
      const response = await fetch('/api/update/apply', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      let payload: {
        success?: boolean
        message?: string
        detail?: string
        version?: string
        restart_required?: boolean
      }
      try {
        payload = (await response.json()) as typeof payload
      } catch {
        throw new Error(
          response.ok
            ? '更新服務回應格式錯誤。'
            : `更新服務暫時無法使用（HTTP ${response.status}）。`,
        )
      }
      if (!response.ok || !payload.success) {
        throw new Error(payload.detail ?? payload.message ?? '更新失敗，請稍後再試。')
      }
      setUpdateStatus(
        payload.restart_required
          ? '更新已下載，重新啟動電視盒後生效'
          : (payload.message ?? '更新完成。'),
      )
      setStagedUpdateVersion(payload.version ?? state.update_available)
    } catch (reason) {
      setUpdateStatus(
        reason instanceof TypeError
          ? '無法連上電視盒，請確認網路連線後重試。'
          : reason instanceof Error
            ? reason.message
            : '更新失敗，請稍後再試。',
      )
    } finally {
      setUpdating(false)
    }
  }


  return (
    <main className="remote-shell" aria-label="電視遙控器">
      <header className="remote-header">
        <div>
          <p className="eyebrow">電視遙控器</p>
          <h1>遙控器</h1>
        </div>
        <button className="forget-button" disabled={forgetting} type="button" onClick={() => void forget()}>
          {forgetting ? '解除中…' : '解除配對'}
        </button>
      </header>

      <div className="remote-summary" aria-label="電視狀態摘要" aria-live="polite">
        <span className={`remote-summary-status connection-${status}`}>
          <span className="status-dot" aria-hidden="true" />
          {status === 'connected' ? '已連線' : status === 'authenticating' ? '驗證中' : status === 'connecting' ? '連線中' : status === 'disconnected' ? '已斷線' : '連線失敗'}
        </span>
        <span>目前：<strong>{activeAppLabel(state?.active_app)}</strong></span>
      </div>

      {state?.update_available ? <section className="remote-update-card" aria-labelledby="remote-update-title">
        <div><strong id="remote-update-title">有新的 FreeTV 更新</strong><span>版本 {state.update_available}</span></div>
        <button
          type="button"
          onClick={() => void applyUpdate()}
          disabled={
            controlsDisabled || updating || stagedUpdateVersion === state.update_available
          }
        >
          {updating
            ? '更新中…'
            : stagedUpdateVersion === state.update_available
              ? '已下載'
              : '立即更新'}
        </button>
        {updateStatus ? <p aria-live="polite">{updateStatus}</p> : null}
      </section> : null}

      {controlsDisabled ? (
        <p className="remote-connection-note" aria-live="polite">
          電視盒重新連線後，按鍵會自動解鎖。
        </p>
      ) : null}
      {videoSearchVisible ? (
        <section id="remote-panel-search" className="search-card" aria-labelledby="search-title">
          <p className="eyebrow">影片搜尋</p>
          <h2 id="search-title">搜尋影片</h2>
          <form onSubmit={submitSearch}>
            <input
              aria-label="搜片"
              placeholder="輸入片名或關鍵字…"
              disabled={controlsDisabled}
              maxLength={128}
              value={query}
              onChange={(event) => setQuery(event.target.value.slice(0, 128))}
            />
            <button className="remote-button search-submit" disabled={controlsDisabled || query.trim().length === 0} type="submit">
              搜片
            </button>
          </form>
        </section>
      ) : null}

      <h2 className="remote-section-title">首頁</h2>
      <section id="remote-panel-home" aria-label="首頁應用程式" className="remote-grid three-column apps-row">
        <CommandButton command="OPEN_YOUTUBE" label="YouTube" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_NETFLIX" label="Netflix" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_NEWS" label="新聞" onCommand={command} disabled={controlsDisabled} />
      </section>

      {netflixContext && netflixContext.stage !== 'unknown' ? (
        <section
          id="remote-panel-input"
          className={`netflix-context-card ${netflixContext.has_error ? 'is-error' : ''}`}
        >
          <p className="eyebrow">Netflix 電視情境</p>
          <h2 id="netflix-context-title">
            {netflixContext.stage === 'browse' ? 'Netflix 片單' : 'Netflix 輸入'}
          </h2>
          {netflixContext.has_error ? (
            <p className="netflix-context-error" role="status" aria-live="polite">
              登入或驗證失敗，請檢查電視畫面後重試
            </p>
          ) : null}
          {netflixInput ? (
            <form onSubmit={submitNetflix}>
              <input
                aria-label="Netflix 情境輸入"
                type={netflixInput.type}
                inputMode={netflixInput.inputMode}
                autoCapitalize="none"
                autoCorrect="off"
                autoComplete={netflixInput.autoComplete}
                spellCheck={false}
                maxLength={256}
                placeholder={netflixInput.placeholder}
                disabled={controlsDisabled || waitingForNetflix}
                value={netflixTyped}
                onChange={(event) => {
                  const val = event.target.value.slice(0, 256)
                  setNetflixTyped(val)
                  if (netflixLocalSendFailed) setNetflixLocalSendFailed(false)
                  if (val.length > 0) scheduleLiveText(val)
                  else cancelLiveText()
                }}
              />
              <button
                className="remote-button netflix-context-submit"
                type="submit"
                aria-label="送出 Netflix 輸入"
                disabled={
                  controlsDisabled ||
                  waitingForNetflix ||
                  netflixTyped.length === 0 ||
                  !netflixContext.can_submit
                }
              >
                送到電視並繼續
              </button>
            </form>
          ) : netflixContext.stage === 'browse' ? (
            <div className="netflix-browse-context">
              {netflixContext.focused_title ? (
                <p className="netflix-focused-title">
                  目前選取：{netflixContext.focused_title}
                </p>
              ) : null}
              <p>左右換片、上下換列，按確定播放。</p>
            </div>
          ) : (
            <p>使用方向鍵與確定鍵操作目前 Netflix 畫面。</p>
          )}
          {waitingForNetflix ? (
            <p className="netflix-context-waiting" role="status" aria-live="polite">
              等待電視端回應...
            </p>
          ) : null}
          {netflixAcknowledgementFailed || netflixLocalSendFailed ? (
            <p className="netflix-context-error" role="status" aria-live="polite">
              無法送出，請重試
            </p>
          ) : null}
        </section>
      ) : null}

      <h2 className="remote-section-title">遙控</h2>
      <section id="remote-panel-remote" aria-label="方向鍵" className="remote-direction-pad">
        <CommandButton command="BACK" label="返回" onCommand={command} className="direction-back" disabled={controlsDisabled} />
        <CommandButton command="NAV_UP" label="上" onCommand={command} className="direction-up" disabled={controlsDisabled} repeatOnHold={repeatDirectionalNavigation} />
        <CommandButton command="PLAY_PAUSE" label="播放／暫停" onCommand={command} className="direction-play" disabled={controlsDisabled} />
        <CommandButton command="NAV_LEFT" label="左" onCommand={command} className="direction-left" disabled={controlsDisabled} repeatOnHold={repeatDirectionalNavigation} />
        <CommandButton command="OK" label="確定" onCommand={command} className="direction-ok" disabled={controlsDisabled} />
        <CommandButton command="NAV_RIGHT" label="右" onCommand={command} className="direction-right" disabled={controlsDisabled} repeatOnHold={repeatDirectionalNavigation} />
        <CommandButton command="SEEK_BACKWARD_5" label="倒退 5 秒" onCommand={command} className="direction-rewind" disabled={controlsDisabled} />
        <CommandButton command="NAV_DOWN" label="下" onCommand={command} className="direction-down" disabled={controlsDisabled} repeatOnHold={repeatDirectionalNavigation} />
        <CommandButton command="SEEK_FORWARD_5" label="快轉 5 秒" onCommand={command} className="direction-forward" disabled={controlsDisabled} />
      </section>

      <h2 className="remote-section-title">調整</h2>
      <section id="remote-panel-adjust" aria-label="音量、倍速與亮度" className="remote-sliders-row">
        {/* Volume Slider */}
        <div className="slider-card">
          <p className="slider-header">音量</p>
          <div className="slider-track">
            <div className="slider-fill vol-fill" style={{ height: `${state?.volume ?? 50}%` }} />
            <CommandButton command="VOLUME_UP" label="音量 +" onCommand={command} disabled={controlsDisabled} repeatOnHold className="slider-step-btn slider-increase" />
            <CommandButton command="MUTE" label={state?.muted ? '靜音' : `${state?.volume ?? 50}%`} onCommand={command} disabled={controlsDisabled} className={`slider-pill ${state?.muted ? 'is-muted' : ''}`} />
            <CommandButton command="VOLUME_DOWN" label="音量 −" onCommand={command} disabled={controlsDisabled} repeatOnHold className="slider-step-btn slider-decrease" />
          </div>
        </div>

        {/* Speed Slider */}
        <div className="slider-card">
          <p className="slider-header">倍速</p>
          <div className="slider-track">
            <CommandButton command="SPEED_UP" label="倍速 +" onCommand={command} disabled={controlsDisabled} className="slider-step-btn slider-increase" />
            <div className="slider-pill speed-pill">倍速</div>
            <CommandButton command="SPEED_DOWN" label="倍速 −" onCommand={command} disabled={controlsDisabled} className="slider-step-btn slider-decrease" />
          </div>
        </div>

        {/* Brightness Slider */}
        <div className="slider-card">
          <p className="slider-header">亮度</p>
          <div className="slider-track">
            <div className="slider-fill bright-fill" style={{ height: `${state?.brightness ?? 100}%` }} />
            <CommandButton command="BRIGHTNESS_UP" label="亮度 +" onCommand={command} disabled={controlsDisabled} repeatOnHold className="slider-step-btn slider-increase" />
            <div className="slider-pill">{state?.brightness ?? 100}%</div>
            <CommandButton command="BRIGHTNESS_DOWN" label="亮度 −" onCommand={command} disabled={controlsDisabled} repeatOnHold className="slider-step-btn slider-decrease" />
          </div>
        </div>
      </section>

      {state?.active_app === 'youtube' ? (
        <YouTubeQualityPanel
          token={token}
          onAuthenticationFailed={onAuthenticationFailed}
        />
      ) : null}


      {channelControlsVisible ? (
        <section
          id="remote-panel-channel"
          className="remote-grid two-column channel-row"
          aria-label="頻道切換"
        >
          <CommandButton
            command="CHANNEL_DOWN"
            label={state?.active_app === 'news' && state.previous_channel_name
              ? `上一台：${state.previous_channel_name}`
              : '頻道 −'}
            onCommand={command}
            disabled={controlsDisabled}
            repeatOnHold
          />
          <CommandButton
            command="CHANNEL_UP"
            label={state?.active_app === 'news' && state.next_channel_name
              ? `下一台：${state.next_channel_name}`
              : '頻道 +'}
            onCommand={command}
            disabled={controlsDisabled}
            repeatOnHold
          />
        </section>
      ) : null}

      {fallbackKeyboardVisible ? (
      <section id="remote-panel-input" className="search-card">
        <p className="eyebrow">鍵盤</p>
        <h2 id="keyboard-title">輸入帳號或密碼</h2>
        <p className="keyboard-description">
          {canTypeIntoApp
            ? '先點電視上的輸入欄，再從這裡打字送出。密碼不會被記住。'
            : '先開啟 Netflix 或 YouTube，點選輸入欄，再從這裡輸入。'}
        </p>
        <form onSubmit={submitTyped}>
          <input
            aria-label="遙控輸入"
            placeholder="電子郵件、密碼或驗證碼…"
            disabled={controlsDisabled}
            maxLength={256}
            type={hideSecret ? 'password' : 'text'}
            autoCapitalize="none"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => {
              const val = event.target.value.slice(0, 256)
              setTyped(val)
              if (val.length > 0) scheduleLiveText(val)
              else cancelLiveText()
            }}
          />
          <button className="remote-button search-submit" disabled={controlsDisabled || typed.length === 0} type="submit">
            送出
          </button>
        </form>
        <div className="keyboard-actions">
          <button
            className="remote-button"
            disabled={controlsDisabled}
            type="button"
            onClick={() => setHideSecret((current) => !current)}
            aria-pressed={!hideSecret}
          >
            {hideSecret ? '顯示文字' : '隱藏文字'}
          </button>
          <CommandButton command="TAB" label="下一欄" onCommand={command} disabled={controlsDisabled} />
        </div>
      </section>
      ) : null}


      <footer className="remote-feedback" aria-live="polite">
        {forgetError ?? state?.error_message ?? state?.status_message ?? lastError?.message ?? lastAcknowledgement?.message ?? (lastAcknowledgement?.success ? '指令已送出。' : '就緒。')}
      </footer>
    </main>
  )
}
