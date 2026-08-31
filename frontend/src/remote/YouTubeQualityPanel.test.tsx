import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { YouTubeQualityPanel } from './YouTubeQualityPanel'

const token = 'paired-token-value-that-is-long-enough'
const detectedQuality = {
  video_id: 'video-alpha',
  current: 'tiny',
  available: ['tiny', 'hd720', 'hd1080'],
}

describe('YouTubeQualityPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('detects the current video qualities and displays its maximum', async () => {
    const fetchQuality = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(detectedQuality), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchQuality)

    render(<YouTubeQualityPanel token={token} onAuthenticationFailed={vi.fn()} />)

    const slider = await screen.findByRole('slider', { name: 'YouTube 畫質' })
    expect((slider as HTMLInputElement).max).toBe('2')
    expect(screen.getByText('最高 1080p')).toBeTruthy()
    expect(fetchQuality).toHaveBeenCalledWith(
      '/api/youtube/quality',
      expect.objectContaining({ headers: { Authorization: `Bearer ${token}` } }),
    )
  })

  it('sets the selected quality when dragging the dashboard', async () => {
    const fetchQuality = vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      const quality = init?.method === 'POST'
        ? { ...detectedQuality, current: 'hd720' }
        : detectedQuality
      return Promise.resolve(
        new Response(JSON.stringify(quality), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchQuality)

    render(<YouTubeQualityPanel token={token} onAuthenticationFailed={vi.fn()} />)
    const slider = await screen.findByRole('slider', { name: 'YouTube 畫質' })
    fireEvent.change(slider, { target: { value: '1' } })
    fireEvent.pointerUp(slider, { pointerId: 1 })

    await waitFor(() => {
      expect(fetchQuality).toHaveBeenCalledWith(
        '/api/youtube/quality',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ quality: 'hd720' }),
        }),
      )
    })
    expect(await screen.findByText('畫質已切換為 720p')).toBeTruthy()
  })
})
