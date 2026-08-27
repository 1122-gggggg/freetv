import { type FormEvent, type ReactElement, useEffect, useRef, useState } from 'react'

import { useControllerSocket } from '../api/useControllerSocket'
import { CommandButton } from '../components/CommandButton'
import type { Command, NetflixInputKind } from '../types/protocol'
import { rememberRemoteToken } from './tokenStorage'

interface SpeechRecognitionResultItem {
  transcript: string
}

interface SpeechRecognitionResultList {
  [index: number]: SpeechRecognitionResultItem
  length: number
}

interface SpeechRecognitionResultEvent {
  results: {
    [index: number]: SpeechRecognitionResultList
    length: number
  }
}

interface SpeechRecognitionInstance {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null
  onerror: ((event: unknown) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const win = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return win.SpeechRecognition || win.webkitSpeechRecognition || null
}

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
  const [hideSecret, setHideSecret] = useState(false)
  const [forgetError, setForgetError] = useState<string | null>(null)
  const [forgetting, setForgetting] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
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
  const netflixSemanticKey = JSON.stringify([
    status === 'connected' ? (state?.active_app ?? null) : status,
    netflixContext?.stage ?? null,
    netflixContext?.input_kind ?? null,
    netflixContext?.focused_title ?? null,
    netflixContext?.has_error ?? null,
  ])
  const [previousNetflixSemanticKey, setPreviousNetflixSemanticKey] =
    useState(netflixSemanticKey)
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



  const SpeechRecognitionAPI = getSpeechRecognition()
  const speechSupported = SpeechRecognitionAPI !== null

  useEffect(() => {
    if (lastError?.code === 'authentication_failed') onAuthenticationFailed()
  }, [lastError, onAuthenticationFailed])



  useEffect(() => () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
  }, [])

  const command = (value: Command) => {
    if (!sendCommand(value)) navigator.vibrate?.([16, 35, 16])
  }

  const handleVoice = () => {
    if (controlsDisabled || !SpeechRecognitionAPI) return
    try {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
        recognitionRef.current = null
      }
      const recognition = new SpeechRecognitionAPI()
      recognitionRef.current = recognition
      recognition.lang = 'zh-TW'
      recognition.interimResults = false
      recognition.maxAlternatives = 1
      recognition.onresult = (event: SpeechRecognitionResultEvent) => {
        const transcript = event.results?.[0]?.[0]?.transcript?.trim()
        if (transcript) {
          setQuery(transcript)
          sendSearch(transcript)
        }
        setListening(false)
      }
      recognition.onerror = () => {
        setListening(false)
      }
      recognition.onend = () => {
        setListening(false)
      }
      setListening(true)
      recognition.start()
    } catch {
      setListening(false)
    }

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

      <div className={`connection-chip connection-${status}`} aria-live="polite">
        <span className="status-dot" aria-hidden="true" />
        {status === 'connected' ? '已連線' : status === 'authenticating' ? '驗證中' : status === 'connecting' ? '連線中' : status === 'disconnected' ? '已斷線' : '連線失敗'}
      </div>
      <p className="remote-connection-note" aria-live="polite">
        {controlsDisabled
          ? '電視盒重新連線後，按鍵會自動解鎖。'
          : '長按方向、音量或頻道鍵可連續送出。'}
      </p>

      <section className="remote-grid three-column apps-row" aria-label="應用程式">
        <CommandButton command="OPEN_YOUTUBE" label="YouTube" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_NETFLIX" label="Netflix" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="OPEN_NEWS" label="新聞" onCommand={command} disabled={controlsDisabled} />
      </section>

      {netflixContext && netflixContext.stage !== 'unknown' ? (
        <section
          className={`netflix-context-card ${netflixContext.has_error ? 'is-error' : ''}`}
          aria-labelledby="netflix-context-title"
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
                  setNetflixTyped(event.target.value.slice(0, 256))
                  if (netflixLocalSendFailed) setNetflixLocalSendFailed(false)
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

      <section className="remote-direction-pad" aria-label="方向鍵">
        <CommandButton command="NAV_UP" label="上" onCommand={command} className="direction-up" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="NAV_LEFT" label="左" onCommand={command} className="direction-left" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="OK" label="確定" onCommand={command} className="direction-ok" disabled={controlsDisabled} />
        <CommandButton command="NAV_RIGHT" label="右" onCommand={command} className="direction-right" disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="NAV_DOWN" label="下" onCommand={command} className="direction-down" disabled={controlsDisabled} repeatOnHold />
      </section>

      <section className="remote-grid two-column" aria-label="主要按鍵">
        <CommandButton command="BACK" label="返回" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="HOME" label="主畫面" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="CHANNEL_UP" label="頻道 +" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="CHANNEL_DOWN" label="頻道 −" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="VOLUME_UP" label="音量 +" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="VOLUME_DOWN" label="音量 −" onCommand={command} disabled={controlsDisabled} repeatOnHold />
        <CommandButton command="MUTE" label="靜音" onCommand={command} disabled={controlsDisabled} />
        <CommandButton command="PLAY_PAUSE" label="播放／暫停" onCommand={command} disabled={controlsDisabled} />
      </section>

      <section className="remote-voice-row" aria-label="語音搜尋">
        <button
          className={`remote-button voice-button ${listening ? 'is-listening' : ''}`}
          disabled={controlsDisabled || !speechSupported}
          type="button"
          onClick={handleVoice}
        >
          {listening ? '聆聽中…' : '語音'}
        </button>
      </section>

      {!netflixContext || netflixContext.stage === 'unknown' ? (
      <section className="search-card" aria-labelledby="keyboard-title">
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
            onChange={(event) => setTyped(event.target.value.slice(0, 256))}
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
          >
            {hideSecret ? '顯示文字' : '隱藏文字'}
          </button>
          <CommandButton command="TAB" label="下一欄" onCommand={command} disabled={controlsDisabled} />
        </div>
      </section>
      ) : null}

      <section className="search-card" aria-labelledby="search-title">
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

      <footer className="remote-feedback" aria-live="polite">
        {forgetError ?? state?.error_message ?? state?.status_message ?? lastError?.message ?? lastAcknowledgement?.message ?? (lastAcknowledgement?.success ? '指令已送出。' : '就緒。')}
      </footer>
    </main>
  )
}
