import { type ChangeEvent, type KeyboardEvent, type PointerEvent, useEffect, useState } from 'react'

interface YouTubeQualityInfo {
  video_id: string
  current: string
  available: string[]
}

interface YouTubeQualityPanelProps {
  token: string
  onAuthenticationFailed: () => void
}

const QUALITY_LABELS: Record<string, string> = {
  auto: '自動',
  tiny: '144p',
  small: '240p',
  medium: '360p',
  large: '480p',
  hd720: '720p',
  hd1080: '1080p',
  hd1440: '1440p',
  hd2160: '2160p',
  highres: '最高畫質',
}

function qualityLabel(quality: string): string {
  return QUALITY_LABELS[quality] ?? quality
}

function parseQualityInfo(value: unknown): YouTubeQualityInfo | null {
  if (typeof value !== 'object' || value === null) return null
  const record = value as Record<string, unknown>
  if (
    typeof record.video_id !== 'string' ||
    typeof record.current !== 'string' ||
    !Array.isArray(record.available) ||
    record.available.length === 0 ||
    !record.available.every((quality) => typeof quality === 'string')
  ) {
    return null
  }
  return {
    video_id: record.video_id,
    current: record.current,
    available: record.available,
  }
}

export function YouTubeQualityPanel({
  token,
  onAuthenticationFailed,
}: YouTubeQualityPanelProps) {
  const [info, setInfo] = useState<YouTubeQualityInfo | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('偵測目前影片畫質…')

  useEffect(() => {
    let cancelled = false
    let refreshTimer: number | undefined

    const refresh = async () => {
      try {
        const response = await fetch('/api/youtube/quality', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (response.status === 401) {
          cancelled = true
          onAuthenticationFailed()
          return
        }
        if (!response.ok) throw new Error('quality unavailable')
        const next = parseQualityInfo(await response.json())
        if (!next) throw new Error('invalid quality response')
        if (cancelled) return
        setInfo(next)
        setSelectedIndex(Math.max(0, next.available.indexOf(next.current)))
        setMessage(`已偵測 ${qualityLabel(next.available.at(-1) ?? next.current)} 最高畫質`)
      } catch {
        if (!cancelled) setMessage('播放 YouTube 影片後會自動偵測畫質。')
      } finally {
        if (!cancelled) refreshTimer = window.setTimeout(refresh, 2000)
      }
    }

    void refresh()
    return () => {
      cancelled = true
      window.clearTimeout(refreshTimer)
    }
  }, [onAuthenticationFailed, token])

  const selectQuality = async (index: number) => {
    const quality = info?.available[index]
    if (!quality || quality === info.current || pending) return
    setPending(true)
    setMessage(`切換至 ${qualityLabel(quality)}…`)
    try {
      const response = await fetch('/api/youtube/quality', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ quality }),
      })
      if (response.status === 401) {
        onAuthenticationFailed()
        return
      }
      if (!response.ok) throw new Error('quality unavailable')
      const next = parseQualityInfo(await response.json())
      if (!next) throw new Error('invalid quality response')
      setInfo(next)
      setSelectedIndex(Math.max(0, next.available.indexOf(next.current)))
      setMessage(`畫質已切換為 ${qualityLabel(next.current)}`)
    } catch {
      setSelectedIndex(Math.max(0, info.available.indexOf(info.current)))
      setMessage('無法切換這個畫質，請稍後重試。')
    } finally {
      setPending(false)
    }
  }

  const updateSelection = (event: ChangeEvent<HTMLInputElement>) => {
    setSelectedIndex(Number(event.currentTarget.value))
  }
  const commitPointerSelection = (event: PointerEvent<HTMLInputElement>) => {
    void selectQuality(Number(event.currentTarget.value))
  }
  const commitKeyboardSelection = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key.startsWith('Arrow') || event.key === 'Home' || event.key === 'End') {
      void selectQuality(Number(event.currentTarget.value))
    }
  }

  const current = info?.available[selectedIndex] ?? info?.current ?? 'auto'
  const minimum = info?.available[0] ?? current
  const maximum = info?.available.at(-1) ?? current

  return (
    <section className="youtube-quality-card" aria-labelledby="youtube-quality-title">
      <div className="youtube-quality-heading">
        <div>
          <p className="eyebrow">YouTube 畫質</p>
          <h2 id="youtube-quality-title">影片畫質</h2>
        </div>
        <strong>{qualityLabel(current)}</strong>
      </div>
      {info ? (
        <>
          <input
            aria-label="YouTube 畫質"
            type="range"
            min={0}
            max={Math.max(0, info.available.length - 1)}
            step={1}
            value={selectedIndex}
            disabled={pending || info.available.length < 2}
            onChange={updateSelection}
            onPointerUp={commitPointerSelection}
            onKeyUp={commitKeyboardSelection}
          />
          <div className="youtube-quality-scale" aria-hidden="true">
            <span>{qualityLabel(minimum)}</span>
            <span>最高 {qualityLabel(maximum)}</span>
          </div>
        </>
      ) : null}
      <p className="youtube-quality-status" aria-live="polite">{message}</p>
    </section>
  )
}
