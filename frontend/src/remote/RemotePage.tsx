import { type FormEvent, type ReactElement, useEffect, useRef, useState } from 'react'

import { useControllerSocket } from '../api/useControllerSocket'
import { CommandButton } from '../components/CommandButton'
import type { Command } from '../types/protocol'
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

function RemoteControl({ token, onForget, onAuthenticationFailed }: RemoteControlProps): ReactElement {
  const { status, state, lastAcknowledgement, lastError, sendCommand, sendSearch } = useControllerSocket('/ws/remote', token)
  const [query, setQuery] = useState('')
  const [forgetError, setForgetError] = useState<string | null>(null)
  const [forgetting, setForgetting] = useState(false)
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const controlsDisabled = status !== 'connected'

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
